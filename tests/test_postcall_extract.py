from __future__ import annotations

from fastapi.testclient import TestClient

from core.app import create_app
from core.db import emit_event, query_events
from features import postcall_extract


def _seed_transcript(*, tenant_id: str, rid: str, text: str) -> None:
    emit_event(
        tenant_id=tenant_id,
        rid=rid,
        event_type="flow_a.transcript_completed",
        payload_dict={"tenant_id": tenant_id, "rid": rid, "transcript": text},
    )


def _set_env(monkeypatch, *, db_path: str) -> None:
    monkeypatch.setenv("VOZ_DB_PATH", db_path)
    monkeypatch.setenv("VOZ_FEATURE_POSTCALL_EXTRACT", "1")
    monkeypatch.setenv("VOZ_POSTCALL_EXTRACT_ENABLED", "1")
    monkeypatch.setenv("VOZ_ADMIN_API_KEY", "admin-secret")


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer admin-secret"}


def test_postcall_extract_schema_validation_failure_writes_failed_event(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "postcall_schema.sqlite3"))
    _seed_transcript(tenant_id="tenant_a", rid="rid-1", text="Please schedule for tomorrow.")

    def _invalid_proposal(*, transcript: str, ai_mode: str):
        return {
            "summary": {"headline": 123, "bullet_points": ["ok"], "sentiment": "neutral"},
            "lead": {"qualified": False, "score": 50, "stage": "warm", "reasons": ["x"]},
            "appt_request": {"requested": False, "channel": "phone", "preferred_window": None, "confidence": 0.3},
        }

    monkeypatch.setattr(postcall_extract, "_llm_propose_json", _invalid_proposal)
    client = TestClient(create_app())

    resp = client.post(
        "/admin/postcall/extract",
        json={"tenant_id": "tenant_a", "rid": "rid-1", "ai_mode": "customer", "idempotency_key": "idem-1"},
        headers=_auth(),
    )
    assert resp.status_code == 422

    failed = query_events("tenant_a", event_type="postcall.extract_failed", limit=10)
    assert len(failed) == 1
    assert failed[0]["rid"] == "rid-1"
    assert "schema_invalid" in failed[0]["payload"]["reason"]
    assert query_events("tenant_a", event_type="postcall.summary", limit=10) == []
    assert query_events("tenant_a", event_type="postcall.lead", limit=10) == []


def test_postcall_extract_idempotency_prevents_duplicate_output_events(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "postcall_idempotency.sqlite3"))
    _seed_transcript(
        tenant_id="tenant_a",
        rid="rid-2",
        text="I am ready to buy. Can we schedule a meeting next week?",
    )

    def _valid_proposal(*, transcript: str, ai_mode: str):
        return {
            "summary": {"headline": "Call summary", "bullet_points": ["bp1"], "sentiment": "positive"},
            "lead": {"qualified": True, "score": 90, "stage": "hot", "reasons": ["clear intent"]},
            "appt_request": {
                "requested": True,
                "channel": "phone",
                "preferred_window": "next week",
                "confidence": 0.95,
            },
        }

    monkeypatch.setattr(postcall_extract, "_llm_propose_json", _valid_proposal)
    client = TestClient(create_app())
    body = {"tenant_id": "tenant_a", "rid": "rid-2", "ai_mode": "customer", "idempotency_key": "idem-2"}

    first = client.post("/admin/postcall/extract", json=body, headers=_auth())
    second = client.post("/admin/postcall/extract", json=body, headers=_auth())

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(query_events("tenant_a", event_type="postcall.summary", limit=10)) == 1
    assert len(query_events("tenant_a", event_type="postcall.lead", limit=10)) == 1
    assert len(query_events("tenant_a", event_type="postcall.appt_request", limit=10)) == 1


def test_postcall_extract_owner_mode_emits_summary_only(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "postcall_owner_mode.sqlite3"))
    _seed_transcript(
        tenant_id="tenant_a",
        rid="rid-owner-1",
        text="Show me insights and call trends for this week.",
    )

    def _owner_proposal(*, transcript: str, ai_mode: str):
        return {
            "summary": {"headline": "Owner analytics call", "bullet_points": ["bp1"], "sentiment": "neutral"},
            "lead": {"qualified": True, "score": 95, "stage": "hot", "reasons": ["contains intent words"]},
            "appt_request": {
                "requested": True,
                "channel": "phone",
                "preferred_window": "tomorrow",
                "confidence": 0.95,
            },
        }

    monkeypatch.setattr(postcall_extract, "_llm_propose_json", _owner_proposal)
    client = TestClient(create_app())
    body = {"tenant_id": "tenant_a", "rid": "rid-owner-1", "ai_mode": "owner", "idempotency_key": "idem-owner"}
    resp = client.post("/admin/postcall/extract", json=body, headers=_auth())
    assert resp.status_code == 200
    out = resp.json()
    assert out["ok"] is True
    assert "summary" in out["events"]
    assert "lead" not in out["events"]
    assert "appt_request" not in out["events"]

    assert len(query_events("tenant_a", event_type="postcall.summary", limit=10)) == 1
    assert len(query_events("tenant_a", event_type="postcall.lead", limit=10)) == 0
    assert len(query_events("tenant_a", event_type="postcall.appt_request", limit=10)) == 0


