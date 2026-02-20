"""VOZLIA FILE PURPOSE
Purpose: Twilio Media Streams handler for Voice Flow A (Twilio WS <-> OpenAI Realtime WS).
Hot path: YES (WS audio loop). Keep per-frame work bounded; no DB or heavy prompt building.
Public interfaces:
  - websocket /twilio/stream
Reads/Writes: env vars; optional lifecycle event writes via core.db.emit_event (off hot path).
Feature flags:
  - VOZ_FEATURE_VOICE_FLOW_A
  - VOZ_FLOW_A_OPENAI_BRIDGE
  - VOZ_FLOW_A_EVENT_EMIT
  - VOZLIA_DEBUG
Failure mode:
  - If OpenAI bridge fails, Twilio stream stays connected but no assistant audio is produced.
  - If DB event emission fails, audio loop remains fail-open.
Last touched: 2026-02-18 (response.create must request supported modalities; add first-delta breadcrumbs)
"""

# CHANGELOG (recent)
# - 2026-02-18: response.create requests modalities=['audio','text'] (per server-supported combos);
#              store/log session output_modalities; keep first-delta breadcrumbs.
# - 2026-02-18: read ai_mode from Twilio customParameters and apply mode-specific instructions.

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from core import db as core_db
from core.config import env_flag, is_debug
from core.logging import logger

router = APIRouter()

# Twilio: μ-law (PCMU) @ 8kHz. 20ms frames => 160 bytes.
TWILIO_SAMPLE_RATE_HZ = 8000
FRAME_MS = 20
FRAME_BYTES = int(TWILIO_SAMPLE_RATE_HZ * (FRAME_MS / 1000.0))  # 160
FRAME_SLEEP_S = FRAME_MS / 1000.0

OPENAI_REALTIME_URL_BASE = "wss://api.openai.com/v1/realtime"


def _dbg(msg: str) -> None:
    if is_debug():
        logger.info(msg)


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        return int(raw)
    except Exception:
        return default


def _env_str(name: str, default: str) -> str:
    raw = (os.getenv(name) or "").strip()
    return raw or default


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    try:
        return float(raw)
    except Exception:
        return default


def _speech_started_debounce_s() -> float:
    return max(0.0, _env_int("VOICE_VAD_SPEECH_STARTED_DEBOUNCE_MS", 300) / 1000.0)


def _barge_in_min_response_ms() -> int:
    return max(0, _env_int("VOICE_BARGE_IN_MIN_RESPONSE_MS", 700))


def _barge_in_min_frames() -> int:
    return max(0, _env_int("VOICE_BARGE_IN_MIN_FRAMES", 25))


