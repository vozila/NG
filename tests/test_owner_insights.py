from __future__ import annotations

import time

from fastapi.testclient import TestClient

from core.app import create_app
from core.db import emit_event


def _set_env(monkeypatch, *, db_path: str) -> None:
    monkeypatch.setenv("VOZ_DB_PATH", db_path)
    monkeypatch.setenv("VOZ_FEATURE_OWNER_INSIGHTS", "1")
    monkeypatch.setenv("VOZ_OWNER_API_KEY", "owner-secret")


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer owner-secret"}


def test_owner_insights_requires_bearer(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "insights_auth.sqlite3"))
    client = TestClient(create_app())

    missing = client.get("/owner/insights/summary", params={"tenant_id": "tenant_demo"})
    assert missing.status_code == 401

    invalid = client.get(
        "/owner/insights/summary",
        params={"tenant_id": "tenant_demo"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert invalid.status_code == 401


def test_owner_insights_returns_expected_counts(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "insights_counts.sqlite3"))

    tenant = "tenant_demo"
    rid = "rid-1"
    emit_event(tenant, rid, "flow_a.call_started", {"tenant_id": tenant, "rid": rid})
    emit_event(tenant, rid, "flow_a.call_stopped", {"tenant_id": tenant, "rid": rid})
    emit_event(tenant, rid, "flow_a.transcript_completed", {"tenant_id": tenant, "rid": rid, "transcript": "hi"})
    emit_event(tenant, rid, "flow_a.transcript_completed", {"tenant_id": tenant, "rid": rid, "transcript": "again"})
    emit_event(tenant, rid, "postcall.summary", {"tenant_id": tenant, "rid": rid})
    emit_event(tenant, rid, "postcall.lead", {"tenant_id": tenant, "rid": rid, "qualified": True})
    emit_event(tenant, rid, "postcall.lead", {"tenant_id": tenant, "rid": rid, "qualified": False})
    emit_event(tenant, rid, "postcall.appt_request", {"tenant_id": tenant, "rid": rid, "requested": True})

    now = int(time.time())
    client = TestClient(create_app())
    resp = client.get(
        "/owner/insights/summary",
        params={"tenant_id": tenant, "since_ts": 0, "until_ts": now + 1000},
        headers=_auth(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["tenant_id"] == tenant
    counts = body["counts"]
    assert counts["call_started"] == 1
    assert counts["call_stopped"] == 1
    assert counts["transcript_completed"] == 2
    assert counts["postcall_summary"] == 1
    assert counts["leads_total"] == 2
    assert counts["leads_qualified"] == 1
    assert counts["appt_requests"] == 1
    assert body["latest"]["rid"] == rid


def test_owner_insights_tenant_isolation(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "insights_tenant.sqlite3"))

    emit_event("tenant_a", "rid-a", "flow_a.call_started", {"tenant_id": "tenant_a"})
    emit_event("tenant_b", "rid-b", "flow_a.call_started", {"tenant_id": "tenant_b"})
    emit_event("tenant_b", "rid-b", "postcall.lead", {"tenant_id": "tenant_b", "qualified": True})

    client = TestClient(create_app())
    resp = client.get(
        "/owner/insights/summary",
        params={"tenant_id": "tenant_a", "since_ts": 0, "until_ts": int(time.time()) + 1000},
        headers=_auth(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["counts"]["call_started"] == 1
    assert body["counts"]["leads_total"] == 0


def test_owner_insights_invalid_window_returns_400(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "insights_window.sqlite3"))
    client = TestClient(create_app())
    resp = client.get(
        "/owner/insights/summary",
        params={"tenant_id": "tenant_demo", "since_ts": 100, "until_ts": 10},
        headers=_auth(),
    )
    assert resp.status_code == 400


def test_owner_insights_default_window_is_bounded(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "insights_default_window.sqlite3"))
    client = TestClient(create_app())
    resp = client.get(
        "/owner/insights/summary",
        params={"tenant_id": "tenant_demo"},
        headers=_auth(),
    )
    assert resp.status_code == 200
    body = resp.json()
    window = body["window"]
    assert 0 <= (window["until_ts"] - window["since_ts"]) <= (24 * 60 * 60)
