from __future__ import annotations

import time

from fastapi.testclient import TestClient

from core.app import create_app
from core.db import emit_event, query_events, query_events_for_rid


def _set_env(monkeypatch, *, db_path: str) -> None:
    monkeypatch.setenv("VOZ_DB_PATH", db_path)
    monkeypatch.setenv("VOZ_FEATURE_POSTCALL_NOTIFY_EMAIL", "1")
    monkeypatch.setenv("VOZ_POSTCALL_NOTIFY_EMAIL_ENABLED", "1")
    monkeypatch.setenv("VOZ_ADMIN_API_KEY", "admin-secret")
    monkeypatch.setenv("VOZ_NOTIFY_EMAIL_WEBHOOK_URL", "https://example.test/webhook")
    monkeypatch.setenv("VOZ_TENANT_OWNER_NOTIFY_JSON", '{"tenant_demo":{"email":"owner@example.com"}}')


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer admin-secret"}


def test_postcall_notify_email_requires_admin_auth(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "notify_email_auth.sqlite3"))
    client = TestClient(create_app())
    resp = client.post("/admin/postcall/notify/email", json={"tenant_id": "tenant_demo", "since_ts": 0})
    assert resp.status_code == 401


def test_postcall_notify_email_dry_run_writes_nothing(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "notify_email_dry.sqlite3"))
    tenant = "tenant_demo"
    rid = "rid-email-dry"
    emit_event(tenant, rid, "postcall.lead", {"tenant_id": tenant, "rid": rid, "qualified": True})
    emit_event(tenant, rid, "postcall.summary", {"tenant_id": tenant, "rid": rid, "headline": "Summary headline"})
    client = TestClient(create_app())
    resp = client.post(
        "/admin/postcall/notify/email",
        headers=_auth(),
        json={"tenant_id": tenant, "since_ts": 0, "limit": 50, "dry_run": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["planned_count"] == 1
    assert body["sent"] == 0
    assert query_events(tenant, event_type="notify.email_sent", limit=20) == []


def test_postcall_notify_email_non_dry_idempotent(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "notify_email_idem.sqlite3"))
    tenant = "tenant_demo"
    rid = "rid-email-live"
    emit_event(tenant, rid, "postcall.appt_request", {"tenant_id": tenant, "rid": rid, "requested": True})

    from features import postcall_notify_email

    sends: list[tuple[str, str, str]] = []

    def _fake_send(*, to_email: str, subject: str, body: str):
        sends.append((to_email, subject, body))
        return True, '{"ok":true}'

    monkeypatch.setattr(postcall_notify_email, "_send_email", _fake_send)
    client = TestClient(create_app())
    first = client.post(
        "/admin/postcall/notify/email",
        headers=_auth(),
        json={"tenant_id": tenant, "since_ts": 0, "limit": 50, "dry_run": False},
    )
    second = client.post(
        "/admin/postcall/notify/email",
        headers=_auth(),
        json={"tenant_id": tenant, "since_ts": 0, "limit": 50, "dry_run": False},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert len(sends) == 1
    assert len(query_events_for_rid(tenant, rid, event_type="notify.email_sent", limit=10)) == 1


def test_postcall_notify_email_limit_cap(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "notify_email_limit.sqlite3"))
    client = TestClient(create_app())
    resp = client.post(
        "/admin/postcall/notify/email",
        headers=_auth(),
        json={"tenant_id": "tenant_demo", "since_ts": int(time.time()) - 60, "limit": 201},
    )
    assert resp.status_code == 422

