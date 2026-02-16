from features.voice_flow_a import VoiceFlowAController


def _new_controller(*, max_backlog_frames: int = 4, pace_ms: int = 20):
    openai_events: list[dict] = []
    twilio_events: list[dict] = []
    ctrl = VoiceFlowAController(
        send_openai=openai_events.append,
        send_twilio=twilio_events.append,
        max_backlog_frames=max_backlog_frames,
        pace_ms=pace_ms,
    )
    ctrl.set_stream_sid("MZ123")
    return ctrl, openai_events, twilio_events


def test_barge_in_triggers_cancel_clear_and_stops_outbound_audio() -> None:
    ctrl, openai_events, twilio_events = _new_controller(max_backlog_frames=8, pace_ms=20)

    ctrl.enqueue_assistant_frame("f1")
    ctrl.enqueue_assistant_frame("f2")
    ctrl.enqueue_assistant_frame("f3")
    assert ctrl.backlog_frames == 3

    ctrl.handle_openai_event({"type": "input_audio_buffer.speech_started"})

    assert openai_events == [{"type": "response.cancel"}]
    assert twilio_events == [{"event": "clear", "streamSid": "MZ123"}]
    assert ctrl.backlog_frames == 0
    assert ctrl.next_twilio_media(now_ms=1_000) is None


def test_backlog_cap_drops_old_frames_and_stays_bounded() -> None:
    ctrl, _, _ = _new_controller(max_backlog_frames=3, pace_ms=1)

    ctrl.enqueue_assistant_frame("f1")
    ctrl.enqueue_assistant_frame("f2")
    ctrl.enqueue_assistant_frame("f3")
    ctrl.enqueue_assistant_frame("f4")
    ctrl.enqueue_assistant_frame("f5")

    assert ctrl.backlog_frames == 3
    assert ctrl.dropped_frames == 2
    assert ctrl.backlog_payloads() == ["f3", "f4", "f5"]


def test_outbound_media_is_paced() -> None:
    ctrl, _, _ = _new_controller(max_backlog_frames=4, pace_ms=20)

    ctrl.enqueue_assistant_frame("f1")
    ctrl.enqueue_assistant_frame("f2")

    first = ctrl.next_twilio_media(now_ms=100)
    blocked = ctrl.next_twilio_media(now_ms=110)
    second = ctrl.next_twilio_media(now_ms=120)

    assert first == {"event": "media", "streamSid": "MZ123", "media": {"payload": "f1"}}
    assert blocked is None
    assert second == {"event": "media", "streamSid": "MZ123", "media": {"payload": "f2"}}
