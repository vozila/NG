import os

from fastapi.testclient import TestClient

from core.app import create_app


def _client_with_flag(value: str) -> TestClient:
    os.environ["VOZ_FEATURE_ACCESS_GATE"] = value
    return TestClient(create_app())


def test_access_gate_happy_path():
    prev = os.getenv("VOZ_FEATURE_ACCESS_GATE")
    try:
        client = _client_with_flag("1")
        start = client.post("/access/start")
        assert start.status_code == 200
        token = start.json()["session_token"]

        step1 = client.post("/access/step", json={"session_token": token, "text": "business code"})
        assert step1.status_code == 200
        assert step1.json()["state"] == "AWAIT_TENANT_ID"

        step2 = client.post("/access/step", json={"session_token": token, "text": "tenant_01"})
        assert step2.status_code == 200
        assert step2.json()["state"] == "AWAIT_ACCESS_CODE"

        step3 = client.post("/access/step", json={"session_token": token, "text": "12345678"})
        assert step3.status_code == 200
        body = step3.json()
        assert body["done"] is True
        assert body["result"]["tenant_id"] == "tenant_01"
    finally:
        if prev is None:
            os.environ.pop("VOZ_FEATURE_ACCESS_GATE", None)
        else:
            os.environ["VOZ_FEATURE_ACCESS_GATE"] = prev


def test_access_gate_invalid_code_rejected():
    prev = os.getenv("VOZ_FEATURE_ACCESS_GATE")
    try:
        client = _client_with_flag("1")
        token = client.post("/access/start").json()["session_token"]
        client.post("/access/step", json={"session_token": token, "text": "business code"})
        client.post("/access/step", json={"session_token": token, "text": "tenant-02"})

        step = client.post("/access/step", json={"session_token": token, "text": "1234"})
        assert step.status_code == 200
        body = step.json()
        assert body["done"] is False
        assert body["state"] == "AWAIT_ACCESS_CODE"
        assert "8 digits" in body["prompt"]
    finally:
        if prev is None:
            os.environ.pop("VOZ_FEATURE_ACCESS_GATE", None)
        else:
            os.environ["VOZ_FEATURE_ACCESS_GATE"] = prev


def test_access_gate_routes_off_vs_on():
    prev = os.getenv("VOZ_FEATURE_ACCESS_GATE")
    try:
        off_client = _client_with_flag("0")
        assert off_client.post("/access/start").status_code == 404

        on_client = _client_with_flag("1")
        assert on_client.post("/access/start").status_code == 200
    finally:
        if prev is None:
            os.environ.pop("VOZ_FEATURE_ACCESS_GATE", None)
        else:
            os.environ["VOZ_FEATURE_ACCESS_GATE"] = prev
