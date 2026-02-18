"""VOZLIA FILE PURPOSE
Purpose: Twilio Media Streams handler for Voice Flow A (Slice A–D scaffolding), including a
  first-class “waiting/thinking audio” lane to avoid future regressions with barge-in/buffers.
Hot path: yes (websocket loop must stay lightweight; no DB/LLM; bounded work per frame).
Public interfaces:
  - WS /twilio/stream
  - parse_twilio_start(d), parse_twilio_media(d), is_twilio_stop(d)
  - WaitingAudioController (pure, deterministic; tested offline)
Reads/Writes: none (in-memory only).
Feature flags:
  - VOZ_FEATURE_VOICE_FLOW_A (default OFF)
  - VOZLIA_DEBUG (gates diagnostic logs)
  - VOICE_WAIT_CHIME_ENABLED (default OFF; enables aux-lane “thinking” chime)
Failure mode: malformed events ignored; sender loop stops on disconnect; aux lane is cancelable.
Last touched: 2026-02-17 (add aux audio lane + deterministic waiting-audio controller)
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import math
import os
import time
from urllib.parse import quote_plus
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from core.config import env_flag, is_debug
from core.feature_loader import load_features
from core.logging import logger

router = APIRouter()

# -----------------------------
# Constants
# -----------------------------

# Twilio Media Streams audio: 8kHz μ-law (PCMU), 20ms frames => 160 bytes
TWILIO_SAMPLE_RATE_HZ = 8000
FRAME_MS = 20
FRAME_BYTES = int(TWILIO_SAMPLE_RATE_HZ * (FRAME_MS / 1000.0))  # 160

# Default pacing (20ms per 160-byte frame)
FRAME_SLEEP_S = FRAME_MS / 1000.0

# OpenAI Realtime endpoint base
OPENAI_REALTIME_URL_BASE = "wss://api.openai.com/v1/realtime"

# -----------------------------
# Helpers: env + logs
# -----------------------------


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        return int(raw)
    except Exception:
        return default


def _env_str(name: str, default: str) -> str:
    raw = (os.getenv(name) or "").strip()
    return raw or default


def _dbg(msg: str) -> None:
    if is_debug():
        logger.info(msg)


# -----------------------------
# Audio buffers and waiting lane
# -----------------------------


@dataclass
class OutgoingAudioBuffers:
    # Two lanes: main (assistant) and aux (waiting/thinking chime)
    main: deque[bytes] = field(default_factory=deque)
    aux: deque[bytes] = field(default_factory=deque)
    remainder: bytearray = field(default_factory=bytearray)

    # Bound main queue to keep latency bounded
    main_max_frames: int = 200


class WaitingAudioController:
    """
    Controls waiting/thinking audio behavior.

    Current MVP behavior:
      - aux lane exists
      - on user speech started: clear aux and disable aux
      - on model speech started/done: disable/enable aux

    Future:
      - can generate a chime and push to aux periodically (gated by VOICE_WAIT_CHIME_ENABLED)
    """

    def __init__(self) -> None:
        self._aux_enabled: bool = True

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
    # Twilio "clear" flushes buffered audio and interrupts playback
    return {"event": "clear", "streamSid": stream_sid}


def _chunk_to_frames(remainder: bytearray, chunk: bytes, *, frame_bytes: int = FRAME_BYTES) -> list[bytes]:
    if chunk:
        remainder.extend(chunk)
    out: list[bytes] = []
    while len(remainder) >= frame_bytes:
        out.append(bytes(remainder[:frame_bytes]))
        del remainder[:frame_bytes]
    return out


# -----------------------------
# Twilio event parsing
# -----------------------------


def parse_twilio_start(evt: dict[str, Any]) -> dict[str, Any] | None:
    if evt.get("event") != "start":
        return None
    start = evt.get("start") or {}
    custom = start.get("customParameters") or {}
    return {
        "streamSid": start.get("streamSid"),
        "callSid": start.get("callSid"),
        "custom": custom,
    }


def parse_twilio_media(evt: dict[str, Any]) -> str | None:
    if evt.get("event") != "media":
        return None
    media = evt.get("media") or {}
    payload = media.get("payload")
    return payload if isinstance(payload, str) else None


def is_twilio_stop(evt: dict[str, Any]) -> bool:
    return evt.get("event") == "stop"


# -----------------------------
# OpenAI Realtime helpers
# -----------------------------


def _build_openai_session_update(*, voice: str, instructions: str | None) -> dict[str, Any]:
    # REQUIRED: session.type="realtime" (your earlier error)
    session: dict[str, Any] = {
        "type": "realtime",
        "output_modalities": ["audio"],
        "audio": {
            "input": {
                "format": {"type": "audio/pcmu"},
                "turn_detection": {
                    "type": "server_vad",
                    "create_response": True,
                    "interrupt_response": True,
                },
            },
            "output": {
                "format": {"type": "audio/pcmu"},
                "voice": voice,
            },
        },
    }
    if instructions:
        session["instructions"] = instructions
    return {"type": "session.update", "session": session}


async def _connect_openai_ws(*, model: str) -> Any:
    """
    Connect to OpenAI Realtime WebSocket.

    IMPORTANT: Different `websockets` versions use different argument names for headers.
    We introspect the connect() signature to choose:
      - additional_headers (new)
      - extra_headers (old)
      - header (websocket-client style)
    """
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY missing")

    try:
        import websockets  # type: ignore
    except ImportError:
        return None

    url = f"{OPENAI_REALTIME_URL_BASE}?model={quote_plus(model)}"
    auth = [("Authorization", f"Bearer {api_key}"), ("OpenAI-Beta", "realtime=v1")]

    # The `websockets` package has changed its connect() signature over versions.
    import inspect
    params = set(inspect.signature(websockets.connect).parameters.keys())

    kwargs: dict[str, Any] = {}
    if "additional_headers" in params:
        kwargs["additional_headers"] = auth
    elif "extra_headers" in params:
        kwargs["extra_headers"] = auth
    elif "headers" in params:
        kwargs["headers"] = auth
    elif "header" in params:
        # websocket-client style expects list[str]
        kwargs["header"] = [f"{k}: {v}" for k, v in auth]
    else:
        kwargs = {}

    return await websockets.connect(url, **kwargs)


async def _start_openai_bridge(
    *,
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    stream_sid_ref: dict[str, str | None],
    buffers: OutgoingAudioBuffers,
    wait_ctl: WaitingAudioController,
    tenant_id: str | None,
    tenant_mode: str | None,
    rid: str | None,
) -> dict[str, Any]:
    """
    Start OpenAI bridge tasks:
      - Twilio inbound frames -> OpenAI input_audio_buffer.append (via bounded queue)
      - OpenAI output_audio.delta -> Twilio outbound main lane frames
      - Barge-in: input_audio_buffer.speech_started -> Twilio clear + clear main + stop aux
    """
    enabled = env_flag("VOZ_FLOW_A_OPENAI_BRIDGE")
    if not enabled:
        return {"ok": False, "reason": "bridge_disabled"}

    model = _env_str("VOZ_OPENAI_REALTIME_MODEL", "gpt-realtime")
    voice = _env_str("VOZ_OPENAI_REALTIME_VOICE", "marin")
    instructions = (os.getenv("VOZ_OPENAI_REALTIME_INSTRUCTIONS") or "").strip() or None

    openai_ws = await _connect_openai_ws(model=model)
    if openai_ws is None:
        raise RuntimeError("websockets dependency missing")

    _dbg("OPENAI_WS_CONNECTED")

    # Send session.update
    await openai_ws.send(json.dumps(_build_openai_session_update(voice=voice, instructions=instructions)))
    _dbg("OPENAI_SESSION_UPDATE_SENT")

    q_max = _env_int("VOICE_OPENAI_IN_Q_MAX", 200)
    in_q: asyncio.Queue[str] = asyncio.Queue(maxsize=q_max)

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

    # Twilio -> OpenAI
    async def _twilio_to_openai_loop() -> None:
        count = 0
        while True:
            audio_b64 = await in_q.get()
            await openai_ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": audio_b64}))
            count += 1
            if is_debug() and (count == 1 or count % 50 == 0):
                _dbg(f"OPENAI_AUDIO_IN count={count} qsize={in_q.qsize()}")

    # OpenAI -> Twilio
    async def _openai_to_twilio_loop() -> None:
        while True:
            raw = await openai_ws.recv()
            evt = json.loads(raw)
            etype = evt.get("type")

            if etype in ("session.created", "session.updated"):
                _dbg("OPENAI_SESSION_UPDATED")
                continue

            if etype == "error":
                _dbg(f"OPENAI_ERROR evt={evt!r}")
                continue

            if etype == "input_audio_buffer.speech_started":
                # barge-in: clear main, stop aux, send Twilio clear
                buffers.main.clear()
                wait_ctl.on_user_speech_started(buffers=buffers)
                sid = stream_sid_ref.get("streamSid")
                if sid:
                    async with send_lock:
                        await websocket.send_text(json.dumps(_build_twilio_clear_msg(sid)))
                _dbg("TWILIO_CLEAR_SENT")
                continue

            if etype == "response.output_audio.delta":
                delta_b64 = evt.get("delta")
                if not isinstance(delta_b64, str) or not delta_b64:
                    continue
                try:
                    chunk = base64.b64decode(delta_b64)
                except binascii.Error:
                    continue

                frames = _chunk_to_frames(buffers.remainder, chunk)
                for f in frames:
                    if len(buffers.main) >= buffers.main_max_frames:
                        buffers.main.popleft()
                    buffers.main.append(f)
                if is_debug():
                    _dbg(f"OPENAI_AUDIO_DELTA frames={len(frames)} main_q={len(buffers.main)}")
                continue

            if etype == "response.done":
                _dbg("OPENAI_RESPONSE_DONE")
                continue

    # Expose for caller
    return {
        "ok": True,
        "openai_ws": openai_ws,
        "enqueue_audio": _drop_oldest_put,
        "task_in": asyncio.create_task(_twilio_to_openai_loop()),
        "task_out": asyncio.create_task(_openai_to_twilio_loop()),
    }


# -----------------------------
# Twilio sender loop
# -----------------------------


async def _twilio_sender_loop(
    *,
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    stream_sid_ref: dict[str, str | None],
    buffers: OutgoingAudioBuffers,
    wait_ctl: WaitingAudioController,
) -> None:
    """
    Send frames to Twilio at ~20ms pacing.
    Prefer main lane, then aux lane (if enabled).
    """
    while True:
        sid = stream_sid_ref.get("streamSid")
        if not sid:
            await asyncio.sleep(0.01)
            continue

        frame: bytes | None = None

        if buffers.main:
            frame = buffers.main.popleft()
            await asyncio.sleep(FRAME_SLEEP_S)
        elif wait_ctl.aux_enabled and buffers.aux:
            frame = buffers.aux.popleft()
            await asyncio.sleep(FRAME_SLEEP_S)
        else:
            await asyncio.sleep(0.01)

        if frame is None:
            continue

        msg = _build_twilio_media_msg(sid, frame)
        async with send_lock:
            await websocket.send_text(json.dumps(msg))


# -----------------------------
# Main WS endpoint
# -----------------------------


@router.websocket("/twilio/stream")
async def twilio_stream(websocket: WebSocket) -> None:
    if not env_flag("VOZ_FEATURE_VOICE_FLOW_A"):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    _dbg("TWILIO_WS_CONNECTED")

    send_lock = asyncio.Lock()
    stream_sid_ref: dict[str, str | None] = {"streamSid": None}

    buffers = OutgoingAudioBuffers(
        main_max_frames=_env_int("VOICE_MAIN_MAX_FRAMES", 200),
    )
    wait_ctl = WaitingAudioController()

    # Bridge state
    bridge: dict[str, Any] | None = None
    openai_ws: Any = None
    bridge_in_task: asyncio.Task | None = None
    bridge_out_task: asyncio.Task | None = None
    enqueue_audio = None

    sender_task: asyncio.Task | None = None

    tenant_id: str | None = None
    tenant_mode: str | None = None
    rid: str | None = None

    try:
        sender_task = asyncio.create_task(
            _twilio_sender_loop(
                websocket=websocket,
                send_lock=send_lock,
                stream_sid_ref=stream_sid_ref,
                buffers=buffers,
                wait_ctl=wait_ctl,
            )
        )

        while True:
            raw = await websocket.receive_text()
            evt = json.loads(raw)

            start = parse_twilio_start(evt)
            if start is not None:
                stream_sid_ref["streamSid"] = start.get("streamSid")
                call_sid = start.get("callSid")
                custom = start.get("custom") or {}
                tenant_id = custom.get("tenant_id")
                tenant_mode = custom.get("tenant_mode")
                rid = custom.get("rid") or call_sid
                from_number = custom.get("from_number")

                _dbg(
                    f"TWILIO_WS_START streamSid={stream_sid_ref['streamSid']} callSid={call_sid} "
                    f"from={from_number} tenant={tenant_id} tenant_mode={tenant_mode} rid={rid}"
                )
                _dbg(f"VOICE_FLOW_A_START tenant_id={tenant_id} tenant_mode={tenant_mode} rid={rid}")

                # Start bridge if enabled
                if env_flag("VOZ_FLOW_A_OPENAI_BRIDGE"):
                    try:
                        bridge = await _start_openai_bridge(
                            websocket=websocket,
                            send_lock=send_lock,
                            stream_sid_ref=stream_sid_ref,
                            buffers=buffers,
                            wait_ctl=wait_ctl,
                            tenant_id=tenant_id,
                            tenant_mode=tenant_mode,
                            rid=rid,
                        )
                        if bridge.get("ok"):
                            openai_ws = bridge["openai_ws"]
                            bridge_in_task = bridge["task_in"]
                            bridge_out_task = bridge["task_out"]
                            enqueue_audio = bridge["enqueue_audio"]
                    except Exception as e:
                        _dbg(f"OPENAI_CONNECT_FAILED err={e!r}")
                continue

            if is_twilio_stop(evt):
                stop = evt.get("stop") or {}
                _dbg(f"TWILIO_WS_STOP streamSid={stream_sid_ref.get('streamSid')} callSid={stop.get('callSid')}")
                break

            payload = parse_twilio_media(evt)
            if payload and enqueue_audio is not None:
                enqueue_audio(payload)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        _dbg(f"TWILIO_WS_ERROR err={e!r}")
    finally:
        # Stop tasks
        for t in (bridge_in_task, bridge_out_task, sender_task):
            if t:
                t.cancel()
        # Close openai ws
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


# -----------------------------
# Feature module contract
# -----------------------------


def selftests() -> dict[str, Any]:
    # Deterministic tests live in tests/test_voice_flow_a.py
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


def mount(app: FastAPI) -> None:
    app.include_router(router)


def install_into_app(app: FastAPI) -> None:
    app.include_router(router)


def ensure_features_loaded(app: FastAPI) -> None:
    load_features(app)
