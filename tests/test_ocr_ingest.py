from __future__ import annotations

from fastapi.testclient import TestClient

from core.app import create_app


def _set_env(monkeypatch, db_path: str) -> None:
    monkeypatch.setenv("VOZ_DB_PATH", db_path)
    monkeypatch.setenv("VOZ_FEATURE_OCR_INGEST", "1")
    monkeypatch.setenv("VOZ_OWNER_OCR_INGEST_ENABLED", "1")
    monkeypatch.setenv("VOZ_OWNER_API_KEY", "owner-secret")


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer owner-secret"}


def test_ocr_ingest_requires_auth(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, str(tmp_path / "ocr_ingest_auth.sqlite3"))
    client = TestClient(create_app())
    resp = client.post(
        "/owner/ocr/ingest",
        json={"tenant_id": "tenant_demo", "source_name": "doc.png", "raw_text": "name: Jane"},
    )
    assert resp.status_code == 401


def test_ocr_ingest_pending_review_flow(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, str(tmp_path / "ocr_ingest_flow.sqlite3"))
    tenant = "tenant_demo"
    client = TestClient(create_app())

    ingest = client.post(
        "/owner/ocr/ingest",
        headers=_auth(),
        json={
            "tenant_id": tenant,
            "source_name": "insurance_card.png",
            "raw_text": "member id: A1234\ngroup: G1",
        },
    )
    assert ingest.status_code == 200
    record = ingest.json()["record"]
    review_id = record["review_id"]
    assert record["status"] == "pending_review"
    assert record["schema_version"] == "v1"
    assert record["proposed_fields"]["member_id"] == "A1234"

    queue = client.get(
        "/owner/ocr/reviews",
        params={"tenant_id": tenant},
        headers=_auth(),
    )
    assert queue.status_code == 200
    items = queue.json()["items"]
    assert any(item["review_id"] == review_id for item in items)

    decide = client.post(
        f"/owner/ocr/reviews/{review_id}",
        params={"tenant_id": tenant},
        headers=_auth(),
        json={"decision": "approve", "reviewer": "ops-1", "notes": "looks good"},
    )
    assert decide.status_code == 200
    assert decide.json()["record"]["decision"] == "approve"

    queue_after = client.get(
        "/owner/ocr/reviews",
        params={"tenant_id": tenant},
        headers=_auth(),
    )
    assert queue_after.status_code == 200
    assert all(item["review_id"] != review_id for item in queue_after.json()["items"])

    decide_again = client.post(
        f"/owner/ocr/reviews/{review_id}",
        params={"tenant_id": tenant},
        headers=_auth(),
        json={"decision": "reject", "reviewer": "ops-2", "notes": None},
    )
    assert decide_again.status_code == 409

