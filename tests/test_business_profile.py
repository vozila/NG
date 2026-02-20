from __future__ import annotations

from fastapi.testclient import TestClient

from core.app import create_app


def _set_env(monkeypatch, db_path: str) -> None:
    monkeypatch.setenv("VOZ_DB_PATH", db_path)
    monkeypatch.setenv("VOZ_FEATURE_BUSINESS_PROFILE", "1")
    monkeypatch.setenv("VOZ_OWNER_BUSINESS_PROFILE_ENABLED", "1")
    monkeypatch.setenv("VOZ_OWNER_API_KEY", "owner-secret")


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer owner-secret"}


def test_business_profile_requires_auth(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, str(tmp_path / "business_profile_auth.sqlite3"))
    client = TestClient(create_app())
    resp = client.get("/owner/business/profile", params={"tenant_id": "tenant_demo"})
    assert resp.status_code == 401


def test_business_profile_crud_flow(monkeypatch, tmp_path) -> None:
    _set_env(monkeypatch, str(tmp_path / "business_profile_crud.sqlite3"))
    tenant = "tenant_demo"
    client = TestClient(create_app())

    put_resp = client.put(
        "/owner/business/profile",
        headers=_auth(),
        json={
            "tenant_id": tenant,
            "business_name": "Glow Studio",
            "phone": "+15180001111",
            "email": "hello@example.com",
            "timezone": "America/New_York",
            "address": "123 Main St",
            "services": ["facial", "laser"],
            "notes": "Owner prefers short scripts",
        },
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["profile"]["business_name"] == "Glow Studio"

    get_resp = client.get(
        "/owner/business/profile",
        params={"tenant_id": tenant},
        headers=_auth(),
    )
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["tenant_id"] == tenant
    assert body["profile"]["services"] == ["facial", "laser"]

    delete_resp = client.delete(
        "/owner/business/profile",
        params={"tenant_id": tenant},
        headers=_auth(),
    )
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True

    after_delete = client.get(
        "/owner/business/profile",
        params={"tenant_id": tenant},
        headers=_auth(),
    )
    assert after_delete.status_code == 200
    assert after_delete.json()["profile"] is None

