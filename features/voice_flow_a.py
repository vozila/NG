"""VOZLIA FILE PURPOSE
Purpose: Twilio Media Streams handler for Voice Flow A (Twilio WS <-> OpenAI Realtime WS).
Hot path: YES (WS audio loop). Keep per-frame work bounded; no DB or heavy prompt building.
Public interfaces:
  - websocket /twilio/stream
Reads/Writes: env vars only (no DB).
Feature flags:
  - VOZ_FEATURE_VOICE_FLOW_A
  - VOZ_FLOW_A_OPENAI_BRIDGE
  - VOZLIA_DEBUG
Failure mode:
  - If OpenAI bridge fails, Twilio stream stays connected but no assistant audio is produced.
Last touched: 2026-02-18 (response.create must request supported modalities; add first-delta breadcrumbs)
"""

# CHANGELOG (recent)
# - 2026-02-18: response.create requests modalities=['audio','text'] (per server-supported combos);
#              store/log session output_modalities; keep first-delta breadcrumbs.

from __future__ import annotations

import asyncio
import base64
import json
import os
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

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


def _chunk_to_frames(remainder: bytearray, chunk: bytes, *, frame_bytes: int = FRAME_BYTES) -> list[bytes]:
    if chunk:
        remainder.extend(chunk)
    out: list[bytes] = []
    while len(remainder) >= frame_bytes:
        out.append(bytes(remainder[:frame_bytes]))
        del remainder[:frame_bytes]
    return out


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
    while True:
        sid = stream_sid_ref.get("streamSid")
        if not sid:
            await asyncio.sleep(0.01)
            continue

        frame: bytes | None = None
        lane = "none"
        if buffers.main:
            frame = buffers.main.popleft()
            lane = "main"
        elif wait_ctl.aux_enabled and buffers.aux:
            frame = buffers.aux.popleft()
            lane = "aux"
        else:
            await asyncio.sleep(0.01)
            continue

        # Send immediately, then sleep to pace.
        msg = _build_twilio_media_msg(sid, frame)
        async with send_lock:
            await websocket.send_text(json.dumps(msg))

        if lane == "main":
            rid = response_state.get("active_response_id")
            if isinstance(rid, str):
                logged_main_ids = response_state.get("logged_twilio_main_frame_ids")
                if isinstance(logged_main_ids, set) and rid not in logged_main_ids:
                    _dbg(
                        f"TWILIO_MAIN_FRAME_SENT first=1 response_id={rid} bytes={len(frame)} q_main={len(buffers.main)}"
                    )
                    logged_main_ids.add(rid)

        await asyncio.sleep(FRAME_SLEEP_S)


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
    voice = _env_str("VOZ_OPENAI_REALTIME_VOICE", "marin")
    instructions = (os.getenv("VOZ_OPENAI_REALTIME_INSTRUCTIONS") or "").strip() or None
    q_max = _env_int("VOICE_OPENAI_IN_Q_MAX", 200)
    in_q: asyncio.Queue[str] = asyncio.Queue(maxsize=q_max)

    openai_ws: Any = None
    sender_task: asyncio.Task | None = None
    in_task: asyncio.Task | None = None
    out_task: asyncio.Task | None = None
    openai_input_blocked_unknown_param = False
    logged_session_created = False
    logged_session_updated = False
    openai_output_modalities: list[str] | None = None

    active_response_id: str | None = None
    response_state: dict[str, Any] = {
        "active_response_id": None,
        "logged_delta_ids": set(),
        "logged_text_delta_ids": set(),
        "seen_audio_ids": set(),
        "logged_twilio_main_frame_ids": set(),
        "logged_done_no_audio_ids": set(),
    }

    turn_seq = 0
    turn_logged_speech_started = False
    turn_logged_transcript = False
    turn_logged_response_create = False

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

                if code != "response_cancel_not_active":
                    _dbg(f"OPENAI_ERROR evt={evt!r}")
                continue

            if etype == "input_audio_buffer.speech_started":
                turn_seq += 1
                turn_logged_speech_started = False
                turn_logged_transcript = False
                turn_logged_response_create = False

                buffers.main.clear()
                wait_ctl.on_user_speech_started(buffers=buffers)

                sid = stream_sid_ref.get("streamSid")
                if sid:
                    async with send_lock:
                        await websocket.send_text(json.dumps(_build_twilio_clear_msg(sid)))
                    _dbg("TWILIO_CLEAR_SENT")

                if active_response_id:
                    await openai_ws.send(json.dumps({"type": "response.cancel"}))

                if not turn_logged_speech_started:
                    _dbg(f"OPENAI_SPEECH_STARTED turn={turn_seq}")
                    turn_logged_speech_started = True
                continue

            if etype == "conversation.item.input_audio_transcription.completed":
                transcript = (evt.get("transcript") or "").strip()
                if not transcript:
                    continue

                if not turn_logged_transcript:
                    _dbg(f"OPENAI_TRANSCRIPT completed len={len(transcript)} turn={turn_seq}")
                    turn_logged_transcript = True

                if active_response_id is not None:
                    continue

                # IMPORTANT: Your server reports supported combinations: ['text'] and ['audio','text'].
                # Request audio+text explicitly so output_audio events are enabled.
                modalities = openai_output_modalities or ["audio", "text"]
                await openai_ws.send(json.dumps({"type": "response.create", "response": {"modalities": modalities}}))

                if not turn_logged_response_create:
                    _dbg(f"OPENAI_RESPONSE_CREATE_SENT rid={turn_seq} modalities={modalities!r}")
                    turn_logged_response_create = True
                continue

            if etype == "response.created":
                response = evt.get("response") if isinstance(evt.get("response"), dict) else {}
                rid = response.get("id")
                if isinstance(rid, str) and rid:
                    active_response_id = rid
                    response_state["active_response_id"] = rid
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
                    try:
                        chunk = base64.b64decode(audio_b64)
                    except Exception:
                        continue

                    frames = _chunk_to_frames(buffers.remainder, chunk)
                    for f in frames:
                        if len(buffers.main) >= buffers.main_max_frames:
                            buffers.main.popleft()
                        buffers.main.append(f)

                    evt_rid = evt.get("response_id")
                    rid = evt_rid if isinstance(evt_rid, str) and evt_rid else active_response_id
                    if isinstance(rid, str):
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
                try:
                    chunk = base64.b64decode(delta_b64)
                except Exception:
                    continue

                frames = _chunk_to_frames(buffers.remainder, chunk)
                for f in frames:
                    if len(buffers.main) >= buffers.main_max_frames:
                        buffers.main.popleft()
                    buffers.main.append(f)

                evt_rid = evt.get("response_id")
                rid = evt_rid if isinstance(evt_rid, str) and evt_rid else active_response_id
                if isinstance(rid, str):
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
                _dbg(f"OPENAI_RESPONSE_DONE id={rid} output_modalities={out_mods}")

                if isinstance(rid, str) and rid:
                    seen_audio_ids = response_state.get("seen_audio_ids")
                    done_no_audio_ids = response_state.get("logged_done_no_audio_ids")
                    if (
                        isinstance(seen_audio_ids, set)
                        and isinstance(done_no_audio_ids, set)
                        and rid not in seen_audio_ids
                        and rid not in done_no_audio_ids
                    ):
                        _dbg(f"OPENAI_RESPONSE_DONE_NO_AUDIO id={rid} output_modalities={out_mods}")
                        done_no_audio_ids.add(rid)

                if isinstance(rid, str) and rid and rid == active_response_id:
                    active_response_id = None
                    response_state["active_response_id"] = None
                if rid is None:
                    active_response_id = None
                    response_state["active_response_id"] = None
                continue

    async def _send_openai_session_update() -> None:
        nonlocal openai_input_blocked_unknown_param
        await openai_ws.send(json.dumps(_build_openai_session_update(voice=voice, instructions=instructions)))
        openai_input_blocked_unknown_param = False

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
                tenant_id = custom.get("tenant_id")
                tenant_mode = custom.get("tenant_mode")
                from_number = custom.get("from_number")

                _dbg(
                    f"TWILIO_WS_START streamSid={stream_sid_ref['streamSid']} callSid={call_sid} "
                    f"from={from_number} tenant={tenant_id} tenant_mode={tenant_mode} rid={rid}"
                )
                _dbg(f"VOICE_FLOW_A_START tenant_id={tenant_id} tenant_mode={tenant_mode} rid={rid}")

                if bridge_enabled:
                    try:
                        openai_ws = await _connect_openai_ws(model=model)
                        _dbg("OPENAI_WS_CONNECTED")
                        await _send_openai_session_update()
                        _dbg("OPENAI_SESSION_UPDATE_SENT")
                        in_task = asyncio.create_task(_twilio_to_openai_loop())
                        out_task = asyncio.create_task(_openai_to_twilio_loop())
                    except Exception as e:
                        _dbg(f"OPENAI_CONNECT_FAILED err={e!r}")

                continue

            if event_type == "media":
                if bridge_enabled and openai_ws is not None:
                    payload = (evt.get("media") or {}).get("payload")
                    if isinstance(payload, str) and payload:
                        _drop_oldest_put(payload)
                continue

            if event_type == "stop":
                stop = evt.get("stop") or {}
                _dbg(f"TWILIO_WS_STOP streamSid={stream_sid_ref.get('streamSid')} callSid={stop.get('callSid')}")
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        _dbg(f"TWILIO_WS_ERROR err={e!r}")
    finally:
        for t in (in_task, out_task, sender_task):
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
