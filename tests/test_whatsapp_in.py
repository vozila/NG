import os

from fastapi.testclient import TestClient

from core.app import create_app
from features.whatsapp_in import normalize_inbound


def test_normalize_inbound_handles_simplified_payload():
    event = normalize_inbound(
        {
            "from": "+15550001111",
            "to": "+15559990000",
            "text": {"body": "hello"},
            "media": [{"url": "https://cdn.example/a.jpg"}, {"url": ""}],
            "timestamp": "1730000000",
        }
    )
    assert event == {
        "channel": "whatsapp",
        "from": "+15550001111",
        "to": "+15559990000",
        "text": "hello",
        "media_urls": ["https://cdn.example/a.jpg"],
        "ts": 1730000000,
    }


def test_normalize_inbound_handles_missing_fields():
    event = normalize_inbound({})
    assert event["channel"] == "whatsapp"
    assert event["from"] == ""
    assert event["to"] == ""
    assert event["text"] == ""
    assert event["media_urls"] == []
    assert isinstance(event["ts"], int)


def test_whatsapp_inbound_route_mounting_flag_off_on():
    old = os.getenv("VOZ_FEATURE_WHATSAPP_IN")
    try:
        os.environ["VOZ_FEATURE_WHATSAPP_IN"] = "0"
        app_off = create_app()
        paths_off = {route.path for route in app_off.routes}
        assert "/whatsapp/inbound" not in paths_off

        os.environ["VOZ_FEATURE_WHATSAPP_IN"] = "1"
        app_on = create_app()
        paths_on = {route.path for route in app_on.routes}
        assert "/whatsapp/inbound" in paths_on

        client = TestClient(app_on)
        resp = client.post(
            "/whatsapp/inbound",
            json={"from": "a", "to": "b", "text": "hi", "ts": 1},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["result"]["status"] == "accepted"
    finally:
        if old is None:
            os.environ.pop("VOZ_FEATURE_WHATSAPP_IN", None)
        else:
            os.environ["VOZ_FEATURE_WHATSAPP_IN"] = old
