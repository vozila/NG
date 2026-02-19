from __future__ import annotations

import time

from fastapi.testclient import TestClient

from core.app import create_app
from core.db import emit_event


def _set_env(monkeypatch, *, db_path: str) -> None:
    monkeypatch.setenv("VOZ_DB_PATH", db_path)
    monkeypatch.setenv("VOZ_FEATURE_OWNER_INBOX", "1")
    monkeypatch.setenv("VOZ_OWNER_INBOX_ENABLED", "1")
    monkeypatch.setenv("VOZ_OWNER_API_KEY", "owner-secret")


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer owner-secret"}


def test_owner_inbox_requires_auth(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "owner_inbox_auth.sqlite3"))
    client = TestClient(create_app())
    resp = client.get("/owner/inbox/leads", params={"tenant_id": "tenant_demo"})
    assert resp.status_code == 401


def test_owner_inbox_tenant_isolation(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "owner_inbox_tenant.sqlite3"))
    emit_event("tenant_a", "rid-a", "postcall.lead", {"tenant_id": "tenant_a", "qualified": True})
    emit_event("tenant_b", "rid-b", "postcall.lead", {"tenant_id": "tenant_b", "qualified": True})

    now = int(time.time())
    client = TestClient(create_app())
    resp = client.get(
        "/owner/inbox/leads",
        params={"tenant_id": "tenant_a", "since_ts": now - 3600, "until_ts": now + 60},
        headers=_auth(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["rid"] == "rid-a"


def test_owner_inbox_limit_cap_and_window_checks(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "owner_inbox_limits.sqlite3"))
    client = TestClient(create_app())

    too_big = client.get(
        "/owner/inbox/leads",
        params={"tenant_id": "tenant_demo", "limit": 201},
        headers=_auth(),
    )
    assert too_big.status_code == 422

    bad_window = client.get(
        "/owner/inbox/leads",
        params={"tenant_id": "tenant_demo", "since_ts": 0, "until_ts": 8 * 24 * 60 * 60},
        headers=_auth(),
    )
    assert bad_window.status_code == 400


def test_owner_inbox_leads_normalization_and_best_effort_caller_meta(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "owner_inbox_normalize.sqlite3"))
    tenant = "tenant_demo"
    rid_with_meta = "rid-meta"
    rid_no_meta = "rid-no-meta"

    emit_event(
        tenant,
        rid_with_meta,
        "postcall.summary",
        {"tenant_id": tenant, "rid": rid_with_meta, "headline": "Lead summary headline"},
    )
    emit_event(
        tenant,
        rid_with_meta,
        "flow_a.call_started",
        {"tenant_id": tenant, "rid": rid_with_meta, "from_number": "+15180001111", "to_number": "+15180002222"},
    )
    emit_event(
        tenant,
        rid_with_meta,
        "postcall.lead",
        {"tenant_id": tenant, "rid": rid_with_meta, "qualified": True, "score": 88, "stage": "hot"},
    )

    emit_event(
        tenant,
        rid_no_meta,
        "postcall.lead",
        {"tenant_id": tenant, "rid": rid_no_meta, "qualified": False, "score": 20, "stage": "cold"},
    )

    now = int(time.time())
    client = TestClient(create_app())
    resp = client.get(
        "/owner/inbox/leads",
        params={"tenant_id": tenant, "since_ts": now - 3600, "until_ts": now + 60, "limit": 50},
        headers=_auth(),
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2

    by_rid = {item["rid"]: item for item in items}
    with_meta = by_rid[rid_with_meta]
    assert with_meta["summary_headline"] == "Lead summary headline"
    assert with_meta["from_number"] == "+15180001111"
    assert with_meta["to_number"] == "+15180002222"

    without_meta = by_rid[rid_no_meta]
    assert without_meta["summary_headline"] is None
    assert without_meta["from_number"] is None
    assert without_meta["to_number"] is None


def test_owner_inbox_appt_requests_endpoint(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "owner_inbox_appt.sqlite3"))
    tenant = "tenant_demo"
    rid = "rid-appt"
    emit_event(
        tenant,
        rid,
        "postcall.appt_request",
        {"tenant_id": tenant, "rid": rid, "requested": True, "channel": "phone", "confidence": 0.9},
    )

    now = int(time.time())
    client = TestClient(create_app())
    resp = client.get(
        "/owner/inbox/appt_requests",
        params={"tenant_id": tenant, "since_ts": now - 3600, "until_ts": now + 60, "limit": 50},
        headers=_auth(),
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["rid"] == rid