def test_postcall_extract_enforces_tenant_isolation(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "postcall_tenant.sqlite3"))
    _seed_transcript(tenant_id="tenant_a", rid="rid-shared", text="tenant A transcript")
    _seed_transcript(tenant_id="tenant_b", rid="rid-shared", text="tenant B transcript")

    def _tenant_checked_proposal(*, transcript: str, ai_mode: str):
        assert "tenant B transcript" not in transcript
        assert "tenant A transcript" in transcript
        return {
            "summary": {"headline": "Tenant A only", "bullet_points": ["bp1"], "sentiment": "neutral"},
            "lead": {"qualified": False, "score": 20, "stage": "cold", "reasons": ["no buying signal"]},
            "appt_request": {"requested": False, "channel": "unknown", "preferred_window": None, "confidence": 0.2},
        }

    monkeypatch.setattr(postcall_extract, "_llm_propose_json", _tenant_checked_proposal)
    client = TestClient(create_app())

    resp = client.post(
        "/admin/postcall/extract",
        json={
            "tenant_id": "tenant_a",
            "rid": "rid-shared",
            "ai_mode": "customer",
            "idempotency_key": "idem-tenant",
        },
        headers=_auth(),
    )
    assert resp.status_code == 200

    a_summary = query_events("tenant_a", event_type="postcall.summary", limit=10)
    b_summary = query_events("tenant_b", event_type="postcall.summary", limit=10)
    assert len(a_summary) == 1
    assert b_summary == []


def test_llm_propose_json_uses_model_when_available(monkeypatch) -> None:
    monkeypatch.setenv("VOZ_POSTCALL_EXTRACT_MODEL_ENABLED", "1")

    def _model(*, transcript: str, ai_mode: str):
        return {
            "summary": {"headline": "model path", "bullet_points": ["m"], "sentiment": "neutral"},
            "lead": {"qualified": True, "score": 88, "stage": "hot", "reasons": ["model"]},
            "appt_request": {"requested": False, "channel": "unknown", "preferred_window": None, "confidence": 0.4},
        }

    monkeypatch.setattr(postcall_extract, "_model_propose_json", _model)
    out = postcall_extract._llm_propose_json(transcript="hello", ai_mode="owner")
    assert out["summary"]["headline"] == "model path"
    assert out["lead"]["score"] == 88


def test_llm_propose_json_falls_back_to_heuristic_on_model_failure(monkeypatch) -> None:
    monkeypatch.setenv("VOZ_POSTCALL_EXTRACT_MODEL_ENABLED", "1")

    def _boom(*, transcript: str, ai_mode: str):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(postcall_extract, "_model_propose_json", _boom)
    out = postcall_extract._llm_propose_json(
        transcript="Please schedule an appointment tomorrow",
        ai_mode="customer",
    )
    assert out["appt_request"]["requested"] is True


def test_postcall_extract_v2_fields_persist(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, db_path=str(tmp_path / "postcall_v2.sqlite3"))
    _seed_transcript(tenant_id="tenant_a", rid="rid-v2", text="Customer asked to talk to owner and call back tomorrow.")

    def _v2_proposal(*, transcript: str, ai_mode: str):
        return {
            "summary": {
                "headline": "Needs owner callback",
                "bullet_points": ["bp1"],
                "sentiment": "neutral",
                "urgency": "high",
                "action_items": ["owner callback today"],
            },
            "lead": {
                "qualified": True,
                "score": 91,
                "stage": "hot",
                "reasons": ["explicit owner request"],
                "callback_requested": True,
                "talk_to_owner": True,
                "preferred_contact": "phone",
            },
            "appt_request": {
                "requested": True,
                "channel": "phone",
                "preferred_window": "tomorrow",
                "confidence": 0.92,
            },
        }

    monkeypatch.setattr(postcall_extract, "_llm_propose_json", _v2_proposal)
    client = TestClient(create_app())
    resp = client.post(
        "/admin/postcall/extract",
        json={"tenant_id": "tenant_a", "rid": "rid-v2", "ai_mode": "customer", "idempotency_key": "idem-v2"},
        headers=_auth(),
    )
    assert resp.status_code == 200

    summary = query_events("tenant_a", event_type="postcall.summary", limit=10)[0]["payload"]
    lead = query_events("tenant_a", event_type="postcall.lead", limit=10)[0]["payload"]
    assert summary["urgency"] == "high"
    assert summary["action_items"] == ["owner callback today"]
    assert lead["callback_requested"] is True
    assert lead["talk_to_owner"] is True
    assert lead["preferred_contact"] == "phone"
