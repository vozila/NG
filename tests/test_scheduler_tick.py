from __future__ import annotations

from fastapi.testclient import TestClient

from core.app import create_app
from core.db import query_events


def _set_env(monkeypatch, db_path: str) -> None:
    monkeypatch.setenv("VOZ_DB_PATH", db_path)
    monkeypatch.setenv("VOZ_FEATURE_WIZARD_GOALS", "1")
    monkeypatch.setenv("VOZ_OWNER_GOALS_ENABLED", "1")
    monkeypatch.setenv("VOZ_OWNER_API_KEY", "owner-secret")
    monkeypatch.setenv("VOZ_FEATURE_SCHEDULER_TICK", "1")
    monkeypatch.setenv("VOZ_SCHEDULER_ENABLED", "1")
    monkeypatch.setenv("VOZ_ADMIN_API_KEY", "admin-secret")


def _owner_auth() -> dict[str, str]:
    return {"Authorization": "Bearer owner-secret"}


def _admin_auth() -> dict[str, str]:
    return {"Authorization": "Bearer admin-secret"}


def _seed_active_goal(client: TestClient, tenant: str) -> str:
    created = client.post(
        "/owner/goals",
        headers=_owner_auth(),
        json={"tenant_id": tenant, "goal": "Check callbacks", "cadence_minutes": 60, "channel": "email"},
    )
    assert created.status_code == 200
    goal_id = created.json()["goal_id"]
    approved = client.post(f"/owner/goals/{goal_id}/approve", headers=_owner_auth(), json={"tenant_id": tenant})
    assert approved.status_code == 200
    return goal_id


def test_scheduler_tick_requires_auth(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, str(tmp_path / "scheduler_auth.sqlite3"))
    client = TestClient(create_app())
    resp = client.post("/admin/scheduler/tick", json={"tenant_id": "tenant_demo"})
    assert resp.status_code == 401


def test_scheduler_tick_dry_and_non_dry_idempotent(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, str(tmp_path / "scheduler_tick.sqlite3"))
    tenant = "tenant_demo"
    client = TestClient(create_app())
    goal_id = _seed_active_goal(client, tenant)

    goals = client.get("/owner/goals", params={"tenant_id": tenant}, headers=_owner_auth())
    assert goals.status_code == 200
    next_run_ts = goals.json()["items"][0]["next_run_ts"]
    assert isinstance(next_run_ts, int)
    now_ts = next_run_ts + 1

    dry = client.post(
        "/admin/scheduler/tick",
        headers=_admin_auth(),
        json={"tenant_id": tenant, "dry_run": True, "now_ts": now_ts},
    )
    assert dry.status_code == 200
    assert dry.json()["due_count"] >= 1
    assert dry.json()["executed_count"] == 0

    first = client.post(
        "/admin/scheduler/tick",
        headers=_admin_auth(),
        json={"tenant_id": tenant, "dry_run": False, "now_ts": now_ts},
    )
    second = client.post(
        "/admin/scheduler/tick",
        headers=_admin_auth(),
        json={"tenant_id": tenant, "dry_run": False, "now_ts": now_ts},
    )
    assert first.status_code == 200
    assert second.status_code == 200

    executed_events = query_events(tenant, event_type="scheduler.goal_executed", limit=50)
    by_goal = [e for e in executed_events if e["rid"] == goal_id]
    assert len(by_goal) == 1

