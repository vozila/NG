from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.app import create_app
from core.db import emit_event, query_events_for_rid
from features import postcall_reconcile


def _set_env(monkeypatch, *, db_path: str) -> None:
    monkeypatch.setenv("VOZ_DB_PATH", db_path)
    monkeypatch.setenv("VOZ_FEATURE_POSTCALL_RECONCILE", "1")
    monkeypatch.setenv("VOZ_POSTCALL_RECONCILE_ENABLED", "1")
    monkeypatch.setenv("VOZ_ADMIN_API_KEY", "admin-secret")


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer admin-secret"}


def _seed_call_stopped(*, tenant_id: str, rid: str, ai_mode: str) -> None:
    emit_event(
        tenant_id=tenant_id,
        rid=rid,
        event_type="flow_a.call_stopped",
        payload_dict={"tenant_id": tenant_id, "rid": rid, "ai_mode": ai_mode, "reason": "twilio_stop"},
        idempotency_key=f"{rid}:call_stopped",
    )


def _seed_transcript(*, tenant_id: str, rid: str, text: str) -> None:
    emit_event(
        tenant_id=tenant_id,
        rid=rid,
        event_type="flow_a.transcript_completed",
        payload_dict={"tenant_id": tenant_id, "rid": rid, "transcript": text, "transcript_len": len(text)},
    )


