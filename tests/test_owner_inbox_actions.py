from __future__ import annotations

from fastapi.testclient import TestClient

from core.app import create_app


def _set_env(monkeypatch, *, db_path: str) -> None:
    monkeypatch.setenv("VOZ_DB_PATH", db_path)
    monkeypatch.setenv("VOZ_FEATURE_OWNER_INBOX_ACTIONS", "1")
    monkeypatch.setenv("VOZ_OWNER_INBOX_ENABLED", "1")
    monkeypatch.setenv("VOZ_OWNER_API_KEY", "owner-secret")


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer owner-secret"}


def test_owner_inbox_actions_requires_auth(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "owner_actions_auth.sqlite3"))
    client = TestClient(create_app())
    resp = client.post(
        "/owner/inbox/actions/qualify",
        json={"tenant_id": "tenant_demo", "rid": "rid-1", "qualified": True},
    )
    assert resp.status_code == 401


def test_owner_inbox_actions_qualify_and_handled_state(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "owner_actions_state.sqlite3"))
    tenant = "tenant_demo"
    rid = "rid-1"
    client = TestClient(create_app())

    q = client.post(
        "/owner/inbox/actions/qualify",
        headers=_auth(),
        json={"tenant_id": tenant, "rid": rid, "qualified": True, "reason": "budget approved"},
    )
    assert q.status_code == 200

    h = client.post(
        "/owner/inbox/actions/handled",
        headers=_auth(),
        json={"tenant_id": tenant, "rid": rid, "handled": True, "channel": "phone", "note": "called back"},
    )
    assert h.status_code == 200

    state = client.get(
        "/owner/inbox/actions/state",
        headers=_auth(),
        params={"tenant_id": tenant, "rid": rid},
    )
    assert state.status_code == 200
    body = state.json()["state"]
    assert body["qualified"] is True
    assert body["qualified_reason"] == "budget approved"
    assert body["handled"] is True
    assert body["handled_channel"] == "phone"
    assert body["handled_note"] == "called back"

