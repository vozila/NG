from __future__ import annotations

import time

from fastapi.testclient import TestClient

from core.app import create_app
from core.db import emit_event, query_events, query_events_for_rid


def _set_env(monkeypatch, *, db_path: str) -> None:
    monkeypatch.setenv("VOZ_DB_PATH", db_path)
    monkeypatch.setenv("VOZ_FEATURE_POSTCALL_NOTIFY_SMS", "1")
    monkeypatch.setenv("VOZ_POSTCALL_NOTIFY_SMS_ENABLED", "1")
    monkeypatch.setenv("VOZ_ADMIN_API_KEY", "admin-secret")
    monkeypatch.setenv("VOZ_TENANT_OWNER_NOTIFY_JSON", '{"tenant_demo":{"sms":"+15180009999"}}')
    monkeypatch.setenv("VOZ_TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("VOZ_TWILIO_AUTH_TOKEN", "token123")
    monkeypatch.setenv("VOZ_TWILIO_SMS_FROM", "+15180000000")


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer admin-secret"}


def test_postcall_notify_sms_requires_admin_auth(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "notify_auth.sqlite3"))
    client = TestClient(create_app())
    resp = client.post("/admin/postcall/notify/sms", json={"tenant_id": "tenant_demo", "since_ts": 0})
    assert resp.status_code == 401


def test_postcall_notify_sms_gates_off_returns_503(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "notify_gate.sqlite3"))
    monkeypatch.setenv("VOZ_POSTCALL_NOTIFY_SMS_ENABLED", "0")
    client = TestClient(create_app())
    resp = client.post(
        "/admin/postcall/notify/sms",
        headers=_auth(),
        json={"tenant_id": "tenant_demo", "since_ts": 0},
    )
    assert resp.status_code == 503


def test_postcall_notify_sms_dry_run_writes_nothing(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "notify_dry.sqlite3"))
    tenant = "tenant_demo"
    rid = "rid-dry"
    emit_event(tenant, rid, "postcall.lead", {"tenant_id": tenant, "rid": rid, "qualified": True})
    emit_event(tenant, rid, "postcall.summary", {"tenant_id": tenant, "rid": rid, "headline": "Summary headline"})
    emit_event(
        tenant,
        rid,
        "flow_a.call_started",
        {"tenant_id": tenant, "rid": rid, "from_number": "+15181112222", "to_number": "+15183334444"},
    )

    client = TestClient(create_app())
    resp = client.post(
        "/admin/postcall/notify/sms",
        headers=_auth(),
        json={"tenant_id": tenant, "since_ts": 0, "limit": 50, "dry_run": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["dry_run"] is True
    assert body["planned_count"] == 1
    assert body["sent"] == 0
    assert len(query_events(tenant, event_type="notify.sms_sent", limit=20)) == 0
    assert len(query_events(tenant, event_type="notify.sms_failed", limit=20)) == 0


def test_postcall_notify_sms_non_dry_emits_sms_sent_and_idempotent(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "notify_idem.sqlite3"))
    tenant = "tenant_demo"
    rid = "rid-live"
    emit_event(tenant, rid, "postcall.appt_request", {"tenant_id": tenant, "rid": rid, "requested": True})
    emit_event(tenant, rid, "postcall.summary", {"tenant_id": tenant, "rid": rid, "headline": "Book call"})

    from features import postcall_notify_sms

    sends: list[tuple[str, str]] = []

    def _fake_send_sms(*, to_number: str, body: str):
        sends.append((to_number, body))
        return True, '{"sid":"SM123"}'

    monkeypatch.setattr(postcall_notify_sms, "_send_sms", _fake_send_sms)
    client = TestClient(create_app())

    first = client.post(
        "/admin/postcall/notify/sms",
        headers=_auth(),
        json={"tenant_id": tenant, "since_ts": 0, "limit": 50, "dry_run": False},
    )
    second = client.post(
        "/admin/postcall/notify/sms",
        headers=_auth(),
        json={"tenant_id": tenant, "since_ts": 0, "limit": 50, "dry_run": False},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(sends) == 1
    sent_events = query_events_for_rid(tenant, rid, event_type="notify.sms_sent", limit=10)
    assert len(sent_events) == 1


def test_postcall_notify_sms_tenant_isolation(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "notify_tenant.sqlite3"))
    emit_event("tenant_demo", "rid-a", "postcall.lead", {"tenant_id": "tenant_demo", "rid": "rid-a"})
    emit_event("tenant_other", "rid-b", "postcall.lead", {"tenant_id": "tenant_other", "rid": "rid-b"})

    client = TestClient(create_app())
    resp = client.post(
        "/admin/postcall/notify/sms",
        headers=_auth(),
        json={"tenant_id": "tenant_demo", "since_ts": 0, "limit": 50, "dry_run": True},
    )
    assert resp.status_code == 200
    planned = resp.json()["planned"]
    assert len(planned) == 1
    assert planned[0]["rid"] == "rid-a"


def test_postcall_notify_sms_limit_cap_enforced(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "notify_limit.sqlite3"))
    client = TestClient(create_app())
    resp = client.post(
        "/admin/postcall/notify/sms",
        headers=_auth(),
        json={"tenant_id": "tenant_demo", "since_ts": int(time.time()) - 60, "limit": 201},
    )
    assert resp.status_code == 422
