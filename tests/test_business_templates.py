from __future__ import annotations

from fastapi.testclient import TestClient

from core.app import create_app


def _set_env(monkeypatch, db_path: str) -> None:
    monkeypatch.setenv("VOZ_DB_PATH", db_path)
    monkeypatch.setenv("VOZ_FEATURE_BUSINESS_TEMPLATES", "1")
    monkeypatch.setenv("VOZ_OWNER_API_KEY", "owner-secret")


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer owner-secret"}


def test_business_templates_requires_auth(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, str(tmp_path / "business_templates_auth.sqlite3"))
    client = TestClient(create_app())
    resp = client.get("/owner/business/templates/catalog")
    assert resp.status_code == 401


def test_business_templates_catalog_and_current(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, str(tmp_path / "business_templates_current.sqlite3"))
    tenant = "tenant_demo"
    client = TestClient(create_app())

    catalog_resp = client.get("/owner/business/templates/catalog", headers=_auth())
    assert catalog_resp.status_code == 200
    templates = catalog_resp.json()["templates"]
    assert len(templates) >= 1
    template_id = templates[0]["template_id"]

    current_default = client.get(
        "/owner/business/templates/current",
        params={"tenant_id": tenant},
        headers=_auth(),
    )
    assert current_default.status_code == 200
    assert current_default.json()["selection"]["template_id"] == template_id

    set_resp = client.put(
        "/owner/business/templates/current",
        headers=_auth(),
        json={
            "tenant_id": tenant,
            "template_id": template_id,
            "custom_instructions": "Keep answers under 20 words.",
        },
    )
    assert set_resp.status_code == 200

    current_after = client.get(
        "/owner/business/templates/current",
        params={"tenant_id": tenant},
        headers=_auth(),
    )
    assert current_after.status_code == 200
    assert current_after.json()["selection"]["custom_instructions"] == "Keep answers under 20 words."


def test_business_templates_rejects_unknown_template(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, str(tmp_path / "business_templates_bad.sqlite3"))
    client = TestClient(create_app())
    resp = client.put(
        "/owner/business/templates/current",
        headers=_auth(),
        json={
            "tenant_id": "tenant_demo",
            "template_id": "missing-template",
            "custom_instructions": None,
        },
    )
    assert resp.status_code == 400

