from __future__ import annotations

from core.app import create_app
from features.voice_flow_a import (
    _build_openai_session_update,
    _build_twilio_clear_msg,
    _chunk_to_frames,
    OutgoingAudioBuffers,
    WaitingAudioController,
)


def _has_route(app, path: str) -> bool:
    return any(getattr(route, "path", None) == path for route in app.routes)


def test_route_mounting_respects_voice_feature_flag(monkeypatch) -> None:
    monkeypatch.setenv("VOZ_FEATURE_SAMPLE", "0")
    monkeypatch.setenv("VOZ_FEATURE_ADMIN_QUALITY", "0")

    monkeypatch.setenv("VOZ_FEATURE_VOICE_FLOW_A", "0")
    app_off = create_app()
    assert _has_route(app_off, "/twilio/stream") is False

    monkeypatch.setenv("VOZ_FEATURE_VOICE_FLOW_A", "1")
    app_on = create_app()
    assert _has_route(app_on, "/twilio/stream") is True


def test_waiting_audio_controller_disables_aux_on_user_speech() -> None:
    buffers = OutgoingAudioBuffers()
    buffers.aux.append(b"x" * 160)

    ctl = WaitingAudioController()
    assert ctl.aux_enabled is True

    ctl.on_user_speech_started(buffers=buffers)
    assert ctl.aux_enabled is False
    assert len(buffers.aux) == 0


def test_waiting_audio_controller_reenables_aux_on_model_done() -> None:
    ctl = WaitingAudioController()
    ctl.on_model_speech_started()
    assert ctl.aux_enabled is False
    ctl.on_model_speech_done()
    assert ctl.aux_enabled is True


def test_chunk_to_frames_yields_160_byte_frames_with_remainder() -> None:
    remainder = bytearray()
    out1 = _chunk_to_frames(remainder, b"x" * 200, frame_bytes=160)
    assert out1 == [b"x" * 160]
    assert len(remainder) == 40

    out2 = _chunk_to_frames(remainder, b"y" * 120, frame_bytes=160)
    assert len(out2) == 1
    assert len(out2[0]) == 160
    assert len(remainder) == 0


def test_build_twilio_clear_msg() -> None:
    assert _build_twilio_clear_msg("MZ123") == {"event": "clear", "streamSid": "MZ123"}


def test_build_openai_session_update_uses_legacy_ulaw_session_schema() -> None:
    msg = _build_openai_session_update(voice="marin", instructions="Be brief.")

    assert msg["type"] == "session.update"
    assert msg["session"]["modalities"] == ["audio"]
    assert msg["session"]["voice"] == "marin"
    assert msg["session"]["input_audio_format"] == "g711_ulaw"
    assert msg["session"]["output_audio_format"] == "g711_ulaw"
    assert "output_modalities" not in msg["session"]
    assert "type" not in msg["session"]
    assert "audio" not in msg["session"]

    assert msg["session"]["turn_detection"] == {
        "type": "server_vad",
        "create_response": True,
        "interrupt_response": True,
    }
