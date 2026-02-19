from __future__ import annotations

import time

from fastapi.testclient import TestClient

from core.app import create_app
from core.db import emit_event


def _set_env(monkeypatch, *, db_path: str) -> None:
    monkeypatch.setenv("VOZ_DB_PATH", db_path)
    monkeypatch.setenv("VOZ_FEATURE_OWNER_ANALYTICS_QUERY", "1")
    monkeypatch.setenv("VOZ_OWNER_ANALYTICS_QUERY_ENABLED", "1")
    monkeypatch.setenv("VOZ_OWNER_API_KEY", "owner-secret")


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer owner-secret"}


def test_owner_analytics_query_counts_and_totals(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "analytics_query_counts.sqlite3"))
    tenant = "tenant_demo"
    rid = "rid-1"
    emit_event(tenant, rid, "flow_a.call_started", {"tenant_id": tenant, "rid": rid, "ai_mode": "customer"})
    emit_event(tenant, rid, "flow_a.transcript_completed", {"tenant_id": tenant, "rid": rid, "ai_mode": "customer"})
    emit_event(tenant, rid, "postcall.lead", {"tenant_id": tenant, "rid": rid, "ai_mode": "customer"})
    emit_event(tenant, rid, "postcall.appt_request", {"tenant_id": tenant, "rid": rid, "ai_mode": "customer"})

    now = int(time.time())
    client = TestClient(create_app())
    resp = client.post(
        "/owner/analytics/query",
        headers=_auth(),
        json={
            "tenant_id": tenant,
            "since_ts": now - 1000,
            "until_ts": now + 1000,
            "query": {
                "metrics": ["count_calls", "count_leads", "count_appt_requests", "count_transcripts"],
                "dimensions": [],
                "filters": {},
                "limit": 50,
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["totals"]["count_calls"] == 1
    assert body["totals"]["count_leads"] == 1
    assert body["totals"]["count_appt_requests"] == 1
    assert body["totals"]["count_transcripts"] == 1


def test_owner_analytics_query_tenant_isolation(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "analytics_query_tenant.sqlite3"))
    emit_event("tenant_a", "r1", "flow_a.call_started", {"tenant_id": "tenant_a"})
    emit_event("tenant_b", "r2", "flow_a.call_started", {"tenant_id": "tenant_b"})
    emit_event("tenant_b", "r2", "postcall.lead", {"tenant_id": "tenant_b"})

    now = int(time.time())
    client = TestClient(create_app())
    resp = client.post(
        "/owner/analytics/query",
        headers=_auth(),
        json={
            "tenant_id": "tenant_a",
            "since_ts": now - 1000,
            "until_ts": now + 1000,
            "query": {"metrics": ["count_calls", "count_leads"], "dimensions": [], "filters": {}, "limit": 10},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"]["count_calls"] == 1
    assert body["totals"]["count_leads"] == 0


def test_owner_analytics_query_limit_cap_enforced(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "analytics_query_limit.sqlite3"))
    client = TestClient(create_app())
    resp = client.post(
        "/owner/analytics/query",
        headers=_auth(),
        json={
            "tenant_id": "tenant_demo",
            "query": {"metrics": ["count_calls"], "dimensions": [], "filters": {}, "limit": 201},
        },
    )
    assert resp.status_code == 422


def test_owner_analytics_query_window_too_wide_returns_400(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "analytics_query_window.sqlite3"))
    client = TestClient(create_app())
    resp = client.post(
        "/owner/analytics/query",
        headers=_auth(),
        json={
            "tenant_id": "tenant_demo",
            "since_ts": 0,
            "until_ts": (8 * 24 * 60 * 60),
            "query": {"metrics": ["count_calls"], "dimensions": [], "filters": {}, "limit": 10},
        },
    )
    assert resp.status_code == 400


def test_owner_analytics_query_invalid_metric_or_dimension_returns_422(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "analytics_query_invalid.sqlite3"))
    client = TestClient(create_app())
    bad_metric = client.post(
        "/owner/analytics/query",
        headers=_auth(),
        json={
            "tenant_id": "tenant_demo",
            "query": {"metrics": ["count_unknown"], "dimensions": [], "filters": {}, "limit": 10},
        },
    )
    assert bad_metric.status_code == 422

    bad_dimension = client.post(
        "/owner/analytics/query",
        headers=_auth(),
        json={
            "tenant_id": "tenant_demo",
            "query": {"metrics": ["count_calls"], "dimensions": ["bad_dim"], "filters": {}, "limit": 10},
        },
    )
    assert bad_dimension.status_code == 422
