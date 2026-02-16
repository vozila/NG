from __future__ import annotations

from core.app import create_app
from features.voice_flow_a import is_twilio_stop, parse_twilio_media, parse_twilio_start


def _has_route(app, path: str) -> bool:
    return any(getattr(route, "path", None) == path for route in app.routes)


def test_parse_twilio_start_extracts_allowlisted_custom_params() -> None:
    parsed = parse_twilio_start(
        {
            "event": "start",
            "start": {
                "streamSid": "MZ111",
                "callSid": "CA111",
                "customParameters": {
                    "tenant_id": " tenant-1 ",
                    "from_number": " +15550001111 ",
                    "tenant": "blocked",
                },
            },
        }
    )
    assert parsed == {
        "streamSid": "MZ111",
        "callSid": "CA111",
        "from_number": "+15550001111",
        "tenant_id": "tenant-1",
    }


def test_parse_twilio_media_handles_valid_and_malformed_payload() -> None:
    assert parse_twilio_media({"event": "media", "media": {"payload": "aGVsbG8="}}) == b"hello"
    assert parse_twilio_media({"event": "media", "media": {"payload": "*"}}) is None
    assert parse_twilio_media({"event": "media", "media": {"payload": None}}) is None


def test_is_twilio_stop() -> None:
    assert is_twilio_stop({"event": "stop"}) is True
    assert is_twilio_stop({"event": "media"}) is False


def test_route_mounting_respects_voice_feature_flag(monkeypatch) -> None:
    monkeypatch.setenv("VOZ_FEATURE_SAMPLE", "0")
    monkeypatch.setenv("VOZ_FEATURE_ADMIN_QUALITY", "0")

    monkeypatch.setenv("VOZ_FEATURE_VOICE_FLOW_A", "0")
    app_off = create_app()
    assert _has_route(app_off, "/twilio/stream") is False

    monkeypatch.setenv("VOZ_FEATURE_VOICE_FLOW_A", "1")
    app_on = create_app()
    assert _has_route(app_on, "/twilio/stream") is True
