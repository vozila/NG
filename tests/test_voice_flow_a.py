from __future__ import annotations

from core.app import create_app
from features.voice_flow_a import (
    _build_openai_session_update,
    _build_twilio_clear_message,
    _chunk_mulaw_frames,
    OutgoingAudioBuffers,
    WaitingAudioConfig,
    WaitingAudioController,
    is_twilio_stop,
    parse_twilio_media,
    parse_twilio_start,
    pick_next_outgoing_frame,
)


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
        "tenant_mode": None,
        "rid": "CA111",
    }


def test_parse_twilio_start_extracts_tenant_mode_and_rid() -> None:
    parsed = parse_twilio_start(
        {
            "event": "start",
            "start": {
                "streamSid": "MZ222",
                "callSid": "CA222",
                "customParameters": {
                    "tenant_id": "tenant-2",
                    "tenant_mode": "shared",
                    "rid": "RID-222",
                },
            },
        }
    )
    assert parsed["tenant_id"] == "tenant-2"
    assert parsed["tenant_mode"] == "shared"
    assert parsed["rid"] == "RID-222"


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


def test_waiting_audio_starts_after_trigger_and_enqueues_chime() -> None:
    buffers = OutgoingAudioBuffers()
    cfg = WaitingAudioConfig(
        enabled=True,
        trigger_ms=800,
        period_ms=1500,
        chime_frames=(b"a" * 160, b"b" * 160),
    )
    ctl = WaitingAudioController(cfg=cfg)

    ctl.wait_start(now_ms=0)

    ctl.update(now_ms=799, buffers=buffers)
    assert ctl.thinking_audio_active is False
    assert list(buffers.aux) == []

    ctl.update(now_ms=800, buffers=buffers)
    assert ctl.thinking_audio_active is True
    assert list(buffers.aux) == [b"a" * 160, b"b" * 160]


def test_waiting_audio_stops_on_user_speech_and_suppresses_until_end() -> None:
    buffers = OutgoingAudioBuffers()
    cfg = WaitingAudioConfig(
        enabled=True,
        trigger_ms=10,
        period_ms=100,
        chime_frames=(b"x" * 160,),
    )
    ctl = WaitingAudioController(cfg=cfg)
    ctl.wait_start(now_ms=0)

    ctl.update(now_ms=10, buffers=buffers)
    assert ctl.thinking_audio_active is True
    assert len(buffers.aux) == 1

    ctl.on_user_speech_started(buffers=buffers)
    assert ctl.thinking_audio_active is False
    assert len(buffers.aux) == 0

    # Even after the trigger, we should remain suppressed until wait_end().
    ctl.update(now_ms=10_000, buffers=buffers)
    assert ctl.thinking_audio_active is False
    assert len(buffers.aux) == 0

    ctl.wait_end(buffers=buffers)
    assert ctl.waiting_active is False
    assert ctl.suppressed_until_end is False


def test_main_lane_always_wins_over_aux_lane() -> None:
    buffers = OutgoingAudioBuffers()
    buffers.main.append(b"MAIN")
    buffers.aux.append(b"AUX")

    picked1 = pick_next_outgoing_frame(buffers, thinking_audio_active=True)
    assert picked1 == ("main", b"MAIN")

    picked2 = pick_next_outgoing_frame(buffers, thinking_audio_active=True)
    assert picked2 == ("aux", b"AUX")


def test_chunk_mulaw_frames_yields_160_byte_frames_with_remainder() -> None:
    remainder = bytearray()
    out1 = _chunk_mulaw_frames(remainder, b"x" * 200, frame_bytes=160)
    assert out1 == [b"x" * 160]
    assert len(remainder) == 40

    out2 = _chunk_mulaw_frames(remainder, b"y" * 120, frame_bytes=160)
    assert len(out2) == 1
    assert len(out2[0]) == 160
    assert len(remainder) == 0


def test_build_twilio_clear_message() -> None:
    assert _build_twilio_clear_message("MZ123") == {"event": "clear", "streamSid": "MZ123"}


def test_build_openai_session_update_uses_pcmu_and_server_vad() -> None:
    msg = _build_openai_session_update(voice="marin", instructions="Be brief.")
    assert msg["type"] == "session.update"
    assert msg["session"]["output_modalities"] == ["audio"]
    assert msg["session"]["audio"]["input"]["format"]["type"] == "audio/pcmu"
    assert msg["session"]["audio"]["output"]["format"]["type"] == "audio/pcmu"
    assert msg["session"]["audio"]["output"]["voice"] == "marin"
    assert msg["session"]["audio"]["input"]["turn_detection"] == {
        "type": "server_vad",
        "create_response": True,
        "interrupt_response": True,
    }