def test_postcall_reconcile_requires_admin_bearer(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "reconcile_auth.sqlite3"))
    client = TestClient(create_app())

    missing = client.post("/admin/postcall/reconcile", json={"tenant_id": "tenant_demo"})
    assert missing.status_code == 401

    invalid = client.post(
        "/admin/postcall/reconcile",
        json={"tenant_id": "tenant_demo"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert invalid.status_code == 401


def test_postcall_reconcile_creates_missing_and_skips_existing(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "reconcile_main.sqlite3"))

    _seed_call_stopped(tenant_id="tenant_demo", rid="rid-1", ai_mode="owner")
    _seed_transcript(tenant_id="tenant_demo", rid="rid-1", text="Need follow up")

    _seed_call_stopped(tenant_id="tenant_demo", rid="rid-2", ai_mode="owner")
    _seed_transcript(tenant_id="tenant_demo", rid="rid-2", text="Already processed")
    emit_event(
        tenant_id="tenant_demo",
        rid="rid-2",
        event_type="postcall.summary",
        payload_dict={"tenant_id": "tenant_demo", "rid": "rid-2", "headline": "existing", "bullet_points": ["x"]},
        idempotency_key="postcall_extract:rid-2:reconcile-rid-2-v1:summary",
    )

    async def _fake_trigger_extract(*, tenant_id: str, rid: str, ai_mode: str, idempotency_key: str):
        emit_event(
            tenant_id=tenant_id,
            rid=rid,
            event_type="postcall.summary",
            payload_dict={"tenant_id": tenant_id, "rid": rid, "headline": "created", "bullet_points": ["x"]},
            idempotency_key=f"postcall_extract:{rid}:{idempotency_key}:summary",
        )
        emit_event(
            tenant_id=tenant_id,
            rid=rid,
            event_type="postcall.lead",
            payload_dict={"tenant_id": tenant_id, "rid": rid, "qualified": False},
            idempotency_key=f"postcall_extract:{rid}:{idempotency_key}:lead",
        )
        return 200, '{"ok":true}'

    monkeypatch.setattr(postcall_reconcile, "_trigger_extract", _fake_trigger_extract)
    client = TestClient(create_app())

    resp = client.post(
        "/admin/postcall/reconcile",
        json={"tenant_id": "tenant_demo", "since_ts": 0, "limit": 50},
        headers=_auth(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["attempted"] == 1
    assert body["created"] == 1
    assert body["skipped"] == 1
    assert body["errors"] == 0

    rid1_summary = query_events_for_rid("tenant_demo", "rid-1", event_type="postcall.summary", limit=10)
    rid1_lead = query_events_for_rid("tenant_demo", "rid-1", event_type="postcall.lead", limit=10)
    rid2_summary = query_events_for_rid("tenant_demo", "rid-2", event_type="postcall.summary", limit=10)
    assert len(rid1_summary) == 1
    assert len(rid1_lead) == 1
    assert len(rid2_summary) == 1


def test_postcall_reconcile_tenant_isolation(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "reconcile_tenant.sqlite3"))
    _seed_call_stopped(tenant_id="tenant_a", rid="rid-a", ai_mode="owner")
    _seed_transcript(tenant_id="tenant_a", rid="rid-a", text="A")
    _seed_call_stopped(tenant_id="tenant_b", rid="rid-b", ai_mode="owner")
    _seed_transcript(tenant_id="tenant_b", rid="rid-b", text="B")

    seen: list[str] = []

    async def _fake_trigger_extract(*, tenant_id: str, rid: str, ai_mode: str, idempotency_key: str):
        seen.append(f"{tenant_id}:{rid}")
        return 200, '{"ok":true}'

    monkeypatch.setattr(postcall_reconcile, "_trigger_extract", _fake_trigger_extract)
    client = TestClient(create_app())

    resp = client.post(
        "/admin/postcall/reconcile",
        json={"tenant_id": "tenant_a", "since_ts": 0, "limit": 50},
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert seen == ["tenant_a:rid-a"]


def test_postcall_reconcile_runtime_gate_off_returns_503(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "reconcile_gate.sqlite3"))
    monkeypatch.setenv("VOZ_POSTCALL_RECONCILE_ENABLED", "0")
    client = TestClient(create_app())

    resp = client.post(
        "/admin/postcall/reconcile",
        json={"tenant_id": "tenant_demo"},
        headers=_auth(),
    )
    assert resp.status_code == 503


def test_postcall_reconcile_dry_run_makes_no_writes(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "reconcile_dry.sqlite3"))
    _seed_call_stopped(tenant_id="tenant_demo", rid="rid-dry", ai_mode="owner")
    _seed_transcript(tenant_id="tenant_demo", rid="rid-dry", text="hello")

    async def _should_not_run(*, tenant_id: str, rid: str, ai_mode: str, idempotency_key: str):
        raise AssertionError("extract should not run in dry_run mode")

    monkeypatch.setattr(postcall_reconcile, "_trigger_extract", _should_not_run)
    client = TestClient(create_app())
    resp = client.post(
        "/admin/postcall/reconcile",
        json={"tenant_id": "tenant_demo", "dry_run": True},
        headers=_auth(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["attempted"] == 1
    assert body["created"] == 0
    assert body["dry_run"] is True
    assert query_events_for_rid("tenant_demo", "rid-dry", event_type="postcall.summary", limit=10) == []


def test_postcall_reconcile_limit_hard_cap_enforced(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "reconcile_limit.sqlite3"))
    client = TestClient(create_app())
    resp = client.post(
        "/admin/postcall/reconcile",
        json={"tenant_id": "tenant_demo", "limit": 201},
        headers=_auth(),
    )
    assert resp.status_code == 422


def test_postcall_reconcile_dedupes_same_rid(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "reconcile_dedupe.sqlite3"))
    _seed_call_stopped(tenant_id="tenant_demo", rid="rid-x", ai_mode="owner")
    emit_event(
        tenant_id="tenant_demo",
        rid="rid-x",
        event_type="flow_a.call_stopped",
        payload_dict={"tenant_id": "tenant_demo", "rid": "rid-x", "ai_mode": "owner", "reason": "cleanup"},
    )

    calls: list[str] = []

    async def _fake_trigger_extract(*, tenant_id: str, rid: str, ai_mode: str, idempotency_key: str):
        calls.append(rid)
        return 200, '{"ok":true}'

    monkeypatch.setattr(postcall_reconcile, "_trigger_extract", _fake_trigger_extract)
    client = TestClient(create_app())
    resp = client.post(
        "/admin/postcall/reconcile",
        json={"tenant_id": "tenant_demo", "since_ts": 0, "limit": 50},
        headers=_auth(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["attempted"] == 1
    assert body["skipped"] == 1
    assert calls == ["rid-x"]


def test_validated_self_base_url_rejects_untrusted_host(monkeypatch) -> None:
    monkeypatch.setenv("VOZ_SELF_BASE_URL", "https://evil.example.com")
    monkeypatch.delenv("VOZ_SELF_BASE_URL_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_HOSTNAME", raising=False)
    monkeypatch.delenv("RENDER_INTERNAL_HOSTNAME", raising=False)
    with pytest.raises(RuntimeError, match="host not allowed"):
        postcall_reconcile._validated_self_base_url()
