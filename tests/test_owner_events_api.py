from __future__ import annotations

import os

from fastapi.testclient import TestClient

from core.app import create_app
from core.db import emit_event


def _set_owner_api_env(*, feature_flag: str, owner_api_key: str | None, db_path: str | None) -> dict[str, str | None]:
    keys = ("VOZ_FEATURE_OWNER_EVENTS_API", "VOZ_OWNER_API_KEY", "VOZ_DB_PATH")
    old: dict[str, str | None] = {k: os.getenv(k) for k in keys}

    os.environ["VOZ_FEATURE_OWNER_EVENTS_API"] = feature_flag
    if owner_api_key is None:
        os.environ.pop("VOZ_OWNER_API_KEY", None)
    else:
        os.environ["VOZ_OWNER_API_KEY"] = owner_api_key
    if db_path is None:
        os.environ.pop("VOZ_DB_PATH", None)
    else:
        os.environ["VOZ_DB_PATH"] = db_path
    return old


def _restore_env(old: dict[str, str | None]) -> None:
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_owner_events_unauthorized_missing_or_invalid_bearer(tmp_path) -> None:
    old = _set_owner_api_env(feature_flag="1", owner_api_key="secret123", db_path=str(tmp_path / "owner.sqlite3"))
    try:
        app = create_app()
        client = TestClient(app)

        missing = client.get("/owner/events", params={"tenant_id": "tenant_demo"})
        assert missing.status_code == 401

        invalid = client.get(
            "/owner/events",
            params={"tenant_id": "tenant_demo"},
            headers={"Authorization": "Bearer wrong"},
        )
        assert invalid.status_code == 401
    finally:
        _restore_env(old)


def test_owner_events_valid_bearer_returns_seeded_events(tmp_path) -> None:
    old = _set_owner_api_env(feature_flag="1", owner_api_key="secret123", db_path=str(tmp_path / "owner.sqlite3"))
    try:
        emit_event(
            tenant_id="tenant_demo",
            rid="rid-1",
            event_type="flow_a.call_started",
            payload_dict={
                "tenant_id": "tenant_demo",
                "rid": "rid-1",
                "ai_mode": "owner",
                "tenant_mode": "shared",
            },
        )
        emit_event(
            tenant_id="tenant_demo",
            rid="rid-1",
            event_type="flow_a.transcript_completed",
            payload_dict={
                "tenant_id": "tenant_demo",
                "rid": "rid-1",
                "ai_mode": "owner",
                "tenant_mode": "shared",
                "turn": 1,
                "transcript_len": 42,
            },
        )

        app = create_app()
        client = TestClient(app)
        resp = client.get(
            "/owner/events",
            params={"tenant_id": "tenant_demo", "event_type": "flow_a.transcript_completed", "limit": 50},
            headers={"Authorization": "Bearer secret123"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert isinstance(body["events"], list)
        assert len(body["events"]) == 1

        evt = body["events"][0]
        assert evt["tenant_id"] == "tenant_demo"
        assert evt["rid"] == "rid-1"
        assert evt["event_type"] == "flow_a.transcript_completed"
        assert evt["payload"]["tenant_id"] == "tenant_demo"
        assert evt["payload"]["rid"] == "rid-1"
    finally:
        _restore_env(old)