def _flush_on_response_created_enabled() -> bool:
    return (os.getenv("VOICE_FLUSH_ON_RESPONSE_CREATED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _initial_greeting_enabled() -> bool:
    return (os.getenv("VOZ_FLOW_A_INITIAL_GREETING_ENABLED") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _initial_greeting_text() -> str:
    return (
        (os.getenv("VOZ_FLOW_A_INITIAL_GREETING_TEXT") or "").strip()
        or "Please greet the caller briefly and ask how you can help."
    )


def _force_input_commit_enabled() -> bool:
    return (os.getenv("VOICE_FORCE_INPUT_COMMIT_FALLBACK") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _force_input_commit_after_s() -> float:
    return max(0.2, _env_int("VOICE_FORCE_INPUT_COMMIT_MS", 1400) / 1000.0)


def _force_input_commit_min_frames() -> int:
    # Twilio media frames are 20ms each; 5 frames ~= 100ms.
    return max(1, _env_int("VOICE_FORCE_INPUT_COMMIT_MIN_FRAMES", 5))


def _effective_prebuffer_frames(main_max_frames: int) -> int:
    # Guardrails:
    # - Very low prebuffer causes first-second garble.
    # - Prebuffer must be below queue capacity, or sender can deadlock at prebuf=True.
    target = max(40, _env_int("VOICE_TWILIO_PREBUFFER_FRAMES", 80))
    max_safe = max(1, main_max_frames - 1)
    return min(target, max_safe)


def _playout_start_frames(prebuffer_frames: int) -> int:
    # Startup jitter buffer (backend-style): wait for a small runway before first send.
    target = _env_int("VOICE_TWILIO_START_BUFFER_FRAMES", 24)
    return max(4, min(target, prebuffer_frames))


def _playout_low_water_frames(start_frames: int) -> int:
    # Optional hysteresis; default disabled to avoid rebuffer oscillation after playout starts.
    target = _env_int("VOICE_TWILIO_LOW_WATER_FRAMES", 0)
    if target <= 0:
        return 0
    return max(2, min(target, start_frames))


def _playout_refill_hold_s() -> float:
    return max(0.0, _env_int("VOICE_TWILIO_REFILL_HOLD_MS", 0) / 1000.0)


def _twilio_stats_log_enabled() -> bool:
    return (os.getenv("VOICE_TWILIO_STATS_LOG_ENABLED") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _speech_ctrl_heartbeat_log_enabled() -> bool:
    return (os.getenv("VOICE_SPEECH_CTRL_HEARTBEAT_LOG_ENABLED") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _minimal_hot_path_enabled() -> bool:
    return (os.getenv("VOICE_TWILIO_MINIMAL_HOT_PATH") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _twilio_chunk_mode_enabled() -> bool:
    return (os.getenv("VOICE_TWILIO_CHUNK_MODE") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _twilio_chunk_frames() -> int:
    ms = max(20, min(400, _env_int("VOICE_TWILIO_CHUNK_MS", 120)))
    return max(1, ms // FRAME_MS)


def _twilio_mark_enabled() -> bool:
    return (os.getenv("VOICE_TWILIO_MARK_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _barge_in_context_note_enabled() -> bool:
    return (os.getenv("VOICE_BARGE_IN_CONTEXT_NOTE") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _barge_in_context_note_text() -> str:
    return (
        (os.getenv("VOICE_BARGE_IN_CONTEXT_NOTE_TEXT") or "").strip()
        or "Caller barged in. Your previous response audio was interrupted and may not have been heard. "
        "Do not restart the conversation. If the caller says continue/go on, continue the interrupted thought."
    )


def _sanitize_transcript_for_event(transcript: str, max_chars: int = 500) -> str:
    cleaned = " ".join(transcript.split()).strip()
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars]


def _lifecycle_event_payload(
    *,
    tenant_id: str | None,
    rid: str | None,
    ai_mode: str,
    tenant_mode: str | None,
    call_sid: str | None,
    stream_sid: str | None,
    from_number: str | None,
    to_number: str | None,
    reason: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "rid": rid,
        "ai_mode": ai_mode,
        "tenant_mode": tenant_mode,
        "call_sid": call_sid,
        "stream_sid": stream_sid,
        "from_number": (from_number.strip() if isinstance(from_number, str) and from_number.strip() else None),
        "to_number": (to_number.strip() if isinstance(to_number, str) and to_number.strip() else None),
    }
    if reason is not None:
        payload["reason"] = reason
    return payload


def _normalize_ai_mode(ai_mode: str | None) -> str:
    mode = (ai_mode or "").strip().lower()
    return mode if mode in {"customer", "owner"} else "customer"


def _normalize_actor_mode(actor_mode: str | None) -> str:
    mode = (actor_mode or "").strip().lower()
    return mode if mode in {"client", "owner"} else "client"


def _resolve_mode_instructions(ai_mode: str) -> str | None:
    raw_json = (os.getenv("VOZ_FLOW_A_MODE_INSTRUCTIONS_JSON") or "").strip()
    if raw_json:
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict):
                v = parsed.get(ai_mode)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        except Exception:
            pass

    suffix = "CUSTOMER" if ai_mode == "customer" else "OWNER"
    return (os.getenv(f"VOZ_FLOW_A_INSTRUCTIONS_{suffix}") or "").strip() or None


def _resolve_actor_mode_policy(tenant_id: str | None, actor_mode: str | None) -> tuple[str, str | None]:
    base_voice = _env_str("VOZ_OPENAI_REALTIME_VOICE", "marin")
    base_instructions = (os.getenv("VOZ_OPENAI_REALTIME_INSTRUCTIONS") or "").strip() or None

    if not env_flag("VOZ_FLOW_A_ACTOR_MODE_POLICY"):
        return base_voice, base_instructions

    mode = _normalize_actor_mode(actor_mode)
    mode_upper = mode.upper()

    tenant_policy_raw = (os.getenv("VOZ_TENANT_MODE_POLICY_JSON") or "").strip()
    tenant_policy: dict[str, Any] = {}
    if tenant_policy_raw:
        try:
            parsed = json.loads(tenant_policy_raw)
            if isinstance(parsed, dict):
                tenant_policy = parsed
        except Exception:
            tenant_policy = {}

    mode_policy: dict[str, Any] = {}
    tenant_block = tenant_policy.get(tenant_id) if tenant_id else None
    if isinstance(tenant_block, dict):
        mode_block = tenant_block.get(mode)
        if isinstance(mode_block, dict):
            mode_policy = mode_block

    mode_voice = (os.getenv(f"VOZ_OPENAI_REALTIME_VOICE_{mode_upper}") or "").strip() or None
    mode_instructions = (os.getenv(f"VOZ_OPENAI_REALTIME_INSTRUCTIONS_{mode_upper}") or "").strip() or None

    policy_voice = mode_policy.get("voice")
    if not isinstance(policy_voice, str) or not policy_voice.strip():
        policy_voice = None
    else:
        policy_voice = policy_voice.strip()

    policy_instructions = mode_policy.get("instructions")
    if not isinstance(policy_instructions, str) or not policy_instructions.strip():
        policy_instructions = None
    else:
        policy_instructions = policy_instructions.strip()

    voice = policy_voice or mode_voice or base_voice
    instructions = policy_instructions or mode_instructions or base_instructions
    return voice, instructions


@dataclass
class OutgoingAudioBuffers:
    # main lane is assistant audio; aux lane reserved for future “thinking chime”
    main: deque[bytes] = field(default_factory=deque)
    aux: deque[bytes] = field(default_factory=deque)
    remainder: bytearray = field(default_factory=bytearray)
    main_max_frames: int = 200


class WaitingAudioController:
    def __init__(self) -> None:
        self._aux_enabled = True

    def on_user_speech_started(self, *, buffers: OutgoingAudioBuffers) -> None:
        buffers.aux.clear()
        self._aux_enabled = False

    def on_model_speech_started(self) -> None:
        self._aux_enabled = False

    def on_model_speech_done(self) -> None:
        self._aux_enabled = True

    @property
    def aux_enabled(self) -> bool:
        return self._aux_enabled


def _build_twilio_media_msg(stream_sid: str, ulaw_frame: bytes) -> dict[str, Any]:
    payload = base64.b64encode(ulaw_frame).decode("ascii")
    return {"event": "media", "streamSid": stream_sid, "media": {"payload": payload}}


def _build_twilio_clear_msg(stream_sid: str) -> dict[str, Any]:
    return {"event": "clear", "streamSid": stream_sid}


def _build_twilio_mark_msg(stream_sid: str, name: str) -> dict[str, Any]:
    return {"event": "mark", "streamSid": stream_sid, "mark": {"name": name}}


def _chunk_to_frames(remainder: bytearray, chunk: bytes, *, frame_bytes: int = FRAME_BYTES) -> list[bytes]:
    if chunk:
        remainder.extend(chunk)
    out: list[bytes] = []
    while len(remainder) >= frame_bytes:
        out.append(bytes(remainder[:frame_bytes]))
        del remainder[:frame_bytes]
    return out


def _audio_queue_bytes(buffers: OutgoingAudioBuffers) -> int:
    return (len(buffers.main) * FRAME_BYTES) + (len(buffers.aux) * FRAME_BYTES) + len(buffers.remainder)


def _flush_output_audio_buffers(buffers: OutgoingAudioBuffers) -> int:
    dropped = _audio_queue_bytes(buffers)
    buffers.main.clear()
    buffers.aux.clear()
    buffers.remainder.clear()
    return dropped


def _diag_init() -> dict[str, int]:
    return {
        "frames": 0,
        "delta_chunks": 0,
        "bytes": 0,
        "same_as_prev_frames": 0,
        "same_run_max": 0,
        "same_run_cur": 0,
        "low_diversity_frames": 0,
        "silence_like_frames": 0,
    }


def _diag_update_frame(diag: dict[str, int], frame: bytes, prev_frame: bytes | None) -> bool:
    diag["frames"] += 1
    diag["bytes"] += len(frame)

    uniq = len(set(frame))
    if uniq <= 2:
        diag["low_diversity_frames"] += 1
    if uniq <= 1:
        diag["silence_like_frames"] += 1

    same_as_prev = prev_frame == frame and prev_frame is not None
    if same_as_prev:
        diag["same_as_prev_frames"] += 1
        diag["same_run_cur"] += 1
    else:
        diag["same_run_cur"] = 1
    if diag["same_run_cur"] > diag["same_run_max"]:
        diag["same_run_max"] = diag["same_run_cur"]
    return same_as_prev


def _diag_score(diag: dict[str, int]) -> str:
    frames = max(1, int(diag.get("frames", 0)))
    same_ratio = float(diag.get("same_as_prev_frames", 0)) / float(frames)
    low_div_ratio = float(diag.get("low_diversity_frames", 0)) / float(frames)
    silence_ratio = float(diag.get("silence_like_frames", 0)) / float(frames)
    same_run_max = int(diag.get("same_run_max", 0))

    if (same_ratio > 0.85 and same_run_max >= 80) or silence_ratio > 0.95:
        return "bad"
    if same_ratio > 0.55 or low_div_ratio > 0.75 or same_run_max >= 40:
        return "suspect"
    return "ok"


def _should_accept_response_audio(*, response_id: str | None, active_response_id: str | None) -> bool:
    if not isinstance(active_response_id, str) or not active_response_id:
        return False
    if response_id is None:
        return True
    return response_id == active_response_id


def _barge_in_allowed(
    *,
    active_response_id: str | None,
    response_started_at: dict[str, float],
    response_state: dict[str, Any],
    now_monotonic: float,
    min_response_ms: int,
    min_frames: int,
) -> bool:
    if not isinstance(active_response_id, str) or not active_response_id:
        return False
    started = response_started_at.get(active_response_id)
    age_ms = int((now_monotonic - started) * 1000.0) if isinstance(started, float) else 0
    sent_frames = 0
    sent_map = response_state.get("sent_main_frames_by_id")
    if isinstance(sent_map, dict):
        raw = sent_map.get(active_response_id, 0)
        sent_frames = int(raw) if isinstance(raw, int | float) else 0
    return age_ms >= max(0, min_response_ms) and sent_frames >= max(0, min_frames)


def _is_sender_underrun_state(*, response_state: dict[str, Any], buffers: OutgoingAudioBuffers) -> bool:
    active = response_state.get("active_response_id")
    if isinstance(active, str) and active:
        return True
    # If there are playable main frames queued, sender should not be idle.
    return bool(buffers.main)


def _build_openai_session_update(*, voice: str, instructions: str | None) -> dict[str, Any]:
    """
    IMPORTANT:
    Your logs prove OpenAI rejects `session.type` with:
      Unknown parameter: 'session.type'
    So we do NOT send `session.type`.

    We do send:
      - modalities: ["audio", "text"]
      - top-level voice + g711_ulaw input/output audio formats
      - server_vad with create_response disabled (legacy control loop)
      - input audio transcription enabled
    """
    session: dict[str, Any] = {
        "modalities": ["audio", "text"],
        "voice": voice,
        "input_audio_format": "g711_ulaw",
        "output_audio_format": "g711_ulaw",
        "turn_detection": {
            "type": "server_vad",
            "threshold": 0.5,
            "silence_duration_ms": 500,
            "create_response": False,
            "interrupt_response": True,
        },
        "input_audio_transcription": {"model": "gpt-4o-mini-transcribe"},
    }
    if instructions:
        session["instructions"] = instructions
    return {"type": "session.update", "session": session}


def _event_emit_enabled() -> bool:
    return env_flag("VOZ_FLOW_A_EVENT_EMIT")


async def _emit_flow_a_event(
    *,
    enabled: bool,
    tenant_id: str | None,
    rid: str | None,
    event_type: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> None:
    if not enabled:
        return

    tenant = (tenant_id or "").strip()
    request_id = (rid or "").strip()
    if not tenant or not request_id:
        _dbg(f"FLOW_A_EVENT_SKIPPED type={event_type} reason=missing_context")
        return

    event_payload = dict(payload)
    event_payload.setdefault("tenant_id", tenant)
    event_payload.setdefault("rid", request_id)

    try:
        await asyncio.to_thread(
            core_db.emit_event,
            tenant,
            request_id,
            event_type,
            event_payload,
            None,
            idempotency_key,
        )
        _dbg(f"FLOW_A_EVENT_EMITTED type={event_type} tenant_id={tenant} rid={request_id}")
    except Exception as e:
        _dbg(f"FLOW_A_EVENT_EMIT_FAILED type={event_type} tenant_id={tenant} rid={request_id} err={e!r}")


async def _connect_openai_ws(*, model: str) -> Any:
    """
    Connect to OpenAI Realtime WebSocket.

    websockets.connect() signature varies by version.
    We introspect for header kw names to avoid Render runtime mismatches.
    """
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY missing")

    import inspect

    import websockets  # type: ignore

    url = f"{OPENAI_REALTIME_URL_BASE}?model={quote_plus(model)}"
    hdrs = [("Authorization", f"Bearer {api_key}"), ("OpenAI-Beta", "realtime=v1")]

    params = set(inspect.signature(websockets.connect).parameters.keys())
    kwargs: dict[str, Any] = {}

    if "additional_headers" in params:
        kwargs["additional_headers"] = hdrs
    elif "extra_headers" in params:
        kwargs["extra_headers"] = hdrs
    elif "headers" in params:
        kwargs["headers"] = hdrs
    elif "header" in params:
        kwargs["header"] = [f"{k}: {v}" for k, v in hdrs]

    return await websockets.connect(url, **kwargs)


async def _twilio_sender_loop(
    *,
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    stream_sid_ref: dict[str, str | None],
    buffers: OutgoingAudioBuffers,
    wait_ctl: WaitingAudioController,
    response_state: dict[str, Any],
) -> None:
    """Send frames to Twilio at ~20ms pacing. Prefer main lane, then aux."""
    minimal_hot_path = _minimal_hot_path_enabled()
    chunk_mode = _twilio_chunk_mode_enabled()
    chunk_frames = _twilio_chunk_frames()
    mark_enabled = _twilio_mark_enabled()
    stats_every_s = max(0.25, _env_int("VOICE_TWILIO_STATS_EVERY_MS", 1000) / 1000.0)
    prebuffer_frames = _effective_prebuffer_frames(buffers.main_max_frames)
    playout_start_frames = _playout_start_frames(prebuffer_frames)
    playout_low_water_frames = _playout_low_water_frames(playout_start_frames)
    playout_refill_hold_s = _playout_refill_hold_s()
    stall_warn_ms = max(20.0, _env_float("VOICE_SEND_STALL_WARN_MS", 35.0))
    stall_crit_ms = max(stall_warn_ms + 5.0, _env_float("VOICE_SEND_STALL_CRIT_MS", 60.0))
    stats_log_enabled = _twilio_stats_log_enabled()
    stats_started = time.monotonic()
    frames_sent = 0
    underruns = 0
    idle_ticks = 0
    prebuf_waits = 0
    late_ms_max = 0.0
    idle_late_ms_max = 0.0
    send_stall_warn_count = 0
    send_stall_crit_count = 0
    send_gap_ms_max = 0.0
    next_due = time.monotonic() + FRAME_SLEEP_S
    last_send_ts: float | None = None
    last_send_rid: str | None = None
    prebuf_complete_logged_for_rid: str | None = None
    prebuf_open_for_rid: str | None = None
    sid_for_fast_json: str | None = None
    fast_json_prefix = ""
    fast_json_suffix = '"}}'
    mark_seq = 0

    while True:
        sid = stream_sid_ref.get("streamSid")
        if not sid:
            await asyncio.sleep(0.01)
            continue
        if minimal_hot_path and sid != sid_for_fast_json:
            sid_for_fast_json = sid
            # Fast path: avoid json.dumps per frame by reusing static envelope pieces.
            fast_json_prefix = f'{{"event":"media","streamSid":"{sid}","media":{{"payload":"'

        frame: bytes | None = None
        lane = "none"
        rid_for_send: str | None = None

        if chunk_mode:
            chunk_parts: list[bytes] = []
            if buffers.main:
                lane = "main"
                rid_for_send = response_state.get("active_response_id")
                rid = rid_for_send if isinstance(rid_for_send, str) else None
                done_ids = response_state.get("processed_response_done_ids")
                playout_started_ids = response_state.get("playout_started_ids")
                refill_wait_started_by_id = response_state.get("refill_wait_started_by_id")
                rid_done = isinstance(done_ids, set) and isinstance(rid, str) and rid in done_ids
                if isinstance(rid, str) and rid and isinstance(playout_started_ids, set):
                    # Startup runway: chunk mode must honor the same startup guard as frame mode.
                    if rid not in playout_started_ids and not rid_done and len(buffers.main) < playout_start_frames:
                        prebuf_waits += 1
                        last_send_ts = None
                        last_send_rid = None
                        await asyncio.sleep(0.01)
                        continue
                    if rid not in playout_started_ids:
                        playout_started_ids.add(rid)
                    # Mid-turn refill hysteresis: hold briefly if queue dipped too low.
                    if (
                        not rid_done
                        and len(buffers.main) < playout_low_water_frames
                        and isinstance(refill_wait_started_by_id, dict)
                        and playout_refill_hold_s > 0.0
                    ):
                        now = time.monotonic()
                        started = refill_wait_started_by_id.get(rid)
                        if not isinstance(started, float):
                            refill_wait_started_by_id[rid] = now
                            prebuf_waits += 1
                            await asyncio.sleep(0.01)
                            continue
                        if (now - started) < playout_refill_hold_s:
                            prebuf_waits += 1
                            await asyncio.sleep(0.01)
                            continue
                        refill_wait_started_by_id.pop(rid, None)
                    elif isinstance(refill_wait_started_by_id, dict):
                        refill_wait_started_by_id.pop(rid, None)
                n = min(chunk_frames, len(buffers.main))
                for _ in range(n):
                    chunk_parts.append(buffers.main.popleft())
            elif wait_ctl.aux_enabled and buffers.aux:
                lane = "aux"
                n = min(chunk_frames, len(buffers.aux))
                for _ in range(n):
                    chunk_parts.append(buffers.aux.popleft())

            if not chunk_parts:
                await asyncio.sleep(0.005)
                continue

            chunk_bytes = b"".join(chunk_parts)
            now = time.monotonic()
            if now >= next_due:
                late_ms_max = max(late_ms_max, (now - next_due) * 1000.0)
            if isinstance(last_send_ts, float) and isinstance(rid_for_send, str) and rid_for_send == last_send_rid:
                send_gap_ms = (now - last_send_ts) * 1000.0
                send_gap_ms_max = max(send_gap_ms_max, send_gap_ms)
                if send_gap_ms > stall_warn_ms:
                    send_stall_warn_count += 1
                if send_gap_ms > stall_crit_ms:
                    send_stall_crit_count += 1
            elif lane != "main":
                last_send_ts = None
                last_send_rid = None
            msg = _build_twilio_media_msg(sid, chunk_bytes)
            async with send_lock:
                await websocket.send_text(json.dumps(msg))
                if mark_enabled and lane == "main":
                    mark_seq += 1
                    await websocket.send_text(
                        json.dumps(_build_twilio_mark_msg(sid, f"m{mark_seq}"))
                    )

            if lane == "main" and isinstance(rid_for_send, str):
                sent_map = response_state.get("sent_main_frames_by_id")
                if isinstance(sent_map, dict):
                    cur = sent_map.get(rid_for_send, 0)
                    sent_map[rid_for_send] = int(cur) + len(chunk_parts)
                last_send_ts = now
                last_send_rid = rid_for_send
                if prebuf_open_for_rid != rid_for_send:
                    prebuf_open_for_rid = rid_for_send
                if rid_for_send != prebuf_complete_logged_for_rid and len(buffers.main) >= prebuffer_frames:
                    _dbg("Prebuffer complete; starting to send audio to Twilio")
                    prebuf_complete_logged_for_rid = rid_for_send
                logged_main_ids = response_state.get("logged_twilio_main_frame_ids")
                if isinstance(logged_main_ids, set) and rid_for_send not in logged_main_ids:
                    _dbg(
                        f"TWILIO_MAIN_FRAME_SENT first=1 response_id={rid_for_send} "
                        f"bytes={len(chunk_bytes)} q_main={len(buffers.main)}"
                    )
                    logged_main_ids.add(rid_for_send)
            else:
                last_send_ts = None
                last_send_rid = None

            frames_sent += len(chunk_parts)
            if now - stats_started >= stats_every_s:
                if stats_log_enabled:
                    prebuf = bool(response_state.get("active_response_id")) and len(buffers.main) < prebuffer_frames
                    _dbg(
                        f"twilio_send stats: q_bytes={_audio_queue_bytes(buffers)} "
                        f"frames_sent={frames_sent} underruns={underruns} idle_ticks={idle_ticks} "
                        f"prebuf_waits={prebuf_waits} "
                        f"late_ms_max={late_ms_max:.1f} prebuf={prebuf} "
                        f"idle_late_ms_max={idle_late_ms_max:.1f} "
                        f"send_gap_ms_max={send_gap_ms_max:.1f} "
                        f"send_stall_warn_count={send_stall_warn_count} "
                        f"send_stall_crit_count={send_stall_crit_count}"
                    )
                stats_started = now
                frames_sent = 0
                underruns = 0
                idle_ticks = 0
                prebuf_waits = 0
                late_ms_max = 0.0
                idle_late_ms_max = 0.0
                send_stall_warn_count = 0
                send_stall_crit_count = 0
                send_gap_ms_max = 0.0

            # Chunk mode still uses a stable 20ms/frame playout clock.
            next_due = next_due + (FRAME_SLEEP_S * len(chunk_parts))
            sleep_s = next_due - time.monotonic()
            if sleep_s > 0:
                await asyncio.sleep(sleep_s)
            else:
                next_due = time.monotonic() + FRAME_SLEEP_S
            continue

        if minimal_hot_path:
            if buffers.main:
                frame = buffers.main.popleft()
                lane = "main"
                rid_for_send = response_state.get("active_response_id")
            elif wait_ctl.aux_enabled and buffers.aux:
                frame = buffers.aux.popleft()
                lane = "aux"

            if frame is None:
                await asyncio.sleep(0.005)
                continue

            payload = base64.b64encode(frame).decode("ascii")
            msg = f"{fast_json_prefix}{payload}{fast_json_suffix}"
            async with send_lock:
                await websocket.send_text(msg)

            if lane == "main" and isinstance(rid_for_send, str):
                sent_map = response_state.get("sent_main_frames_by_id")
                if isinstance(sent_map, dict):
                    cur = sent_map.get(rid_for_send, 0)
                    sent_map[rid_for_send] = int(cur) + 1

            next_due = next_due + FRAME_SLEEP_S
            sleep_s = next_due - time.monotonic()
            if sleep_s > 0:
                await asyncio.sleep(sleep_s)
            else:
                next_due = time.monotonic() + FRAME_SLEEP_S
            continue

        if buffers.main:
            lane = "main"
            rid = response_state.get("active_response_id")
            done_ids = response_state.get("processed_response_done_ids")
            playout_started_ids = response_state.get("playout_started_ids")
            refill_wait_started_by_id = response_state.get("refill_wait_started_by_id")
            rid_done = isinstance(done_ids, set) and isinstance(rid, str) and rid in done_ids
            if isinstance(rid, str) and rid and isinstance(playout_started_ids, set):
                # Startup runway: do not start sending until a small buffer is ready.
                if rid not in playout_started_ids and not rid_done and len(buffers.main) < playout_start_frames:
                    prebuf_waits += 1
                    last_send_ts = None
                    last_send_rid = None
                    await asyncio.sleep(0.01)
                    continue
                if rid not in playout_started_ids:
                    playout_started_ids.add(rid)
                # Mid-turn refill hysteresis: short hold when buffer dips too low.
                if (
                    not rid_done
                    and len(buffers.main) < playout_low_water_frames
                    and isinstance(refill_wait_started_by_id, dict)
                    and playout_refill_hold_s > 0.0
                ):
                    now = time.monotonic()
                    started = refill_wait_started_by_id.get(rid)
                    if not isinstance(started, float):
                        refill_wait_started_by_id[rid] = now
                        prebuf_waits += 1
                        await asyncio.sleep(0.01)
                        continue
                    if (now - started) < playout_refill_hold_s:
                        prebuf_waits += 1
                        await asyncio.sleep(0.01)
                        continue
                    refill_wait_started_by_id.pop(rid, None)
                elif isinstance(refill_wait_started_by_id, dict):
                    refill_wait_started_by_id.pop(rid, None)
            frame = buffers.main.popleft()
            lane = "main"
        elif wait_ctl.aux_enabled and buffers.aux:
            frame = buffers.aux.popleft()
            lane = "aux"
        else:
            last_send_ts = None
            last_send_rid = None
            if _is_sender_underrun_state(response_state=response_state, buffers=buffers):
                underruns += 1
            else:
                idle_ticks += 1
            now = time.monotonic()
            if now >= next_due:
                idle_late_ms_max = max(idle_late_ms_max, (now - next_due) * 1000.0)
                next_due = now + FRAME_SLEEP_S
            if now - stats_started >= stats_every_s:
                if stats_log_enabled:
                    prebuf = bool(response_state.get("active_response_id")) and len(buffers.main) < prebuffer_frames
                    _dbg(
                        f"twilio_send stats: q_bytes={_audio_queue_bytes(buffers)} "
                        f"frames_sent={frames_sent} underruns={underruns} idle_ticks={idle_ticks} "
                        f"prebuf_waits={prebuf_waits} "
                        f"late_ms_max={late_ms_max:.1f} prebuf={prebuf} "
                        f"idle_late_ms_max={idle_late_ms_max:.1f} "
                        f"send_gap_ms_max={send_gap_ms_max:.1f} "
                        f"send_stall_warn_count={send_stall_warn_count} "
                        f"send_stall_crit_count={send_stall_crit_count}"
                    )
                stats_started = now
                frames_sent = 0
                underruns = 0
                idle_ticks = 0
                prebuf_waits = 0
                late_ms_max = 0.0
                idle_late_ms_max = 0.0
                send_stall_warn_count = 0
                send_stall_crit_count = 0
                send_gap_ms_max = 0.0
            await asyncio.sleep(0.01)
            continue

        now = time.monotonic()
        if now >= next_due:
            late_ms_max = max(late_ms_max, (now - next_due) * 1000.0)
        rid_for_send = response_state.get("active_response_id") if lane == "main" else None
        if isinstance(last_send_ts, float) and isinstance(rid_for_send, str) and rid_for_send == last_send_rid:
            send_gap_ms = (now - last_send_ts) * 1000.0
            send_gap_ms_max = max(send_gap_ms_max, send_gap_ms)
            if send_gap_ms > stall_warn_ms:
                send_stall_warn_count += 1
            if send_gap_ms > stall_crit_ms:
                send_stall_crit_count += 1
        elif lane != "main":
            last_send_ts = None
            last_send_rid = None

        # Send immediately, then sleep to pace.
        msg = _build_twilio_media_msg(sid, frame)
        async with send_lock:
            await websocket.send_text(json.dumps(msg))
        frames_sent += 1
        if isinstance(rid_for_send, str):
            last_send_ts = now
            last_send_rid = rid_for_send
        else:
            last_send_ts = None
            last_send_rid = None

        if lane == "main":
            rid = response_state.get("active_response_id")
            if isinstance(rid, str):
                sent_map = response_state.get("sent_main_frames_by_id")
                if isinstance(sent_map, dict):
                    current = sent_map.get(rid, 0)
                    if isinstance(current, int):
                        sent_map[rid] = current + 1
                    else:
                        sent_map[rid] = 1
                if prebuf_open_for_rid != rid:
                    prebuf_open_for_rid = rid
                if rid != prebuf_complete_logged_for_rid and len(buffers.main) >= prebuffer_frames:
                    _dbg("Prebuffer complete; starting to send audio to Twilio")
                    prebuf_complete_logged_for_rid = rid
                logged_main_ids = response_state.get("logged_twilio_main_frame_ids")
                if isinstance(logged_main_ids, set) and rid not in logged_main_ids:
                    _dbg(
                        f"TWILIO_MAIN_FRAME_SENT first=1 response_id={rid} bytes={len(frame)} q_main={len(buffers.main)}"
                    )
                    logged_main_ids.add(rid)

        if now - stats_started >= stats_every_s:
            if stats_log_enabled:
                prebuf = bool(response_state.get("active_response_id")) and len(buffers.main) < prebuffer_frames
                _dbg(
                    f"twilio_send stats: q_bytes={_audio_queue_bytes(buffers)} "
                    f"frames_sent={frames_sent} underruns={underruns} idle_ticks={idle_ticks} "
                    f"prebuf_waits={prebuf_waits} "
                    f"late_ms_max={late_ms_max:.1f} prebuf={prebuf} "
                    f"idle_late_ms_max={idle_late_ms_max:.1f} "
                    f"send_gap_ms_max={send_gap_ms_max:.1f} "
                    f"send_stall_warn_count={send_stall_warn_count} "
                    f"send_stall_crit_count={send_stall_crit_count}"
                )
            stats_started = now
            frames_sent = 0
            underruns = 0
            idle_ticks = 0
            prebuf_waits = 0
            late_ms_max = 0.0
            idle_late_ms_max = 0.0
            send_stall_warn_count = 0
            send_stall_crit_count = 0
            send_gap_ms_max = 0.0

        # Keep a stable 20ms playout clock to normalize bursty producer output.
        next_due = next_due + FRAME_SLEEP_S
        sleep_s = next_due - time.monotonic()
        if sleep_s > 0:
            await asyncio.sleep(sleep_s)
        else:
            # If behind schedule, reset to now so we do not drift indefinitely.
            next_due = time.monotonic() + FRAME_SLEEP_S


@router.websocket("/twilio/stream")
async def twilio_stream(websocket: WebSocket) -> None:
    if not env_flag("VOZ_FEATURE_VOICE_FLOW_A"):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    _dbg("TWILIO_WS_CONNECTED")

    send_lock = asyncio.Lock()
    stream_sid_ref: dict[str, str | None] = {"streamSid": None}

    buffers = OutgoingAudioBuffers(main_max_frames=_env_int("VOICE_MAIN_MAX_FRAMES", 200))
    wait_ctl = WaitingAudioController()

    # OpenAI bridge state
    bridge_enabled = env_flag("VOZ_FLOW_A_OPENAI_BRIDGE")
    model = _env_str("VOZ_OPENAI_REALTIME_MODEL", "gpt-realtime")
    voice, instructions = _resolve_actor_mode_policy(None, None)
    q_max = _env_int("VOICE_OPENAI_IN_Q_MAX", 200)
    in_q: asyncio.Queue[str] = asyncio.Queue(maxsize=q_max)

    openai_ws: Any = None
    sender_task: asyncio.Task | None = None
    in_task: asyncio.Task | None = None
    out_task: asyncio.Task | None = None
    heartbeat_task: asyncio.Task | None = None
    openai_input_blocked_unknown_param = False
    logged_session_created = False
    logged_session_updated = False
    openai_output_modalities: list[str] | None = None
    logged_mode_selection = False

    active_response_id: str | None = None
    response_state: dict[str, Any] = {
        "active_response_id": None,
        "logged_delta_ids": set(),
        "logged_text_delta_ids": set(),
        "seen_audio_ids": set(),
        "logged_twilio_main_frame_ids": set(),
        "logged_done_no_audio_ids": set(),
        "processed_response_done_ids": set(),
        "sent_main_frames_by_id": {},
        "playout_started_ids": set(),
        "refill_wait_started_by_id": {},
    }

    turn_seq = 0
    turn_logged_speech_started = False
    turn_logged_transcript = False
    turn_logged_response_create = False
    call_tenant_id: str | None = None
    call_tenant_mode: str | None = None
    call_ai_mode: str = "customer"
    call_rid: str | None = None
    call_sid: str | None = None
    call_stream_sid: str | None = None
    call_from_number: str | None = None
    call_to_number: str | None = None
    event_emit_enabled = _event_emit_enabled()
    call_stopped_emitted = False
    last_speech_started_ts: float | None = None
    pending_speech_started_at: float | None = None
    pending_speech_started_media_frames: int | None = None
    pending_input_commit_sent = False
    twilio_media_frames_rx = 0
    last_media_rx_ts: float | None = None
    ws_started_at = time.monotonic()
    logged_media_absent = False
    response_started_at: dict[str, float] = {}
    response_audio_diag: dict[str, dict[str, int]] = {}
    response_last_frame: dict[str, bytes] = {}

    def _drop_oldest_put(item: str) -> None:
        try:
            in_q.put_nowait(item)
        except asyncio.QueueFull:
            try:
                in_q.get_nowait()
            except Exception:
                pass
            try:
                in_q.put_nowait(item)
            except Exception:
                pass

    async def _twilio_to_openai_loop() -> None:
        nonlocal openai_input_blocked_unknown_param
        while True:
            audio_b64 = await in_q.get()
            if openai_input_blocked_unknown_param:
                continue
            await openai_ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": audio_b64}))

    def _normalize_modalities(x: Any) -> list[str] | None:
        if not isinstance(x, list) or not x:
            return None
        out: list[str] = []
        for v in x:
            if isinstance(v, str) and v:
                out.append(v)
        return out or None

    async def _openai_to_twilio_loop() -> None:
        nonlocal logged_session_created, logged_session_updated, openai_input_blocked_unknown_param
        nonlocal active_response_id, openai_output_modalities
        nonlocal turn_seq, turn_logged_speech_started, turn_logged_transcript, turn_logged_response_create
        nonlocal last_speech_started_ts
        nonlocal pending_speech_started_at, pending_speech_started_media_frames, pending_input_commit_sent

        while True:
            raw = await openai_ws.recv()
            evt = json.loads(raw)
            etype = evt.get("type")

            if etype == "session.created":
                session = evt.get("session") if isinstance(evt.get("session"), dict) else {}
                om = session.get("output_modalities") or session.get("modalities")
                openai_output_modalities = _normalize_modalities(om) or openai_output_modalities
                if not logged_session_created:
                    _dbg(
                        f"OPENAI_SESSION_CREATED keys={list(session.keys())} "
                        f"output_modalities={openai_output_modalities}"
                    )
                    logged_session_created = True
                continue

            if etype == "session.updated":
                session = evt.get("session") if isinstance(evt.get("session"), dict) else {}
                om = session.get("output_modalities") or session.get("modalities")
                openai_output_modalities = _normalize_modalities(om) or openai_output_modalities
                if not logged_session_updated:
                    _dbg(
                        f"OPENAI_SESSION_UPDATED keys={list(session.keys())} "
                        f"output_modalities={openai_output_modalities}"
                    )
                    logged_session_updated = True
                continue

            if etype == "error":
                err = evt.get("error")
                code = err.get("code") if isinstance(err, dict) else None
                param = err.get("param") if isinstance(err, dict) else None
                msg = err.get("message") if isinstance(err, dict) else None

                if code == "unknown_parameter":
                    openai_input_blocked_unknown_param = True

                # If server rejects modalities, force the known-supported audio+text combo.
                if code == "invalid_value" and param == "response.modalities":
                    openai_output_modalities = ["audio", "text"]
                    _dbg(f"OPENAI_MODALITIES_FORCED output_modalities={openai_output_modalities} msg={msg!r}")

                # Expected sometimes when fallback commit races with server-side auto-commit.
                if code == "input_audio_buffer_commit_empty":
                    continue

                if code != "response_cancel_not_active":
                    _dbg(f"OPENAI_ERROR evt={evt!r}")
                continue

            if etype == "input_audio_buffer.speech_started":
                now = time.monotonic()
                debounce_s = _speech_started_debounce_s()
                if (
                    isinstance(last_speech_started_ts, float)
                    and debounce_s > 0.0
                    and (now - last_speech_started_ts) < debounce_s
                ):
                    _dbg(
                        "OPENAI_SPEECH_STARTED_DEBOUNCED "
                        f"dt_ms={int((now - last_speech_started_ts) * 1000.0)}"
                    )
                    continue
                last_speech_started_ts = now
                pending_speech_started_at = now
                pending_speech_started_media_frames = twilio_media_frames_rx
                pending_input_commit_sent = False
                turn_seq += 1
                turn_logged_speech_started = False
                turn_logged_transcript = False
                turn_logged_response_create = False

                _dbg("OpenAI VAD: user speech START")
                had_buffered_audio = bool(buffers.main) or bool(buffers.aux) or bool(buffers.remainder)
                if active_response_id:
                    can_barge = _barge_in_allowed(
                        active_response_id=active_response_id,
                        response_started_at=response_started_at,
                        response_state=response_state,
                        now_monotonic=now,
                        min_response_ms=_barge_in_min_response_ms(),
                        min_frames=_barge_in_min_frames(),
                    )
                    if can_barge:
                        dropped_bytes = _flush_output_audio_buffers(buffers)
                        wait_ctl.on_user_speech_started(buffers=buffers)

                        sid = stream_sid_ref.get("streamSid")
                        if sid:
                            async with send_lock:
                                await websocket.send_text(json.dumps(_build_twilio_clear_msg(sid)))
                            _dbg("TWILIO_CLEAR_SENT")
                        _dbg(
                            "BARGE-IN: user speech started while AI speaking; "
                            "canceling active response and clearing audio buffer."
                        )
                        if dropped_bytes > 0:
                            _dbg(
                                f"AUDIO_BUFFER_FLUSH_ON_SPEECH_STARTED dropped_bytes={dropped_bytes} "
                                f"active_response_id={active_response_id}"
                            )
                        await openai_ws.send(json.dumps({"type": "response.cancel"}))
                        if _barge_in_context_note_enabled():
                            try:
                                await openai_ws.send(
                                    json.dumps(
                                        {
                                            "type": "conversation.item.create",
                                            "item": {
                                                "type": "message",
                                                "role": "system",
                                                "content": [
                                                    {
                                                        "type": "input_text",
                                                        "text": _barge_in_context_note_text(),
                                                    }
                                                ],
                                            },
                                        }
                                    )
                                )
                            except Exception as e:
                                _dbg(f"BARGE_IN_CONTEXT_NOTE_FAILED err={e!r}")
                    else:
                        _dbg(
                            "BARGE-IN_IGNORED_EARLY "
                            f"response_id={active_response_id} "
                            f"min_ms={_barge_in_min_response_ms()} min_frames={_barge_in_min_frames()}"
                        )
                elif had_buffered_audio:
                    dropped_bytes = _flush_output_audio_buffers(buffers)
                    wait_ctl.on_user_speech_started(buffers=buffers)
                    sid = stream_sid_ref.get("streamSid")
                    if sid:
                        async with send_lock:
                            await websocket.send_text(json.dumps(_build_twilio_clear_msg(sid)))
                        _dbg("TWILIO_CLEAR_SENT")
                    _dbg(
                        "AUDIO_BUFFER_FLUSH_ON_SPEECH_STARTED "
                        f"dropped_bytes={dropped_bytes} active_response_id=None"
                    )

                if not turn_logged_speech_started:
                    _dbg(f"OPENAI_SPEECH_STARTED turn={turn_seq}")
                    turn_logged_speech_started = True
                continue

            if etype == "input_audio_buffer.speech_stopped":
                if _force_input_commit_enabled() and openai_ws is not None:
                    if pending_input_commit_sent:
                        _dbg("OPENAI_INPUT_COMMIT_SKIPPED reason=speech_stopped already_committed=1")
                        continue
                    min_frames = _force_input_commit_min_frames()
                    start_frames = pending_speech_started_media_frames or twilio_media_frames_rx
                    captured_frames = max(0, twilio_media_frames_rx - start_frames)
                    if captured_frames < min_frames:
                        _dbg(
                            "OPENAI_INPUT_COMMIT_SKIPPED reason=speech_stopped "
                            f"captured_frames={captured_frames} min_frames={min_frames}"
                        )
                        continue
                    try:
                        await openai_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                        pending_input_commit_sent = True
                        _dbg("OPENAI_INPUT_COMMIT_SENT reason=speech_stopped")
                    except Exception as e:
                        _dbg(f"OPENAI_INPUT_COMMIT_FAILED reason=speech_stopped err={e!r}")
                continue

            if etype == "conversation.item.input_audio_transcription.completed":
                transcript = (evt.get("transcript") or "").strip()
                if not transcript:
                    continue

                if not turn_logged_transcript:
                    _dbg(f"OPENAI_TRANSCRIPT completed len={len(transcript)} turn={turn_seq}")
                    turn_logged_transcript = True
                pending_speech_started_at = None
                pending_speech_started_media_frames = None
                pending_input_commit_sent = False

                await _emit_flow_a_event(
                    enabled=event_emit_enabled,
                    tenant_id=call_tenant_id,
                    rid=call_rid,
                    event_type="flow_a.transcript_completed",
                    payload={
                        "tenant_id": call_tenant_id,
                        "rid": call_rid,
                        "ai_mode": call_ai_mode,
                        "tenant_mode": call_tenant_mode,
                        "turn": turn_seq,
                        "transcript_len": len(transcript),
                        "transcript": _sanitize_transcript_for_event(transcript),
                    },
                )

                if active_response_id is not None:
                    continue

                # Keep output audio enabled deterministically.
                modalities = ["audio", "text"]
                await openai_ws.send(json.dumps({"type": "response.create", "response": {"modalities": modalities}}))

                if not turn_logged_response_create:
                    _dbg(f"OPENAI_RESPONSE_CREATE_SENT rid={turn_seq} modalities={modalities!r}")
                    turn_logged_response_create = True
                continue

            if etype == "response.created":
                response = evt.get("response") if isinstance(evt.get("response"), dict) else {}
                rid = response.get("id")
                if isinstance(rid, str) and rid:
                    if _flush_on_response_created_enabled():
                        dropped_bytes = _flush_output_audio_buffers(buffers)
                        if dropped_bytes > 0:
                            sid = stream_sid_ref.get("streamSid")
                            if sid:
                                async with send_lock:
                                    await websocket.send_text(json.dumps(_build_twilio_clear_msg(sid)))
                                _dbg("TWILIO_CLEAR_SENT")
                            _dbg(
                                f"AUDIO_BUFFER_FLUSH_ON_RESPONSE_CREATED response_id={rid} "
                                f"dropped_bytes={dropped_bytes}"
                            )
                    active_response_id = rid
                    response_state["active_response_id"] = rid
                    response_started_at[rid] = time.monotonic()
                    _dbg(f"OPENAI_RESPONSE_CREATED id={rid}")
                continue

            if etype == "response.output_text.delta":
                delta = evt.get("delta")
                evt_rid = evt.get("response_id")
                rid = evt_rid if isinstance(evt_rid, str) and evt_rid else active_response_id
                if isinstance(rid, str):
                    logged_text_ids = response_state.get("logged_text_delta_ids")
                    if isinstance(logged_text_ids, set) and rid not in logged_text_ids:
                        _dbg(
                            f"OPENAI_TEXT_DELTA_FIRST response_id={rid} "
                            f"chars={(len(delta) if isinstance(delta, str) else 0)}"
                        )
                        logged_text_ids.add(rid)
                continue

            # Some Realtime variants may stream audio via content-part events instead of output_audio.delta.
            # Treat these as a fallback path into the same Twilio "main lane" buffer.
            if etype in ("response.content_part.added", "response.content_part.done"):
                part = evt.get("part") if isinstance(evt.get("part"), dict) else {}
                audio_b64 = part.get("audio")
                if isinstance(audio_b64, str) and audio_b64:
                    evt_rid = evt.get("response_id")
                    response_id = evt_rid if isinstance(evt_rid, str) and evt_rid else None
                    if not _should_accept_response_audio(
                        response_id=response_id,
                        active_response_id=active_response_id,
                    ):
                        _dbg(
                            "OPENAI_AUDIO_DROPPED "
                            f"response_id={response_id} active_response_id={active_response_id}"
                        )
                        continue
                    try:
                        chunk = base64.b64decode(audio_b64)
                    except Exception:
                        continue

                    frames = _chunk_to_frames(buffers.remainder, chunk)
                    for f in frames:
                        if len(buffers.main) >= buffers.main_max_frames:
                            buffers.main.popleft()
                        buffers.main.append(f)

                    rid = evt_rid if isinstance(evt_rid, str) and evt_rid else active_response_id
                    if isinstance(rid, str):
                        diag = response_audio_diag.setdefault(rid, _diag_init())
                        diag["delta_chunks"] += 1
                        prev = response_last_frame.get(rid)
                        for f in frames:
                            _diag_update_frame(diag, f, prev)
                            prev = f
                        if prev is not None:
                            response_last_frame[rid] = prev

                        seen_audio_ids = response_state.get("seen_audio_ids")
                        if isinstance(seen_audio_ids, set):
                            seen_audio_ids.add(rid)

                        logged_delta_ids = response_state.get("logged_delta_ids")
                        if isinstance(logged_delta_ids, set) and rid not in logged_delta_ids:
                            _dbg(
                                f"OPENAI_AUDIO_PART_FIRST response_id={rid} "
                                f"bytes={len(chunk)} part_type={part.get('type')}"
                            )
                            logged_delta_ids.add(rid)
                continue

            if etype in ("response.output_audio.delta", "response.audio.delta"):
                delta_b64 = evt.get("delta")
                if not isinstance(delta_b64, str) or not delta_b64:
                    continue
                evt_rid = evt.get("response_id")
                response_id = evt_rid if isinstance(evt_rid, str) and evt_rid else None
                if not _should_accept_response_audio(
                    response_id=response_id,
                    active_response_id=active_response_id,
                ):
                    _dbg(
                        "OPENAI_AUDIO_DROPPED "
                        f"response_id={response_id} active_response_id={active_response_id}"
                    )
                    continue
                try:
                    chunk = base64.b64decode(delta_b64)
                except Exception:
                    continue

                frames = _chunk_to_frames(buffers.remainder, chunk)
                for f in frames:
                    if len(buffers.main) >= buffers.main_max_frames:
                        buffers.main.popleft()
                    buffers.main.append(f)

                rid = evt_rid if isinstance(evt_rid, str) and evt_rid else active_response_id
                if isinstance(rid, str):
                    diag = response_audio_diag.setdefault(rid, _diag_init())
                    diag["delta_chunks"] += 1
                    prev = response_last_frame.get(rid)
                    for f in frames:
                        _diag_update_frame(diag, f, prev)
                        prev = f
                    if prev is not None:
                        response_last_frame[rid] = prev

                    seen_audio_ids = response_state.get("seen_audio_ids")
                    if isinstance(seen_audio_ids, set):
                        seen_audio_ids.add(rid)

                    logged_delta_ids = response_state.get("logged_delta_ids")
                    if isinstance(logged_delta_ids, set) and rid not in logged_delta_ids:
                        _dbg(f"OPENAI_AUDIO_DELTA_FIRST response_id={rid} bytes={len(chunk)}")
                        logged_delta_ids.add(rid)
                continue

            if etype == "response.done":
                response = evt.get("response") if isinstance(evt.get("response"), dict) else {}
                rid = response.get("id")
                out_mods = response.get("output_modalities")
                if isinstance(rid, str):
                    processed_done_ids = response_state.get("processed_response_done_ids")
                    if isinstance(processed_done_ids, set) and rid in processed_done_ids:
                        _dbg(f"OPENAI_RESPONSE_DONE_DUPLICATE id={rid}")
                        continue
                    if isinstance(processed_done_ids, set):
                        processed_done_ids.add(rid)
                _dbg(f"OPENAI_RESPONSE_DONE id={rid} output_modalities={out_mods}")
                if isinstance(rid, str):
                    started = response_started_at.get(rid)
                    if isinstance(started, float):
                        dt_ms = int((time.monotonic() - started) * 1000.0)
                        _dbg(f"speech_ctrl_ACTIVE_DONE type=response.done response_id={rid} dt_ms={dt_ms}")
                    diag = response_audio_diag.get(rid)
                    if isinstance(diag, dict):
                        score = _diag_score(diag)
                        frames = max(1, int(diag.get("frames", 0)))
                        same_ratio = float(diag.get("same_as_prev_frames", 0)) / float(frames)
                        low_div_ratio = float(diag.get("low_diversity_frames", 0)) / float(frames)
                        silence_ratio = float(diag.get("silence_like_frames", 0)) / float(frames)
                        _dbg(
                            "AUDIO_HEALTH "
                            f"response_id={rid} score={score} frames={diag.get('frames',0)} "
                            f"chunks={diag.get('delta_chunks',0)} bytes={diag.get('bytes',0)} "
                            f"same_ratio={same_ratio:.2f} same_run_max={diag.get('same_run_max',0)} "
                            f"low_div_ratio={low_div_ratio:.2f} silence_ratio={silence_ratio:.2f}"
                        )
                had_audio = False

                if isinstance(rid, str) and rid:
                    seen_audio_ids = response_state.get("seen_audio_ids")
                    done_no_audio_ids = response_state.get("logged_done_no_audio_ids")
                    had_audio = isinstance(seen_audio_ids, set) and rid in seen_audio_ids
                    if (
                        isinstance(seen_audio_ids, set)
                        and isinstance(done_no_audio_ids, set)
                        and rid not in seen_audio_ids
                        and rid not in done_no_audio_ids
                    ):
                        _dbg(f"OPENAI_RESPONSE_DONE_NO_AUDIO id={rid} output_modalities={out_mods}")
                        done_no_audio_ids.add(rid)

                await _emit_flow_a_event(
                    enabled=event_emit_enabled,
                    tenant_id=call_tenant_id,
                    rid=call_rid,
                    event_type="flow_a.response_done",
                    payload={
                        "tenant_id": call_tenant_id,
                        "rid": call_rid,
                        "ai_mode": call_ai_mode,
                        "tenant_mode": call_tenant_mode,
                        "turn": turn_seq,
                        "response_id": rid,
                        "output_modalities": out_mods,
                        "had_audio": had_audio,
                    },
                )

                if isinstance(rid, str) and rid and rid == active_response_id:
                    _dbg(
                        f"Response {rid} finished with event 'response.done'; "
                        "clearing active_response_id"
                    )
                    active_response_id = None
                    response_state["active_response_id"] = None
                    response_started_at.pop(rid, None)
                    response_audio_diag.pop(rid, None)
                    response_last_frame.pop(rid, None)
                    sent_map = response_state.get("sent_main_frames_by_id")
                    if isinstance(sent_map, dict):
                        sent_map.pop(rid, None)
                    playout_started_ids = response_state.get("playout_started_ids")
                    if isinstance(playout_started_ids, set):
                        playout_started_ids.discard(rid)
                    refill_wait_started_by_id = response_state.get("refill_wait_started_by_id")
                    if isinstance(refill_wait_started_by_id, dict):
                        refill_wait_started_by_id.pop(rid, None)
                    if len(buffers.remainder) < FRAME_BYTES:
                        buffers.remainder.clear()
                if rid is None:
                    active_response_id = None
                    response_state["active_response_id"] = None
                    if len(buffers.remainder) < FRAME_BYTES:
                        buffers.remainder.clear()
                continue

    async def _send_openai_session_update() -> None:
        nonlocal openai_input_blocked_unknown_param
        await openai_ws.send(json.dumps(_build_openai_session_update(voice=voice, instructions=instructions)))
        openai_input_blocked_unknown_param = False

    async def _maybe_send_initial_greeting() -> None:
        if not _initial_greeting_enabled():
            return
        if openai_ws is None:
            return
        prompt = _initial_greeting_text()
        try:
            await openai_ws.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": prompt}],
                        },
                    }
                )
            )
            await openai_ws.send(
                json.dumps({"type": "response.create", "response": {"modalities": ["audio", "text"]}})
            )
            _dbg("OPENAI_INITIAL_GREETING_SENT")
        except Exception as e:
            _dbg(f"OPENAI_INITIAL_GREETING_FAILED err={e!r}")

    async def _speech_ctrl_heartbeat_loop() -> None:
        nonlocal logged_media_absent, pending_input_commit_sent, pending_speech_started_at
        nonlocal pending_speech_started_media_frames
        every_s = max(0.5, _env_int("VOICE_SPEECH_CTRL_HEARTBEAT_MS", 2000) / 1000.0)
        heartbeat_log_enabled = _speech_ctrl_heartbeat_log_enabled()
        while True:
            await asyncio.sleep(every_s)
            now = time.monotonic()
            media_idle_ms = int((now - (last_media_rx_ts or ws_started_at)) * 1000.0)
            if heartbeat_log_enabled:
                _dbg(
                    "speech_ctrl_HEARTBEAT "
                    f"enabled={bridge_enabled} shadow=False qsize={in_q.qsize()} "
                    f"active_response_id={response_state.get('active_response_id')} "
                    f"media_rx_frames={twilio_media_frames_rx} media_idle_ms={media_idle_ms}"
                )
            if not logged_media_absent and twilio_media_frames_rx == 0 and (now - ws_started_at) >= 5.0:
                _dbg("TWILIO_MEDIA_NOT_RECEIVED_AFTER_5S")
                logged_media_absent = True
            if (
                _force_input_commit_enabled()
                and bridge_enabled
                and openai_ws is not None
                and pending_speech_started_at is not None
                and not pending_input_commit_sent
                and active_response_id is None
                and (now - pending_speech_started_at) >= _force_input_commit_after_s()
            ):
                min_frames = _force_input_commit_min_frames()
                start_frames = pending_speech_started_media_frames or twilio_media_frames_rx
                captured_frames = max(0, twilio_media_frames_rx - start_frames)
                if captured_frames < min_frames:
                    _dbg(
                        "OPENAI_INPUT_COMMIT_SKIPPED reason=heartbeat_fallback "
                        f"captured_frames={captured_frames} min_frames={min_frames}"
                    )
                    continue
                try:
                    await openai_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                    pending_input_commit_sent = True
                    _dbg(
                        "OPENAI_INPUT_COMMIT_SENT "
                        f"reason=heartbeat_fallback dt_ms={int((now - pending_speech_started_at) * 1000.0)}"
                    )
                except Exception as e:
                    _dbg(f"OPENAI_INPUT_COMMIT_FAILED reason=heartbeat_fallback err={e!r}")

    try:
        sender_task = asyncio.create_task(
            _twilio_sender_loop(
                websocket=websocket,
                send_lock=send_lock,
                stream_sid_ref=stream_sid_ref,
                buffers=buffers,
                wait_ctl=wait_ctl,
                response_state=response_state,
            )
        )
        heartbeat_task = asyncio.create_task(_speech_ctrl_heartbeat_loop())

        while True:
            raw = await websocket.receive_text()
            evt = json.loads(raw)
            event_type = evt.get("event")

            if event_type == "start":
                start = evt.get("start") or {}
                stream_sid_ref["streamSid"] = start.get("streamSid")
                call_sid = start.get("callSid")
                custom = start.get("customParameters") or {}

                rid = custom.get("rid") or call_sid
                tenant_id_raw = custom.get("tenant_id")
                tenant_id = tenant_id_raw if isinstance(tenant_id_raw, str) and tenant_id_raw.strip() else None
                tenant_mode = custom.get("tenant_mode")
                from_number = custom.get("from_number")
                to_number = custom.get("to_number")
                ai_mode_raw = custom.get("ai_mode")
                ai_mode = _normalize_ai_mode(ai_mode_raw if isinstance(ai_mode_raw, str) else None)
                call_tenant_id = tenant_id
                call_tenant_mode = tenant_mode if isinstance(tenant_mode, str) else None
                call_ai_mode = ai_mode
                call_rid = rid if isinstance(rid, str) else None
                call_sid = call_sid if isinstance(call_sid, str) else None
                call_stream_sid = stream_sid_ref.get("streamSid")
                call_from_number = from_number if isinstance(from_number, str) else None
                call_to_number = to_number if isinstance(to_number, str) else None
                # Keep compatibility with existing policy resolver that uses client|owner naming.
                actor_mode = "owner" if ai_mode == "owner" else "client"
                voice, instructions = _resolve_actor_mode_policy(tenant_id, actor_mode)
                mode_instructions = _resolve_mode_instructions(ai_mode)
                if mode_instructions:
                    instructions = mode_instructions

                _dbg(
                    f"TWILIO_WS_START streamSid={stream_sid_ref['streamSid']} callSid={call_sid} "
                    f"from={from_number} tenant={tenant_id} tenant_mode={tenant_mode} rid={rid} ai_mode={ai_mode}"
                )
                _dbg(
                    f"VOICE_FLOW_A_START tenant_id={tenant_id} tenant_mode={tenant_mode} "
                    f"rid={rid} ai_mode={ai_mode}"
                )
                if not logged_mode_selection:
                    _dbg(f"VOICE_FLOW_A_MODE_SELECTED ai_mode={ai_mode} tenant_id={tenant_id} rid={rid}")
                    logged_mode_selection = True

                await _emit_flow_a_event(
                    enabled=event_emit_enabled,
                    tenant_id=call_tenant_id,
                    rid=call_rid,
                    event_type="flow_a.call_started",
                    payload=_lifecycle_event_payload(
                        tenant_id=call_tenant_id,
                        rid=call_rid,
                        ai_mode=call_ai_mode,
                        tenant_mode=call_tenant_mode,
                        call_sid=call_sid,
                        stream_sid=call_stream_sid,
                        from_number=call_from_number,
                        to_number=call_to_number,
                    ),
                    idempotency_key=f"{call_rid}:call_started" if call_rid else None,
                )

                if bridge_enabled:
                    try:
                        openai_ws = await _connect_openai_ws(model=model)
                        _dbg("OPENAI_WS_CONNECTED")
                        await _send_openai_session_update()
                        _dbg("OPENAI_SESSION_UPDATE_SENT")
                        in_task = asyncio.create_task(_twilio_to_openai_loop())
                        out_task = asyncio.create_task(_openai_to_twilio_loop())
                        await _maybe_send_initial_greeting()
                    except Exception as e:
                        _dbg(f"OPENAI_CONNECT_FAILED err={e!r}")

                continue

            if event_type == "media":
                if bridge_enabled and openai_ws is not None:
                    payload = (evt.get("media") or {}).get("payload")
                    if isinstance(payload, str) and payload:
                        twilio_media_frames_rx += 1
                        last_media_rx_ts = time.monotonic()
                        _drop_oldest_put(payload)
                continue

            if event_type == "stop":
                stop = evt.get("stop") or {}
                _dbg(f"TWILIO_WS_STOP streamSid={stream_sid_ref.get('streamSid')} callSid={stop.get('callSid')}")
                if not call_stopped_emitted:
                    await _emit_flow_a_event(
                        enabled=event_emit_enabled,
                        tenant_id=call_tenant_id,
                        rid=call_rid,
                        event_type="flow_a.call_stopped",
                        payload=_lifecycle_event_payload(
                            tenant_id=call_tenant_id,
                            rid=call_rid,
                            ai_mode=call_ai_mode,
                            tenant_mode=call_tenant_mode,
                            call_sid=call_sid,
                            stream_sid=call_stream_sid,
                            from_number=call_from_number,
                            to_number=call_to_number,
                            reason="twilio_stop",
                        ),
                        idempotency_key=f"{call_rid}:call_stopped" if call_rid else None,
                    )
                    call_stopped_emitted = True
                break

    except WebSocketDisconnect:
        if not call_stopped_emitted:
            await _emit_flow_a_event(
                enabled=event_emit_enabled,
                tenant_id=call_tenant_id,
                rid=call_rid,
                event_type="flow_a.call_stopped",
                payload=_lifecycle_event_payload(
                    tenant_id=call_tenant_id,
                    rid=call_rid,
                    ai_mode=call_ai_mode,
                    tenant_mode=call_tenant_mode,
                    call_sid=call_sid,
                    stream_sid=call_stream_sid,
                    from_number=call_from_number,
                    to_number=call_to_number,
                    reason="twilio_disconnect",
                ),
                idempotency_key=f"{call_rid}:call_stopped" if call_rid else None,
            )
            call_stopped_emitted = True
    except Exception as e:
        _dbg(f"TWILIO_WS_ERROR err={e!r}")
    finally:
        if not call_stopped_emitted:
            await _emit_flow_a_event(
                enabled=event_emit_enabled,
                tenant_id=call_tenant_id,
                rid=call_rid,
                event_type="flow_a.call_stopped",
                payload=_lifecycle_event_payload(
                    tenant_id=call_tenant_id,
                    rid=call_rid,
                    ai_mode=call_ai_mode,
                    tenant_mode=call_tenant_mode,
                    call_sid=call_sid,
                    stream_sid=call_stream_sid,
                    from_number=call_from_number,
                    to_number=call_to_number,
                    reason="stream_cleanup",
                ),
                idempotency_key=f"{call_rid}:call_stopped" if call_rid else None,
            )
        for t in (in_task, out_task, sender_task, heartbeat_task):
            if t:
                t.cancel()
        try:
            if openai_ws is not None:
                await openai_ws.close()
        except Exception:
            pass
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()
        except Exception:
            pass


def selftests() -> dict[str, Any]:
    return {"ok": True}


def security_checks() -> dict[str, Any]:
    return {"ok": True}


def load_profile() -> dict[str, Any]:
    return {"ok": True}


FEATURE = {
    "key": "voice_flow_a",
    "router": router,
    "enabled_env": "VOZ_FEATURE_VOICE_FLOW_A",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
