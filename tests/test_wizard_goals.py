from __future__ import annotations

from fastapi.testclient import TestClient

from core.app import create_app


def _set_env(monkeypatch, db_path: str) -> None:
    monkeypatch.setenv("VOZ_DB_PATH", db_path)
    monkeypatch.setenv("VOZ_FEATURE_WIZARD_GOALS", "1")
    monkeypatch.setenv("VOZ_OWNER_GOALS_ENABLED", "1")
    monkeypatch.setenv("VOZ_OWNER_API_KEY", "owner-secret")


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer owner-secret"}


def test_wizard_goals_requires_auth(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, str(tmp_path / "wizard_goals_auth.sqlite3"))
    client = TestClient(create_app())
    resp = client.get("/owner/goals", params={"tenant_id": "tenant_demo"})
    assert resp.status_code == 401


def test_wizard_goals_lifecycle(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, str(tmp_path / "wizard_goals_lifecycle.sqlite3"))
    tenant = "tenant_demo"
    client = TestClient(create_app())

    created = client.post(
        "/owner/goals",
        headers=_auth(),
        json={"tenant_id": tenant, "goal": "Call leads daily", "cadence_minutes": 60, "channel": "email"},
    )
    assert created.status_code == 200
    goal_id = created.json()["goal_id"]

    approved = client.post(f"/owner/goals/{goal_id}/approve", headers=_auth(), json={"tenant_id": tenant})
    assert approved.status_code == 200

    paused = client.post(f"/owner/goals/{goal_id}/pause", headers=_auth(), json={"tenant_id": tenant})
    assert paused.status_code == 200

    resumed = client.post(f"/owner/goals/{goal_id}/resume", headers=_auth(), json={"tenant_id": tenant})
    assert resumed.status_code == 200

    updated = client.patch(
        f"/owner/goals/{goal_id}",
        headers=_auth(),
        json={"tenant_id": tenant, "cadence_minutes": 120, "policy": "only weekdays"},
    )
    assert updated.status_code == 200

    listing = client.get("/owner/goals", params={"tenant_id": tenant}, headers=_auth())
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["goal_id"] == goal_id
    assert item["status"] == "active"
    assert item["cadence_minutes"] == 120
    assert item["policy"] == "only weekdays"

