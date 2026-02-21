from __future__ import annotations

from fastapi.testclient import TestClient

from core.app import create_app


def _set_env(monkeypatch, db_path: str) -> None:
    monkeypatch.setenv("VOZ_DB_PATH", db_path)
    monkeypatch.setenv("VOZ_FEATURE_PLAYBOOKS", "1")
    monkeypatch.setenv("VOZ_OWNER_PLAYBOOKS_ENABLED", "1")
    monkeypatch.setenv("VOZ_OWNER_API_KEY", "owner-secret")


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer owner-secret"}


def test_playbooks_requires_auth(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, str(tmp_path / "playbooks_auth.sqlite3"))
    client = TestClient(create_app())
    resp = client.post(
        "/owner/playbooks/wizard/draft",
        json={
            "tenant_id": "tenant_demo",
            "goal_id": "goal-1",
            "messages": [{"role": "user", "text": "Do this daily"}],
        },
    )
    assert resp.status_code == 401


def test_playbook_draft_and_read(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, str(tmp_path / "playbooks_read.sqlite3"))
    tenant = "tenant_demo"
    client = TestClient(create_app())

    draft = client.post(
        "/owner/playbooks/wizard/draft",
        headers=_auth(),
        json={
            "tenant_id": tenant,
            "goal_id": "goal-1",
            "messages": [
                {"role": "user", "text": "Call hot leads daily"},
                {"role": "assistant", "text": "Got it, will draft a playbook"},
            ],
            "schedule_hint_minutes": 180,
        },
    )
    assert draft.status_code == 200
    playbook_id = draft.json()["playbook_id"]

    got = client.get(f"/owner/playbooks/{playbook_id}", params={"tenant_id": tenant}, headers=_auth())
    assert got.status_code == 200
    pb = got.json()["playbook"]
    assert pb["playbook_id"] == playbook_id
    assert pb["goal_id"] == "goal-1"
    assert pb["schema_version"] == "v1"
    assert pb["schedule_hint_minutes"] == 180


def test_playbook_schema_validation(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, str(tmp_path / "playbooks_schema.sqlite3"))
    client = TestClient(create_app())
    bad = client.post(
        "/owner/playbooks/wizard/draft",
        headers=_auth(),
        json={
            "tenant_id": "tenant_demo",
            "goal_id": "goal-1",
            "messages": [{"role": "other", "text": "nope"}],
        },
    )
    assert bad.status_code == 422

