from __future__ import annotations

import asyncio

from core.app import create_app
from features import voice_flow_a
from features.voice_flow_a import (
    OutgoingAudioBuffers,
    WaitingAudioController,
    _audio_queue_bytes,
    _barge_in_allowed,
    _build_customer_instructions,
    _build_owner_instructions,
    _build_openai_session_update,
    _build_twilio_clear_msg,
    _build_twilio_mark_msg,
    _chunk_to_frames,
    _customer_sms_followup_enabled,
    _detect_transcript_intents,
    _detect_owner_goal_actions,
    _diag_init,
    _diag_score,
    _diag_update_frame,
    _effective_prebuffer_frames,
    _force_input_commit_min_frames,
    _force_input_commit_after_s,
    _force_input_commit_enabled,
    _flush_on_response_created_enabled,
    _flush_output_audio_buffers,
    _initial_greeting_enabled,
    _initial_greeting_text,
    _is_sender_underrun_state,
    _lifecycle_event_payload,
    _playout_low_water_frames,
    _playout_refill_hold_s,
    _playout_start_frames,
    _resolve_customer_knowledge_context,
    _resolve_intent_decisions,
    _resolve_actor_mode_policy,
    _sanitize_transcript_for_event,
    _should_accept_response_audio,
    _speech_started_debounce_s,
    _twilio_chunk_frames,
    _twilio_chunk_mode_enabled,
    _twilio_mark_enabled,
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


def test_audio_queue_bytes_counts_main_aux_and_remainder() -> None:
    buffers = OutgoingAudioBuffers()
    buffers.main.extend([b"a" * 160, b"b" * 160])
    buffers.aux.append(b"c" * 160)
    buffers.remainder.extend(b"d" * 10)
    assert _audio_queue_bytes(buffers) == (3 * 160) + 10


def test_flush_output_audio_buffers_clears_all_lanes_and_remainder() -> None:
    buffers = OutgoingAudioBuffers()
    buffers.main.extend([b"a" * 160, b"b" * 160])
    buffers.aux.append(b"c" * 160)
    buffers.remainder.extend(b"d" * 11)
    dropped = _flush_output_audio_buffers(buffers)
    assert dropped == (3 * 160) + 11
    assert len(buffers.main) == 0
    assert len(buffers.aux) == 0
    assert len(buffers.remainder) == 0


def test_is_sender_underrun_state_active_response() -> None:
    buffers = OutgoingAudioBuffers()
    state = {"active_response_id": "resp_123"}
    assert _is_sender_underrun_state(response_state=state, buffers=buffers) is True


def test_is_sender_underrun_state_idle_silence() -> None:
    buffers = OutgoingAudioBuffers()
    state = {"active_response_id": None}
    assert _is_sender_underrun_state(response_state=state, buffers=buffers) is False


def test_is_sender_underrun_state_buffered_main_without_active_response() -> None:
    buffers = OutgoingAudioBuffers()
    buffers.main.append(b"x" * 160)
    state = {"active_response_id": None}
    assert _is_sender_underrun_state(response_state=state, buffers=buffers) is True


def test_diag_score_ok_for_varied_audio() -> None:
    diag = _diag_init()
    prev = None
    for i in range(40):
        frame = bytes((j + i) % 256 for j in range(160))
        _diag_update_frame(diag, frame, prev)
        prev = frame
    assert _diag_score(diag) == "ok"


def test_diag_score_bad_for_highly_repetitive_audio() -> None:
    diag = _diag_init()
    frame = b"\xff" * 160
    prev = None
    for _ in range(120):
        _diag_update_frame(diag, frame, prev)
        prev = frame
    assert _diag_score(diag) == "bad"


def test_vad_speech_started_debounce_env_default(monkeypatch) -> None:
    monkeypatch.delenv("VOICE_VAD_SPEECH_STARTED_DEBOUNCE_MS", raising=False)
    assert _speech_started_debounce_s() == 0.3


def test_vad_speech_started_debounce_env_override(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_VAD_SPEECH_STARTED_DEBOUNCE_MS", "450")
    assert _speech_started_debounce_s() == 0.45


def test_initial_greeting_env_defaults(monkeypatch) -> None:
    monkeypatch.delenv("VOZ_FLOW_A_INITIAL_GREETING_ENABLED", raising=False)
    monkeypatch.delenv("VOZ_FLOW_A_INITIAL_GREETING_TEXT", raising=False)
    assert _initial_greeting_enabled() is False
    assert _initial_greeting_text() == "Please greet the caller briefly and ask how you can help."


def test_initial_greeting_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("VOZ_FLOW_A_INITIAL_GREETING_ENABLED", "1")
    monkeypatch.setenv("VOZ_FLOW_A_INITIAL_GREETING_TEXT", "Say hello.")
    assert _initial_greeting_enabled() is True
    assert _initial_greeting_text() == "Say hello."


def test_flush_on_response_created_enabled_default_on(monkeypatch) -> None:
    monkeypatch.delenv("VOICE_FLUSH_ON_RESPONSE_CREATED", raising=False)
    assert _flush_on_response_created_enabled() is True


def test_flush_on_response_created_enabled_override_off(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_FLUSH_ON_RESPONSE_CREATED", "0")
    assert _flush_on_response_created_enabled() is False


def test_force_input_commit_defaults(monkeypatch) -> None:
    monkeypatch.delenv("VOICE_FORCE_INPUT_COMMIT_FALLBACK", raising=False)
    monkeypatch.delenv("VOICE_FORCE_INPUT_COMMIT_MS", raising=False)
    monkeypatch.delenv("VOICE_FORCE_INPUT_COMMIT_MIN_FRAMES", raising=False)
    assert _force_input_commit_enabled() is True
    assert _force_input_commit_after_s() == 1.4
    assert _force_input_commit_min_frames() == 5


def test_force_input_commit_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_FORCE_INPUT_COMMIT_FALLBACK", "0")
    monkeypatch.setenv("VOICE_FORCE_INPUT_COMMIT_MS", "900")
    monkeypatch.setenv("VOICE_FORCE_INPUT_COMMIT_MIN_FRAMES", "8")
    assert _force_input_commit_enabled() is False
    assert _force_input_commit_after_s() == 0.9
    assert _force_input_commit_min_frames() == 8


def test_effective_prebuffer_frames_has_guardrail(monkeypatch) -> None:
    monkeypatch.delenv("VOICE_TWILIO_PREBUFFER_FRAMES", raising=False)
    assert _effective_prebuffer_frames(200) == 80
    monkeypatch.setenv("VOICE_TWILIO_PREBUFFER_FRAMES", "4")
    assert _effective_prebuffer_frames(200) == 40
    monkeypatch.setenv("VOICE_TWILIO_PREBUFFER_FRAMES", "120")
    assert _effective_prebuffer_frames(200) == 120
    monkeypatch.setenv("VOICE_TWILIO_PREBUFFER_FRAMES", "500")
    assert _effective_prebuffer_frames(200) == 199


def test_playout_start_frames_clamped_to_safe_range(monkeypatch) -> None:
    monkeypatch.delenv("VOICE_TWILIO_START_BUFFER_FRAMES", raising=False)
    assert _playout_start_frames(80) == 24

    monkeypatch.setenv("VOICE_TWILIO_START_BUFFER_FRAMES", "2")
    assert _playout_start_frames(80) == 4

    monkeypatch.setenv("VOICE_TWILIO_START_BUFFER_FRAMES", "120")
    assert _playout_start_frames(30) == 30


def test_playout_low_water_frames_defaults_off_and_clamps(monkeypatch) -> None:
    monkeypatch.delenv("VOICE_TWILIO_LOW_WATER_FRAMES", raising=False)
    assert _playout_low_water_frames(24) == 0

    monkeypatch.setenv("VOICE_TWILIO_LOW_WATER_FRAMES", "1")
    assert _playout_low_water_frames(24) == 2

    monkeypatch.setenv("VOICE_TWILIO_LOW_WATER_FRAMES", "50")
    assert _playout_low_water_frames(24) == 24


def test_playout_refill_hold_seconds(monkeypatch) -> None:
    monkeypatch.delenv("VOICE_TWILIO_REFILL_HOLD_MS", raising=False)
    assert _playout_refill_hold_s() == 0.0

    monkeypatch.setenv("VOICE_TWILIO_REFILL_HOLD_MS", "120")
    assert _playout_refill_hold_s() == 0.12

    monkeypatch.setenv("VOICE_TWILIO_REFILL_HOLD_MS", "-5")
    assert _playout_refill_hold_s() == 0.0


def test_should_accept_response_audio_requires_active_response() -> None:
    assert _should_accept_response_audio(response_id=None, active_response_id=None) is False
    assert _should_accept_response_audio(response_id="r1", active_response_id=None) is False
    assert _should_accept_response_audio(response_id=None, active_response_id="r1") is True
    assert _should_accept_response_audio(response_id="r1", active_response_id="r1") is True
    assert _should_accept_response_audio(response_id="r2", active_response_id="r1") is False


def test_barge_in_allowed_requires_min_age_and_frames() -> None:
    state = {"sent_main_frames_by_id": {"resp_1": 12}}
    started = {"resp_1": 100.0}
    assert (
        _barge_in_allowed(
            active_response_id="resp_1",
            response_started_at=started,
            response_state=state,
            now_monotonic=100.2,
            min_response_ms=450,
            min_frames=15,
        )
        is False
    )
    state["sent_main_frames_by_id"]["resp_1"] = 16
    assert (
        _barge_in_allowed(
            active_response_id="resp_1",
            response_started_at=started,
            response_state=state,
            now_monotonic=100.5,
            min_response_ms=450,
            min_frames=15,
        )
        is True
    )


def test_build_twilio_clear_msg() -> None:
    assert _build_twilio_clear_msg("MZ123") == {"event": "clear", "streamSid": "MZ123"}


def test_build_twilio_mark_msg() -> None:
    assert _build_twilio_mark_msg("MZ123", "m1") == {
        "event": "mark",
        "streamSid": "MZ123",
        "mark": {"name": "m1"},
    }


def test_twilio_chunk_mode_env(monkeypatch) -> None:
    monkeypatch.delenv("VOICE_TWILIO_CHUNK_MODE", raising=False)
    assert _twilio_chunk_mode_enabled() is True
    monkeypatch.setenv("VOICE_TWILIO_CHUNK_MODE", "0")
    assert _twilio_chunk_mode_enabled() is False
    monkeypatch.setenv("VOICE_TWILIO_CHUNK_MODE", "1")
    assert _twilio_chunk_mode_enabled() is True


def test_twilio_chunk_frames_clamped(monkeypatch) -> None:
    monkeypatch.delenv("VOICE_TWILIO_CHUNK_MS", raising=False)
    assert _twilio_chunk_frames() == 6  # 120ms / 20ms
    monkeypatch.setenv("VOICE_TWILIO_CHUNK_MS", "5")
    assert _twilio_chunk_frames() == 1
    monkeypatch.setenv("VOICE_TWILIO_CHUNK_MS", "500")
    assert _twilio_chunk_frames() == 20


def test_twilio_mark_enabled_env(monkeypatch) -> None:
    monkeypatch.delenv("VOICE_TWILIO_MARK_ENABLED", raising=False)
    assert _twilio_mark_enabled() is True
    monkeypatch.setenv("VOICE_TWILIO_MARK_ENABLED", "0")
    assert _twilio_mark_enabled() is False


def test_build_openai_session_update_uses_legacy_ulaw_session_schema() -> None:
    msg = _build_openai_session_update(voice="marin", instructions="Be brief.")

    assert msg["type"] == "session.update"
    assert msg["session"]["modalities"] == ["audio", "text"]
    assert msg["session"]["voice"] == "marin"
    assert msg["session"]["input_audio_format"] == "g711_ulaw"
    assert msg["session"]["output_audio_format"] == "g711_ulaw"
    assert "output_modalities" not in msg["session"]
    assert "type" not in msg["session"]
    assert "audio" not in msg["session"]

    assert msg["session"]["turn_detection"] == {
        "type": "server_vad",
        "threshold": 0.5,
        "silence_duration_ms": 500,
        "create_response": False,
        "interrupt_response": True,
    }
    assert msg["session"]["input_audio_transcription"] == {"model": "gpt-4o-mini-transcribe"}


def test_resolve_actor_mode_policy_unknown_mode_defaults_to_client(monkeypatch) -> None:
    monkeypatch.setenv("VOZ_FLOW_A_ACTOR_MODE_POLICY", "1")
    monkeypatch.setenv("VOZ_OPENAI_REALTIME_VOICE", "marin")
    monkeypatch.setenv("VOZ_OPENAI_REALTIME_VOICE_CLIENT", "alloy")
    monkeypatch.setenv("VOZ_OPENAI_REALTIME_INSTRUCTIONS_CLIENT", "Client protocol")

    voice, instructions = _resolve_actor_mode_policy("tenant_demo", "unexpected")
    assert voice == "alloy"
    assert instructions == "Client protocol"


def test_resolve_actor_mode_policy_uses_tenant_json_for_owner(monkeypatch) -> None:
    monkeypatch.setenv("VOZ_FLOW_A_ACTOR_MODE_POLICY", "1")
    monkeypatch.setenv(
        "VOZ_TENANT_MODE_POLICY_JSON",
        (
            '{"tenant_demo":{"client":{"instructions":"client default","voice":"marin"},'
            '"owner":{"instructions":"owner analytics","voice":"cedar"}}}'
        ),
    )
    monkeypatch.setenv("VOZ_OPENAI_REALTIME_VOICE_OWNER", "alloy")
    monkeypatch.setenv("VOZ_OPENAI_REALTIME_INSTRUCTIONS_OWNER", "owner env")

    voice, instructions = _resolve_actor_mode_policy("tenant_demo", "owner")
    assert voice == "cedar"
    assert instructions == "owner analytics"


def test_resolve_actor_mode_policy_falls_back_to_mode_env_when_json_missing(monkeypatch) -> None:
    monkeypatch.setenv("VOZ_FLOW_A_ACTOR_MODE_POLICY", "1")
    monkeypatch.delenv("VOZ_TENANT_MODE_POLICY_JSON", raising=False)
    monkeypatch.setenv("VOZ_OPENAI_REALTIME_VOICE", "marin")
    monkeypatch.setenv("VOZ_OPENAI_REALTIME_INSTRUCTIONS", "base instructions")
    monkeypatch.setenv("VOZ_OPENAI_REALTIME_VOICE_OWNER", "alloy")
    monkeypatch.setenv("VOZ_OPENAI_REALTIME_INSTRUCTIONS_OWNER", "owner env instructions")

    voice, instructions = _resolve_actor_mode_policy("tenant_demo", "owner")
    assert voice == "alloy"
    assert instructions == "owner env instructions"


def test_resolve_actor_mode_policy_when_kill_switch_off_uses_base_env(monkeypatch) -> None:
    monkeypatch.setenv("VOZ_FLOW_A_ACTOR_MODE_POLICY", "0")
    monkeypatch.setenv("VOZ_OPENAI_REALTIME_VOICE", "marin")
    monkeypatch.setenv("VOZ_OPENAI_REALTIME_INSTRUCTIONS", "base instructions")
    monkeypatch.setenv("VOZ_OPENAI_REALTIME_VOICE_OWNER", "alloy")
    monkeypatch.setenv("VOZ_OPENAI_REALTIME_INSTRUCTIONS_OWNER", "owner env instructions")
    monkeypatch.setenv(
        "VOZ_TENANT_MODE_POLICY_JSON",
        '{"tenant_demo":{"owner":{"instructions":"owner analytics","voice":"cedar"}}}',
    )

    voice, instructions = _resolve_actor_mode_policy("tenant_demo", "owner")
    assert voice == "marin"
    assert instructions == "base instructions"


def test_resolve_customer_knowledge_context_from_custom_parameters(monkeypatch) -> None:
    monkeypatch.delenv("VOZ_FLOW_A_DEFAULT_TEMPLATE_KEY", raising=False)
    monkeypatch.delenv("VOZ_FLOW_A_DEFAULT_PROFILE_VERSION", raising=False)
    monkeypatch.delenv("VOZ_FLOW_A_DEFAULT_PROFILE_HASH", raising=False)
    monkeypatch.delenv("VOZ_FLOW_A_DEFAULT_PROFILE_SUMMARY", raising=False)
    monkeypatch.delenv("VOZ_FLOW_A_DEFAULT_TEMPLATE_PROMPT", raising=False)

    ctx = _resolve_customer_knowledge_context(
        custom_parameters={
            "template_key": "salon_v1",
            "business_profile_version": "42",
            "business_profile_hash": "sha256:abc123",
            "business_profile_summary": "Hours 9-5; haircut from $30",
            "business_template_prompt": "Highlight booking availability.",
        }
    )
    assert ctx["template_key"] == "salon_v1"
    assert ctx["profile_version"] == "42"
    assert ctx["profile_hash"] == "sha256:abc123"
    assert ctx["profile_summary"] == "Hours 9-5; haircut from $30"
    assert ctx["template_prompt"] == "Highlight booking availability."


def test_resolve_customer_knowledge_context_falls_back_to_env(monkeypatch) -> None:
    monkeypatch.setenv("VOZ_FLOW_A_DEFAULT_TEMPLATE_KEY", "default_tpl")
    monkeypatch.setenv("VOZ_FLOW_A_DEFAULT_PROFILE_VERSION", "3")
    monkeypatch.setenv("VOZ_FLOW_A_DEFAULT_PROFILE_HASH", "hash_xyz")
    monkeypatch.setenv("VOZ_FLOW_A_DEFAULT_PROFILE_SUMMARY", "Default profile summary")
    monkeypatch.setenv("VOZ_FLOW_A_DEFAULT_TEMPLATE_PROMPT", "Default template prompt")

    ctx = _resolve_customer_knowledge_context(custom_parameters={})
    assert ctx["template_key"] == "default_tpl"
    assert ctx["profile_version"] == "3"
    assert ctx["profile_hash"] == "hash_xyz"
    assert ctx["profile_summary"] == "Default profile summary"
    assert ctx["template_prompt"] == "Default template prompt"


def test_build_customer_instructions_includes_baseline_and_knowledge(monkeypatch) -> None:
    monkeypatch.setenv("VOZ_FLOW_A_CUSTOMER_SAFE_BASELINE", "Use careful customer-safe language.")
    monkeypatch.setenv("VOZ_FLOW_A_TALK_TO_OWNER_BASELINE", "Escalate owner requests and capture callback.")
    out = _build_customer_instructions(
        base_instructions="Base policy.",
        mode_instructions="Customer mode policy.",
        knowledge_context={
            "template_key": "salon_v1",
            "profile_version": "7",
            "profile_hash": "hash_7",
            "profile_summary": "Haircut from $30.",
            "template_prompt": "Be brief and practical.",
        },
    )
    assert "Customer mode policy." in out
    assert "Use careful customer-safe language." in out
    assert "template_key: salon_v1" in out
    assert "profile_version: 7" in out
    assert "profile_hash: hash_7" in out
    assert "profile_summary: Haircut from $30." in out
    assert "template_prompt: Be brief and practical." in out
    assert "Escalate owner requests and capture callback." in out


def test_build_customer_instructions_uses_base_when_mode_missing(monkeypatch) -> None:
    monkeypatch.setenv("VOZ_FLOW_A_CUSTOMER_SAFE_BASELINE", "Escalate when needed.")
    monkeypatch.setenv("VOZ_FLOW_A_TALK_TO_OWNER_BASELINE", "Offer owner follow-up.")
    out = _build_customer_instructions(
        base_instructions="Base instructions only.",
        mode_instructions=None,
        knowledge_context={
            "template_key": None,
            "profile_version": None,
            "profile_hash": None,
            "profile_summary": None,
            "template_prompt": None,
        },
    )
    assert "Base instructions only." in out
    assert "Escalate when needed." in out
    assert "Offer owner follow-up." in out
    assert "Knowledge context:" not in out


def test_build_owner_instructions_includes_goal_baseline(monkeypatch) -> None:
    monkeypatch.setenv("VOZ_FLOW_A_OWNER_GOAL_BASELINE", "Keep list-goals short and confirm pause/resume target.")
    out = _build_owner_instructions(
        base_instructions="Owner base instructions.",
        mode_instructions=None,
    )
    assert "Owner base instructions." in out
    assert "Keep list-goals short and confirm pause/resume target." in out


def test_detect_transcript_intents_flags_callback_appointment_and_owner() -> None:
    out = _detect_transcript_intents(
        "Can I book an appointment and please have the owner call me back tomorrow?"
    )
    assert out["callback"] is True
    assert out["appointment"] is True
    assert out["talk_to_owner"] is True


def test_detect_transcript_intents_no_match() -> None:
    out = _detect_transcript_intents("Thanks, just checking your address.")
    assert out["callback"] is False
    assert out["appointment"] is False
    assert out["talk_to_owner"] is False


def test_detect_owner_goal_actions_goal_intake_and_text() -> None:
    out = _detect_owner_goal_actions("Please add goal: increase weekday bookings by 20 percent")
    assert out["goal_intake"] is True
    assert out["goal_text"] == "increase weekday bookings by 20 percent"


def test_detect_owner_goal_actions_list_pause_resume_and_ref() -> None:
    list_out = _detect_owner_goal_actions("Can you list goals quickly?")
    assert list_out["goal_list"] is True

    pause_out = _detect_owner_goal_actions("Pause goal 3 for now")
    assert pause_out["goal_pause"] is True
    assert pause_out["goal_ref"] == "goal 3"

    resume_out = _detect_owner_goal_actions("Resume goal #7")
    assert resume_out["goal_resume"] is True
    assert resume_out["goal_ref"] == "goal 7"


def test_customer_sms_followup_enabled_env(monkeypatch) -> None:
    monkeypatch.delenv("VOICE_CUSTOMER_SMS_FOLLOWUP_ENABLED", raising=False)
    assert _customer_sms_followup_enabled() is False
    monkeypatch.setenv("VOICE_CUSTOMER_SMS_FOLLOWUP_ENABLED", "1")
    assert _customer_sms_followup_enabled() is True


def test_resolve_intent_decisions_shadow_mode_keeps_heuristic_actions(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_INTENT_NLU_ENABLED", "1")
    monkeypatch.setenv("VOICE_INTENT_NLU_SHADOW_MODE", "1")
    monkeypatch.setenv("VOICE_INTENT_NLU_ACTIONS_ENABLED", "0")

    decisions, shadow = _resolve_intent_decisions(
        heuristic_intents={"callback": True, "appointment": False, "talk_to_owner": False},
        nlu_intents={
            "callback": {"detected": False, "confidence": 0.2},
            "appointment": {"detected": True, "confidence": 0.95},
            "talk_to_owner": {"detected": True, "confidence": 0.88},
        },
    )
    assert decisions["callback"]["detected"] is True
    assert decisions["callback"]["source"] == "heuristic"
    assert decisions["appointment"]["detected"] is False
    assert decisions["talk_to_owner"]["detected"] is False
    assert isinstance(shadow, dict)
    assert shadow["heuristic"]["callback"] is True
    assert shadow["nlu"]["appointment"]["detected"] is True


def test_resolve_intent_decisions_actions_enabled_uses_nlu_above_threshold(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_INTENT_NLU_ENABLED", "1")
    monkeypatch.setenv("VOICE_INTENT_NLU_SHADOW_MODE", "0")
    monkeypatch.setenv("VOICE_INTENT_NLU_ACTIONS_ENABLED", "1")
    monkeypatch.setenv("VOICE_INTENT_NLU_CONFIDENCE_MIN", "0.75")

    decisions, shadow = _resolve_intent_decisions(
        heuristic_intents={"callback": False, "appointment": False, "talk_to_owner": False},
        nlu_intents={
            "callback": {"detected": True, "confidence": 0.91},
            "appointment": {"detected": False, "confidence": 0.1},
            "talk_to_owner": {"detected": False, "confidence": 0.2},
        },
    )
    assert decisions["callback"]["detected"] is True
    assert decisions["callback"]["source"] == "nlu"
    assert decisions["callback"]["confidence"] == 0.91
    assert shadow is None


def test_resolve_intent_decisions_actions_enabled_falls_back_to_heuristics_when_nlu_low_conf(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_INTENT_NLU_ENABLED", "1")
    monkeypatch.setenv("VOICE_INTENT_NLU_SHADOW_MODE", "0")
    monkeypatch.setenv("VOICE_INTENT_NLU_ACTIONS_ENABLED", "1")
    monkeypatch.setenv("VOICE_INTENT_NLU_CONFIDENCE_MIN", "0.90")

    decisions, shadow = _resolve_intent_decisions(
        heuristic_intents={"callback": True, "appointment": False, "talk_to_owner": True},
        nlu_intents={
            "callback": {"detected": True, "confidence": 0.6},
            "appointment": {"detected": True, "confidence": 0.95},
            "talk_to_owner": {"detected": False, "confidence": 0.3},
        },
    )
    assert decisions["callback"]["detected"] is True
    assert decisions["callback"]["source"] == "heuristic"
    assert decisions["appointment"]["detected"] is True
    assert decisions["appointment"]["source"] == "nlu"
    assert decisions["talk_to_owner"]["detected"] is True
    assert decisions["talk_to_owner"]["source"] == "heuristic"
    assert shadow is None


def test_emit_flow_a_event_kill_switch_off_makes_no_db_calls(monkeypatch) -> None:
    monkeypatch.setenv("VOZ_FLOW_A_EVENT_EMIT", "0")
    calls: list[tuple[str, str, str]] = []

    def _fake_emit_event(
        tenant_id: str,
        rid: str,
        event_type: str,
        payload_dict: dict[str, object],
        trace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        calls.append((tenant_id, rid, event_type))
        return "evt_1"

    monkeypatch.setattr(voice_flow_a.core_db, "emit_event", _fake_emit_event)
    assert voice_flow_a._event_emit_enabled() is False

    asyncio.run(
        voice_flow_a._emit_flow_a_event(
            enabled=voice_flow_a._event_emit_enabled(),
            tenant_id="tenant_demo",
            rid="rid-123",
            event_type="flow_a.call_started",
            payload={
                "tenant_id": "tenant_demo",
                "rid": "rid-123",
                "ai_mode": "owner",
                "tenant_mode": "owner",
            },
        )
    )

    assert calls == []


def test_emit_flow_a_event_kill_switch_on_emits_expected_tuple(monkeypatch) -> None:
    monkeypatch.setenv("VOZ_FLOW_A_EVENT_EMIT", "1")
    calls: list[tuple[str, str, str]] = []

    def _fake_emit_event(
        tenant_id: str,
        rid: str,
        event_type: str,
        payload_dict: dict[str, object],
        trace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        calls.append((tenant_id, rid, event_type))
        return "evt_1"

    monkeypatch.setattr(voice_flow_a.core_db, "emit_event", _fake_emit_event)
    assert voice_flow_a._event_emit_enabled() is True

    asyncio.run(
        voice_flow_a._emit_flow_a_event(
            enabled=voice_flow_a._event_emit_enabled(),
            tenant_id="tenant_demo",
            rid="rid-456",
            event_type="flow_a.call_started",
            payload={
                "tenant_id": "tenant_demo",
                "rid": "rid-456",
                "ai_mode": "customer",
                "tenant_mode": "customer",
            },
        )
    )

    assert calls == [("tenant_demo", "rid-456", "flow_a.call_started")]


def test_sanitize_transcript_for_event_normalizes_whitespace() -> None:
    out = _sanitize_transcript_for_event(" hello   there \n\n this   is  a test ")
    assert out == "hello there this is a test"


def test_sanitize_transcript_for_event_truncates_to_max_chars() -> None:
    src = "a" * 700
    out = _sanitize_transcript_for_event(src, max_chars=500)
    assert len(out) == 500
    assert out == "a" * 500


def test_lifecycle_event_payload_includes_from_to_numbers() -> None:
    payload = _lifecycle_event_payload(
        tenant_id="tenant_demo",
        rid="rid-1",
        ai_mode="owner",
        tenant_mode="shared",
        call_sid="CA123",
        stream_sid="MZ123",
        from_number=" +15180001111 ",
        to_number="+15180002222",
        reason="twilio_stop",
    )
    assert payload["tenant_id"] == "tenant_demo"
    assert payload["rid"] == "rid-1"
    assert payload["from_number"] == "+15180001111"
    assert payload["to_number"] == "+15180002222"
    assert payload["reason"] == "twilio_stop"


def test_lifecycle_event_payload_missing_numbers_become_none() -> None:
    payload = _lifecycle_event_payload(
        tenant_id="tenant_demo",
        rid="rid-2",
        ai_mode="customer",
        tenant_mode="shared",
        call_sid="CA999",
        stream_sid="MZ999",
        from_number=" ",
        to_number=None,
        reason=None,
    )
    assert payload["from_number"] is None
    assert payload["to_number"] is None
    assert "reason" not in payload
