"""VOZLIA FILE PURPOSE
Purpose: Twilio Media Streams ↔ OpenAI Realtime bridge for Voice Flow A.
Hot path: yes (WS loops; avoid per-frame logging / heavy parsing).
Public interfaces:
  - WebSocket: /twilio/stream
  - Helpers: parse_twilio_start, parse_twilio_media, is_twilio_stop
Reads/Writes: reads env vars only (no DB).
Feature flags: VOZ_FEATURE_VOICE_FLOW_A (default OFF), VOZLIA_DEBUG.
Failure mode: if OpenAI connection fails, close Twilio WS cleanly (no busy loops).
Last touched: 2026-02-17 (port OpenAI Realtime bridge from legacy flow_a.py).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import websockets
from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from core.config import env_flag, is_debug
from core.feature_loader import load_features
from core.logging import logger

router = APIRouter()

# ---- Env (legacy-compatible names) ----
BYTES_PER_FRAME = int(os.getenv("BYTES_PER_FRAME", "160"))  # 20ms @ 8kHz μ-law
FRAME_INTERVAL = float(os.getenv("FRAME_INTERVAL", "0.02"))
PREBUFFER_BYTES = int(os.getenv("PREBUFFER_BYTES", "8000"))
MAX_TWILIO_BACKLOG_SECONDS = float(os.getenv("MAX_TWILIO_BACKLOG_SECONDS", "1.0"))

OPENAI_REALTIME_MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-4o-mini-realtime-preview-2024-12-17")
OPENAI_REALTIME_URL = os.getenv(
    "OPENAI_REALTIME_URL", f"wss://api.openai.com/v1/realtime?model={OPENAI_REALTIME_MODEL}"
)
OPENAI_REALTIME_VOICE = os.getenv("OPENAI_REALTIME_VOICE", os.getenv("VOICE_NAME", "coral"))
REALTIME_SYSTEM_PROMPT = os.getenv(
    "REALTIME_SYSTEM_PROMPT",
    "You are Vozlia, a helpful real-time voice assistant. Always introduce yourself. "
    "Be concise, friendly, and natural.",
)
REALTIME_TRANSCRIBE_MODEL = os.getenv("REALTIME_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")

REALTIME_VAD_THRESHOLD = float(os.getenv("REALTIME_VAD_THRESHOLD", "0.5"))
REALTIME_VAD_SILENCE_MS = int(os.getenv("REALTIME_VAD_SILENCE_MS", "600"))
REALTIME_VAD_PREFIX_MS = int(os.getenv("REALTIME_VAD_PREFIX_MS", "200"))

REALTIME_CREATE_RESPONSE = env_flag("REALTIME_CREATE_RESPONSE", "1")
OPENAI_INTERRUPT_RESPONSE = env_flag("OPENAI_INTERRUPT_RESPONSE", "1")
REALTIME_SEND_INITIAL_GREETING = env_flag("REALTIME_SEND_INITIAL_GREETING", "1")

_TENANT_ID_ALLOWLIST = ("tenant_id",)


def _clean_str(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    s = v.strip()
    return s or None


def parse_twilio_start(d: dict) -> dict:
    start = d.get("start")
    start_obj = start if isinstance(start, dict) else {}
    custom = start_obj.get("customParameters")
    custom_obj = custom if isinstance(custom, dict) else {}

    tenant_id = None
    for k in _TENANT_ID_ALLOWLIST:
        tenant_id = _clean_str(custom_obj.get(k))
        if tenant_id:
            break

    return {
        "streamSid": _clean_str(start_obj.get("streamSid")) or _clean_str(d.get("streamSid")),
        "callSid": _clean_str(start_obj.get("callSid")) or _clean_str(d.get("callSid")),
        "from_number": _clean_str(start_obj.get("from")) or _clean_str(custom_obj.get("from_number")),
        "tenant_id": tenant_id,
    }


def parse_twilio_media(d: dict) -> bytes | None:
    # NOTE: expensive (base64 decode). Kept for tests and offline validation.
    media = d.get("media")
    if not isinstance(media, dict):
        return None
    payload = media.get("payload")
    if not isinstance(payload, str):
        return None
    try:
        return base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error):
        return None


def parse_twilio_media_payload_b64(d: dict) -> str | None:
    # Fast path: return base64 string without decoding.
    media = d.get("media")
    if not isinstance(media, dict):
        return None
    payload = media.get("payload")
    if not isinstance(payload, str):
        return None
    if len(payload) > 50_000:
        return None
    return payload


def is_twilio_stop(d: dict) -> bool:
    return d.get("event") == "stop"


def _openai_headers() -> list[tuple[str, str]]:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return [("Authorization", f"Bearer {api_key}"), ("OpenAI-Beta", "realtime=v1")]


@contextmanager
def _temp_env(values: dict[str, str | None]) -> Iterator[None]:
    old: dict[str, str | None] = {}
    for k, v in values.items():
        old[k] = os.getenv(k)
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@router.websocket("/twilio/stream")
async def twilio_stream(websocket: WebSocket) -> None:
    """Flow A bridge: Twilio WS ↔ OpenAI Realtime WS."""
    await websocket.accept()

    # NOTE: FastAPI WebSocket sends are not guaranteed to be concurrency-safe; guard with a lock.
    twilio_send_lock = asyncio.Lock()
    openai_send_lock = asyncio.Lock()

    stream_sid: str | None = None
    call_sid: str | None = None
    tenant_id: str | None = None

    openai_ws: websockets.WebSocketClientProtocol | None = None
    audio_buffer = bytearray()
    stop_event = asyncio.Event()

    sender_task: asyncio.Task[None] | None = None
    openai_task: asyncio.Task[None] | None = None

    active_response_id: str | None = None
    assistant_last_audio_time = 0.0

    async def twilio_send(obj: dict[str, object]) -> None:
        async with twilio_send_lock:
            await websocket.send_text(json.dumps(obj))

    async def twilio_clear() -> None:
        if not stream_sid:
            return
        try:
            await twilio_send({"event": "clear", "streamSid": stream_sid})
        except Exception:
            return

    def assistant_speaking() -> bool:
        if audio_buffer:
            return True
        return bool(assistant_last_audio_time and (time.monotonic() - assistant_last_audio_time) < 0.5)

    async def create_realtime_session() -> websockets.WebSocketClientProtocol:
        if is_debug():
            logger.info(
                "FLOW_A openai_connect url=%s tenant=%s callSid=%s", OPENAI_REALTIME_URL, tenant_id, call_sid
            )

        ws = await websockets.connect(
            OPENAI_REALTIME_URL,
            extra_headers=_openai_headers(),
            ping_interval=None,
            ping_timeout=None,
            max_size=None,
        )

        prompt = REALTIME_SYSTEM_PROMPT
        if tenant_id:
            prompt = f"{prompt}\n\nTenant context: tenant_id={tenant_id}."

        session_update = {
            "type": "session.update",
            "session": {
                "instructions": prompt,
                "voice": OPENAI_REALTIME_VOICE,
                "modalities": ["text", "audio"],
                "input_audio_format": "g711_ulaw",
                "output_audio_format": "g711_ulaw",
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": REALTIME_VAD_THRESHOLD,
                    "silence_duration_ms": REALTIME_VAD_SILENCE_MS,
                    "prefix_padding_ms": REALTIME_VAD_PREFIX_MS,
                    "create_response": REALTIME_CREATE_RESPONSE,
                    "interrupt_response": OPENAI_INTERRUPT_RESPONSE,
                },
                "input_audio_transcription": {"model": REALTIME_TRANSCRIBE_MODEL},
            },
        }
        await ws.send(json.dumps(session_update))

        if REALTIME_SEND_INITIAL_GREETING:
            await ws.send(json.dumps({"type": "response.create"}))

        return ws

    async def openai_send(obj: dict[str, object]) -> None:
        assert openai_ws is not None
        async with openai_send_lock:
            await openai_ws.send(json.dumps(obj))

    async def twilio_audio_sender() -> None:
        nonlocal assistant_last_audio_time
        next_send = time.monotonic()
        frames_sent = 0
        play_start: float | None = None
        prebuffer_active = True

        while not stop_event.is_set():
            if not stream_sid:
                await asyncio.sleep(0.01)
                continue

            now = time.monotonic()
            if now < next_send:
                await asyncio.sleep(min(0.01, next_send - now))
                continue

            if play_start is None:
                play_start = now
                frames_sent = 0
                prebuffer_active = True

            # backlog > 0 means we've sent more audio than wall clock; cap it.
            call_elapsed = now - play_start
            sent_dur = frames_sent * FRAME_INTERVAL
            backlog = sent_dur - call_elapsed
            if backlog > MAX_TWILIO_BACKLOG_SECONDS:
                await asyncio.sleep(0.01)
                next_send = time.monotonic()
                continue

            if prebuffer_active and len(audio_buffer) < PREBUFFER_BYTES:
                await asyncio.sleep(0.005)
                next_send = time.monotonic() + FRAME_INTERVAL
                continue
            prebuffer_active = False

            if len(audio_buffer) >= BYTES_PER_FRAME:
                chunk = bytes(audio_buffer[:BYTES_PER_FRAME])
                del audio_buffer[:BYTES_PER_FRAME]
                payload = base64.b64encode(chunk).decode("ascii")
                msg = {"event": "media", "streamSid": stream_sid, "media": {"payload": payload}}
                try:
                    await twilio_send(msg)
                except Exception:
                    stop_event.set()
                    return
                assistant_last_audio_time = time.monotonic()
                frames_sent += 1
            else:
                await asyncio.sleep(0.005)

            next_send = time.monotonic() + FRAME_INTERVAL

    async def openai_event_loop() -> None:
        nonlocal active_response_id
        assert openai_ws is not None
        try:
            async for raw in openai_ws:
                if stop_event.is_set():
                    break
                try:
                    event = json.loads(raw)
                except Exception:
                    continue
                etype = event.get("type")

                if etype == "response.created":
                    rid = (event.get("response") or {}).get("id")
                    if isinstance(rid, str) and rid:
                        active_response_id = rid
                    continue

                if etype in ("response.completed", "response.failed", "response.canceled"):
                    rid = (event.get("response") or {}).get("id")
                    if active_response_id and rid == active_response_id:
                        active_response_id = None
                        # Pad to frame boundary to avoid sender deadlock on trailing remainder.
                        rem = len(audio_buffer) % BYTES_PER_FRAME
                        if rem:
                            audio_buffer.extend(b"\xff" * (BYTES_PER_FRAME - rem))
                    continue

                if etype == "response.audio.delta":
                    rid = event.get("response_id")
                    if active_response_id and rid != active_response_id:
                        continue
                    delta_b64 = event.get("delta")
                    if not isinstance(delta_b64, str) or not delta_b64:
                        continue
                    try:
                        audio_buffer.extend(base64.b64decode(delta_b64))
                    except Exception:
                        continue
                    continue

                if etype == "input_audio_buffer.speech_started":
                    if assistant_speaking():
                        # Local mute + clear Twilio queued audio.
                        audio_buffer.clear()
                        await twilio_clear()

                        # Best-effort cancel OpenAI response (cancel races are expected).
                        if active_response_id:
                            rid = active_response_id
                            active_response_id = None
                            try:
                                await openai_send({"type": "response.cancel", "response_id": rid})
                            except Exception:
                                pass
                    continue

                if etype == "error":
                    if is_debug():
                        logger.info("FLOW_A openai_error event=%s", event)
                    else:
                        err = event.get("error", {})
                        code = err.get("code") if isinstance(err, dict) else None
                        if code not in ("response_cancel_not_active",):
                            logger.warning("FLOW_A openai_error code=%s", code)
                    continue

        except Exception:
            if is_debug():
                logger.exception("FLOW_A openai_loop_exception")
        finally:
            stop_event.set()

    try:
        async for raw in websocket.iter_text():
            try:
                data = json.loads(raw)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue

            event = data.get("event")
            if event == "connected":
                if is_debug():
                    logger.info("TWILIO_WS_CONNECTED")
                continue

            if event == "start":
                start_info = parse_twilio_start(data)
                stream_sid = start_info["streamSid"]
                call_sid = start_info["callSid"]
                tenant_id = start_info["tenant_id"]

                if is_debug():
                    logger.info(
                        "TWILIO_WS_START streamSid=%s callSid=%s from=%s tenant=%s",
                        stream_sid,
                        call_sid,
                        start_info["from_number"],
                        tenant_id,
                    )

                if openai_ws is None:
                    try:
                        openai_ws = await create_realtime_session()
                    except Exception as e:
                        logger.warning("FLOW_A openai_session_failed err=%s", type(e).__name__)
                        break

                    sender_task = asyncio.create_task(twilio_audio_sender())
                    openai_task = asyncio.create_task(openai_event_loop())
                continue

            if event == "media":
                if openai_ws is None:
                    continue
                payload_b64 = parse_twilio_media_payload_b64(data)
                if payload_b64 is None:
                    continue
                try:
                    await openai_send({"type": "input_audio_buffer.append", "audio": payload_b64})
                except Exception:
                    stop_event.set()
                    break
                continue

            if is_twilio_stop(data):
                if is_debug():
                    logger.info("TWILIO_WS_STOP streamSid=%s callSid=%s", stream_sid, call_sid)
                stop_event.set()
                break

    except WebSocketDisconnect:
        stop_event.set()
    finally:
        stop_event.set()

        for t in (sender_task, openai_task):
            try:
                if t is not None:
                    t.cancel()
            except Exception:
                pass

        try:
            if openai_ws is not None:
                await openai_ws.close()
        except Exception:
            pass

        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close()
            except Exception:
                pass

        _ = tenant_id
        _ = call_sid


def _has_ws_route(app: FastAPI, path: str) -> bool:
    return any(getattr(route, "path", None) == path for route in app.routes)


def selftests() -> dict:
    start_evt = {
        "event": "start",
        "start": {
            "streamSid": "MZ123",
            "callSid": "CA123",
            "customParameters": {"tenant_id": " tenant-a ", "tenant": "blocked", "from_number": " +15551234567 "},
        },
    }
    if parse_twilio_start(start_evt) != {
        "streamSid": "MZ123",
        "callSid": "CA123",
        "from_number": "+15551234567",
        "tenant_id": "tenant-a",
    }:
        return {"ok": False, "message": "parse_twilio_start failed"}

    if parse_twilio_start({"event": "start", "start": {"customParameters": {"tenant": "x"}}})["tenant_id"] is not None:
        return {"ok": False, "message": "tenant_id allowlist failed"}

    if parse_twilio_media({"event": "media", "media": {"payload": "aGVsbG8="}}) != b"hello":
        return {"ok": False, "message": "parse_twilio_media valid payload failed"}
    if parse_twilio_media({"event": "media", "media": {"payload": "*"}}) is not None:
        return {"ok": False, "message": "parse_twilio_media malformed payload failed"}

    if parse_twilio_media_payload_b64({"event": "media", "media": {"payload": "aGVsbG8="}}) != "aGVsbG8=":
        return {"ok": False, "message": "parse_twilio_media_payload_b64 failed"}

    if not is_twilio_stop({"event": "stop"}) or is_twilio_stop({"event": "media"}):
        return {"ok": False, "message": "is_twilio_stop failed"}

    env_reset = {
        "VOZ_FEATURE_SAMPLE": "0",
        "VOZ_FEATURE_ADMIN_QUALITY": "0",
        "VOZ_FEATURE_ACCESS_GATE": "0",
        "VOZ_FEATURE_WHATSAPP_IN": "0",
    }
    with _temp_env({**env_reset, "VOZ_FEATURE_VOICE_FLOW_A": "0"}):
        off_app = FastAPI()
        load_features(off_app)
        if _has_ws_route(off_app, "/twilio/stream"):
            return {"ok": False, "message": "route mounted while feature disabled"}

    with _temp_env({**env_reset, "VOZ_FEATURE_VOICE_FLOW_A": "1"}):
        on_app = FastAPI()
        load_features(on_app)
        if not _has_ws_route(on_app, "/twilio/stream"):
            return {"ok": False, "message": "route missing while feature enabled"}

    return {"ok": True, "message": "voice_flow_a selftests ok"}


def security_checks() -> dict:
    enabled = env_flag("VOZ_FEATURE_VOICE_FLOW_A", "0")
    raw = os.getenv("VOZ_FEATURE_VOICE_FLOW_A")
    if raw is None and enabled:
        return {"ok": False, "message": "VOZ_FEATURE_VOICE_FLOW_A must default OFF"}

    tenant_ok = parse_twilio_start({"event": "start", "start": {"customParameters": {"tenant_id": " tenant-a "}}})[
        "tenant_id"
    ]
    if tenant_ok != "tenant-a":
        return {"ok": False, "message": "tenant_id strip/allowlist failed"}

    tenant_blocked = parse_twilio_start({"event": "start", "start": {"customParameters": {"tenant": "wrong"}}})[
        "tenant_id"
    ]
    if tenant_blocked is not None:
        return {"ok": False, "message": "tenant_id must come from allowlist only"}

    return {"ok": True, "message": "voice_flow_a security checks ok"}


def load_profile() -> dict:
    return {"hint": "twilio-openai-bridge", "p50_ms": 10, "p95_ms": 50}


FEATURE = {
    "key": "voice_flow_a",
    "router": router,
    "enabled_env": "VOZ_FEATURE_VOICE_FLOW_A",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
