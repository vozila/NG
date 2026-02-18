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

# --- Env-configurable knobs (safe defaults) ----------------------------------

# Start “thinking audio” only after the wait has lasted at least this long.
VOICE_WAIT_SOUND_TRIGGER_MS = int(os.getenv("VOICE_WAIT_SOUND_TRIGGER_MS", "800") or 800)

# Master kill-switch for aux-lane chime audio (default OFF to avoid regressions).
VOICE_WAIT_CHIME_ENABLED = env_flag("VOICE_WAIT_CHIME_ENABLED", "0")

# Periodic chime loop settings (Option A): short beep repeated every ~1.2–1.8s.
VOICE_WAIT_CHIME_PERIOD_MS = int(os.getenv("VOICE_WAIT_CHIME_PERIOD_MS", "1500") or 1500)
VOICE_WAIT_CHIME_BEEP_MS = int(os.getenv("VOICE_WAIT_CHIME_BEEP_MS", "120") or 120)

# 8kHz mu-law: Twilio Media Streams uses 20ms frames => 160 bytes.
_TWILIO_SAMPLE_RATE_HZ = 8000
_TWILIO_FRAME_MS = 20
_TWILIO_FRAME_BYTES = int(_TWILIO_SAMPLE_RATE_HZ * (_TWILIO_FRAME_MS / 1000.0))

# OpenAI Realtime bridge (default OFF; independent rollback from route gate).
VOZ_FLOW_A_OPENAI_BRIDGE = env_flag("VOZ_FLOW_A_OPENAI_BRIDGE", "0")
VOZ_OPENAI_REALTIME_MODEL = os.getenv("VOZ_OPENAI_REALTIME_MODEL", "gpt-realtime") or "gpt-realtime"
VOZ_OPENAI_REALTIME_VOICE = os.getenv("VOZ_OPENAI_REALTIME_VOICE", "marin") or "marin"
VOZ_OPENAI_REALTIME_INSTRUCTIONS = os.getenv("VOZ_OPENAI_REALTIME_INSTRUCTIONS")
OPENAI_REALTIME_URL_BASE = "wss://api.openai.com/v1/realtime"

# Main lane buffering/pacing safety for Twilio outbound.
VOICE_MAIN_MAX_FRAMES = int(os.getenv("VOICE_MAIN_MAX_FRAMES", "200") or 200)

# Twilio inbound -> OpenAI event queue cap.
VOICE_OPENAI_IN_Q_MAX = int(os.getenv("VOICE_OPENAI_IN_Q_MAX", "200") or 200)

_TENANT_ID_ALLOWLIST = ("tenant_id",)
_TENANT_MODE_ALLOWLIST = ("tenant_mode",)
_RID_ALLOWLIST = ("rid",)


# --- Twilio event parsing helpers (pure) -------------------------------------

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

    tenant_mode = None
    for k in _TENANT_MODE_ALLOWLIST:
        tenant_mode = _clean_str(custom_obj.get(k))
        if tenant_mode:
            break

    rid = None
    for k in _RID_ALLOWLIST:
        rid = _clean_str(custom_obj.get(k))
        if rid:
            break
    rid = rid or _clean_str(start_obj.get("callSid")) or _clean_str(d.get("callSid"))

    return {
        "streamSid": _clean_str(start_obj.get("streamSid")) or _clean_str(d.get("streamSid")),
        "callSid": _clean_str(start_obj.get("callSid")) or _clean_str(d.get("callSid")),
        "from_number": (
            _clean_str(start_obj.get("from"))
            or _clean_str(custom_obj.get("from_number"))
        ),
        "tenant_id": tenant_id,
        "tenant_mode": tenant_mode,
        "rid": rid,
    }


def parse_twilio_media(d: dict) -> bytes | None:
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


def is_twilio_stop(d: dict) -> bool:
    return d.get("event") == "stop"


# --- Deterministic waiting-audio controller (no network / DB) ----------------

LaneName = Literal["main", "aux"]


@dataclass
class OutgoingAudioBuffers:
    """Two independent audio lanes.

    - main: assistant speech (OpenAI Realtime audio deltas in future)
    - aux:  “thinking audio” comfort tone (cancelable, does not clear main)
    """

    main: deque[bytes] = field(default_factory=deque)
    aux: deque[bytes] = field(default_factory=deque)


def _clear_deque(dq: deque[bytes]) -> None:
    dq.clear()


def pick_next_outgoing_frame(
    buffers: OutgoingAudioBuffers, *, thinking_audio_active: bool
) -> tuple[LaneName, bytes] | None:
    """Single, testable routing rule:
    - main speech always wins
    - aux is only used when thinking_audio_active and main is empty
    """
    if buffers.main:
        return ("main", buffers.main.popleft())
    if thinking_audio_active and buffers.aux:
        return ("aux", buffers.aux.popleft())
    return None


def _linear16_to_mulaw(sample: int) -> int:
    """Convert signed 16-bit PCM sample -> G.711 mu-law byte.

    This is a tiny deterministic encoder to generate the comfort tone once at import time.
    """
    # Standard constants.
    bias = 0x84
    clip = 32635

    sign = 0x80 if sample < 0 else 0
    if sample < 0:
        sample = -sample
    if sample > clip:
        sample = clip

    sample += bias

    exponent = 7
    mask = 0x4000
    while exponent > 0 and (sample & mask) == 0:
        exponent -= 1
        mask >>= 1

    mantissa = (sample >> (exponent + 3)) & 0x0F
    ulaw = ~(sign | (exponent << 4) | mantissa) & 0xFF
    return ulaw


def _mulaw_silence_byte() -> int:
    # In G.711 mu-law, 0xFF is commonly used for silence (zero amplitude).
    return 0xFF


def _generate_mulaw_beep_frames(
    *,
    hz: int = 440,
    beep_ms: int = VOICE_WAIT_CHIME_BEEP_MS,
    sample_rate_hz: int = _TWILIO_SAMPLE_RATE_HZ,
    frame_bytes: int = _TWILIO_FRAME_BYTES,
    amplitude: int = 4500,
) -> list[bytes]:
    """Generate a short, low-amplitude mu-law beep as a list of Twilio-sized frames.

    Precomputed once at import time to keep hot path clean.
    """
    n = max(1, int(sample_rate_hz * (beep_ms / 1000.0)))
    out = bytearray()
    for i in range(n):
        # Low amplitude sine to avoid intrusion.
        s = int(amplitude * math.sin(2.0 * math.pi * hz * (i / sample_rate_hz)))
        out.append(_linear16_to_mulaw(s))

    # Pad to a multiple of frame size so every frame is exactly 20ms for Twilio.
    pad = (-len(out)) % frame_bytes
    if pad:
        out.extend([_mulaw_silence_byte()] * pad)

    frames: list[bytes] = []
    for off in range(0, len(out), frame_bytes):
        frames.append(bytes(out[off : off + frame_bytes]))
    return frames


_DEFAULT_CHIME_FRAMES: list[bytes] = _generate_mulaw_beep_frames()


@dataclass(frozen=True)
class WaitingAudioConfig:
    enabled: bool
    trigger_ms: int
    period_ms: int
    chime_frames: tuple[bytes, ...]


@dataclass
class WaitingAudioController:
    """Pure state machine for “waiting/thinking audio”.

    Core idea: treat thinking audio as a first-class state and *separate lane*.

    Behavior:
    - wait_start() marks the start of a tool/skill wait.
    - After trigger_ms of waiting with no suppression, thinking_audio_active becomes True.
    - While active, update() enqueues a short chime into buffers.aux every period_ms.
    - on_user_speech_started() immediately stops chime and clears aux (does NOT clear main).
    - wait_end() stops chime and resets suppression.
    """

    cfg: WaitingAudioConfig
    waiting_active: bool = False
    waiting_started_ms: int | None = None
    thinking_audio_active: bool = False
    # If caller speaks while we are waiting, we suppress thinking audio until wait_end().
    suppressed_until_end: bool = False
    _next_chime_due_ms: int = 0

    def wait_start(self, *, now_ms: int) -> None:
        self.waiting_active = True
        self.waiting_started_ms = now_ms
        self.suppressed_until_end = False
        self._next_chime_due_ms = 0
        self.thinking_audio_active = False

    def wait_end(self, *, buffers: OutgoingAudioBuffers | None = None) -> None:
        self.waiting_active = False
        self.waiting_started_ms = None
        self.suppressed_until_end = False
        self._next_chime_due_ms = 0
        self.thinking_audio_active = False
        if buffers is not None:
            _clear_deque(buffers.aux)

    def on_user_speech_started(self, *, buffers: OutgoingAudioBuffers | None = None) -> None:
        # Stop the aux lane instantly; do NOT clear main.
        self.thinking_audio_active = False
        self.suppressed_until_end = True
        self._next_chime_due_ms = 0
        if buffers is not None:
            _clear_deque(buffers.aux)

    def _should_think(self, *, now_ms: int) -> bool:
        if not self.cfg.enabled:
            return False
        if not self.waiting_active or self.suppressed_until_end:
            return False
        if self.waiting_started_ms is None:
            return False
        return (now_ms - self.waiting_started_ms) >= self.cfg.trigger_ms

    def update(self, *, now_ms: int, buffers: OutgoingAudioBuffers) -> None:
        """Advance state and enqueue aux chime frames if due.

        Designed to be safe to call frequently (e.g., from sender loop).
        """
        want_thinking = self._should_think(now_ms=now_ms)
        if not want_thinking:
            if self.thinking_audio_active:
                # We were thinking and now shouldn't be: stop + clear aux.
                self.thinking_audio_active = False
                _clear_deque(buffers.aux)
            return

        # We are in THINKING.
        if not self.thinking_audio_active:
            self.thinking_audio_active = True
            self._next_chime_due_ms = now_ms

        # Only enqueue a new chime when due and the aux buffer is empty-ish
        # (keeps backlog bounded and cancelable).
        if now_ms >= self._next_chime_due_ms and len(buffers.aux) == 0:
            buffers.aux.extend(self.cfg.chime_frames)
            self._next_chime_due_ms = now_ms + self.cfg.period_ms


def _build_waiting_audio_config_from_env() -> WaitingAudioConfig:
    trigger_ms = VOICE_WAIT_SOUND_TRIGGER_MS
    period_ms = VOICE_WAIT_CHIME_PERIOD_MS
    # Clamp to avoid silly values that could flood the loop.
    trigger_ms = max(0, min(trigger_ms, 10_000))
    period_ms = max(200, min(period_ms, 10_000))
    return WaitingAudioConfig(
        enabled=VOICE_WAIT_CHIME_ENABLED,
        trigger_ms=trigger_ms,
        period_ms=period_ms,
        chime_frames=tuple(_DEFAULT_CHIME_FRAMES),
    )


# --- Helpers for tests (env isolation) ---------------------------------------

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


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


def _build_openai_session_update(*, voice: str, instructions: str | None) -> dict[str, Any]:
    session: dict[str, Any] = {
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


def _build_twilio_clear_message(stream_sid: str) -> dict[str, Any]:
    return {"event": "clear", "streamSid": stream_sid}


def _chunk_mulaw_frames(
    remainder: bytearray, chunk: bytes, *, frame_bytes: int = _TWILIO_FRAME_BYTES
) -> list[bytes]:
    if chunk:
        remainder.extend(chunk)
    out: list[bytes] = []
    while len(remainder) >= frame_bytes:
        out.append(bytes(remainder[:frame_bytes]))
        del remainder[:frame_bytes]
    return out


def _drain_main_lane_with_cap(buffers: OutgoingAudioBuffers, *, max_frames: int) -> int:
    dropped = 0
    while len(buffers.main) > max_frames:
        buffers.main.popleft()
        dropped += 1
    return dropped


def _enqueue_audio_append(q: asyncio.Queue[str], payload_b64: str) -> None:
    msg = json.dumps({"type": "input_audio_buffer.append", "audio": payload_b64})
    if q.qsize() >= q.maxsize:
        try:
            q.get_nowait()  # drop oldest
        except asyncio.QueueEmpty:
            pass
    try:
        q.put_nowait(msg)
    except asyncio.QueueFull:
        pass


async def _twilio_send_json(
    websocket: WebSocket, send_lock: asyncio.Lock, msg: dict[str, Any]
) -> bool:
    try:
        async with send_lock:
            await websocket.send_text(json.dumps(msg))
        return True
    except Exception:
        return False


async def _send_twilio_clear(
    websocket: WebSocket,
    *,
    send_lock: asyncio.Lock,
    stream_sid_ref: dict[str, str | None],
) -> None:
    stream_sid = stream_sid_ref.get("streamSid")
    if not stream_sid:
        return
    sent = await _twilio_send_json(websocket, send_lock, _build_twilio_clear_message(stream_sid))
    if sent and is_debug():
        logger.info("TWILIO_CLEAR_SENT streamSid=%s", stream_sid)


async def _openai_sender_loop(
    openai_ws: Any, *, in_q: asyncio.Queue[str], stop: asyncio.Event
) -> None:
    while not stop.is_set():
        try:
            outbound = await asyncio.wait_for(in_q.get(), timeout=0.2)
        except asyncio.TimeoutError:
            continue
        try:
            await openai_ws.send(outbound)
        except Exception:
            break


async def _openai_receiver_loop(
    openai_ws: Any,
    *,
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    stream_sid_ref: dict[str, str | None],
    buffers: OutgoingAudioBuffers,
    wait_ctl: WaitingAudioController,
    stop: asyncio.Event,
) -> None:
    remainder = bytearray()
    audio_delta_count = 0
    while not stop.is_set():
        try:
            raw = await openai_ws.recv()
        except Exception:
            break
        if not isinstance(raw, str):
            continue
        try:
            evt = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(evt, dict):
            continue

        evt_type = evt.get("type")
        if evt_type == "session.updated":
            if is_debug():
                logger.info("OPENAI_SESSION_UPDATED")
            continue

        if evt_type == "response.done":
            if is_debug():
                logger.info("OPENAI_RESPONSE_DONE")
            continue

        if evt_type == "error":
            if is_debug():
                logger.info("OPENAI_ERROR evt=%s", json.dumps(evt))
            continue

        if evt_type == "input_audio_buffer.speech_started":
            buffers.main.clear()
            wait_ctl.on_user_speech_started(buffers=buffers)
            await _send_twilio_clear(
                websocket, send_lock=send_lock, stream_sid_ref=stream_sid_ref
            )
            continue

        if evt_type != "response.output_audio.delta":
            continue

        delta = evt.get("delta")
        if not isinstance(delta, str):
            continue
        try:
            audio_chunk = base64.b64decode(delta, validate=True)
        except (ValueError, binascii.Error):
            continue

        for frame in _chunk_mulaw_frames(remainder, audio_chunk):
            buffers.main.append(frame)
        dropped = _drain_main_lane_with_cap(
            buffers, max_frames=max(1, VOICE_MAIN_MAX_FRAMES)
        )
        if dropped > 0:
            await _send_twilio_clear(
                websocket, send_lock=send_lock, stream_sid_ref=stream_sid_ref
            )
        audio_delta_count += 1
        if is_debug():
            if audio_delta_count == 1 or audio_delta_count % 50 == 0 or dropped > 0:
                logger.info(
                    "OPENAI_AUDIO_DELTA count=%s buffered_main=%s dropped=%s",
                    audio_delta_count,
                    len(buffers.main),
                    dropped,
                )


async def _connect_openai_ws(*, api_key: str, model: str) -> Any:
    try:
        import websockets
    except ImportError:
        return None

    url = f"{OPENAI_REALTIME_URL_BASE}?model={quote_plus(model)}"
    auth = [("Authorization", f"Bearer {api_key}")]
    try:
        return await websockets.connect(url, additional_headers=auth)
    except TypeError:
        # Compatibility with older websockets signatures.
        return await websockets.connect(url, extra_headers=auth)


async def _start_openai_bridge(
    *,
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    stream_sid_ref: dict[str, str | None],
    buffers: OutgoingAudioBuffers,
    wait_ctl: WaitingAudioController,
    stop: asyncio.Event,
) -> tuple[Any, asyncio.Queue[str], asyncio.Task[None], asyncio.Task[None]] | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        if is_debug():
            logger.info("OPENAI_BRIDGE_DISABLED reason=missing_api_key")
        return None

    ws = await _connect_openai_ws(api_key=api_key, model=VOZ_OPENAI_REALTIME_MODEL)
    if ws is None:
        if is_debug():
            logger.info("OPENAI_BRIDGE_DISABLED reason=missing_websockets_lib")
        return None

    if is_debug():
        logger.info("OPENAI_WS_CONNECTED")

    in_q: asyncio.Queue[str] = asyncio.Queue(maxsize=max(1, VOICE_OPENAI_IN_Q_MAX))
    sender_task = asyncio.create_task(_openai_sender_loop(ws, in_q=in_q, stop=stop))
    receiver_task = asyncio.create_task(
        _openai_receiver_loop(
            ws,
            websocket=websocket,
            send_lock=send_lock,
            stream_sid_ref=stream_sid_ref,
            buffers=buffers,
            wait_ctl=wait_ctl,
            stop=stop,
        )
    )

    session_msg = _build_openai_session_update(
        voice=VOZ_OPENAI_REALTIME_VOICE,
        instructions=VOZ_OPENAI_REALTIME_INSTRUCTIONS,
    )
    await ws.send(json.dumps(session_msg))
    if is_debug():
        logger.info("OPENAI_SESSION_UPDATE_SENT")

    return ws, in_q, sender_task, receiver_task


async def _ws_sender_loop(websocket: WebSocket, *, stream_sid_ref: dict[str, str | None],
                          send_lock: asyncio.Lock, buffers: OutgoingAudioBuffers,
                          wait_ctl: WaitingAudioController, stop: asyncio.Event) -> None:
    """Outbound loop: prefer main lane; otherwise use aux lane when thinking.

    Main and aux frames are both paced to Twilio's 20ms cadence to avoid sender bursts.
    """
    while websocket.client_state == WebSocketState.CONNECTED and not stop.is_set():
        stream_sid = stream_sid_ref.get("streamSid")
        if not stream_sid:
            await asyncio.sleep(0.01)
            continue

        now_ms = _now_ms()
        wait_ctl.update(now_ms=now_ms, buffers=buffers)

        picked = pick_next_outgoing_frame(
            buffers, thinking_audio_active=wait_ctl.thinking_audio_active
        )
        if picked is None:
            await asyncio.sleep(0.02)
            continue

        lane, frame = picked
        payload = base64.b64encode(frame).decode("ascii")
        msg = {"event": "media", "streamSid": stream_sid, "media": {"payload": payload}}
        sent = await _twilio_send_json(websocket, send_lock, msg)
        if not sent:
            break

        _ = lane
        await asyncio.sleep(_TWILIO_FRAME_MS / 1000.0)


@router.websocket("/twilio/stream")
async def twilio_stream(websocket: WebSocket) -> None:
    await websocket.accept()

    stream_sid_ref: dict[str, str | None] = {"streamSid": None}
    call_sid: str | None = None
    from_number: str | None = None
    session_ctx: dict[str, str | None] = {
        "tenant_id": None,
        "tenant_mode": None,
        "rid": None,
    }

    buffers = OutgoingAudioBuffers()
    wait_ctl = WaitingAudioController(cfg=_build_waiting_audio_config_from_env())
    send_lock = asyncio.Lock()

    stop = asyncio.Event()
    sender_task = asyncio.create_task(
        _ws_sender_loop(
            websocket,
            stream_sid_ref=stream_sid_ref,
            send_lock=send_lock,
            buffers=buffers,
            wait_ctl=wait_ctl,
            stop=stop,
        )
    )
    openai_ws: Any = None
    openai_in_q: asyncio.Queue[str] | None = None
    openai_sender_task: asyncio.Task[None] | None = None
    openai_receiver_task: asyncio.Task[None] | None = None
    audio_in_count = 0

    def notify_wait_start(reason: str) -> None:
        # NOTE: the controller contains the real logic; this wrapper is for breadcrumbs only.
        if wait_ctl.waiting_active:
            return
        wait_ctl.wait_start(now_ms=_now_ms())
        if is_debug():
            logger.info(
                "VOICE_WAIT_START reason=%s streamSid=%s callSid=%s",
                reason,
                stream_sid_ref.get("streamSid"),
                call_sid,
            )

    def notify_wait_end() -> None:
        if not wait_ctl.waiting_active:
            return
        started_ms = wait_ctl.waiting_started_ms or _now_ms()
        elapsed = _now_ms() - started_ms
        wait_ctl.wait_end(buffers=buffers)
        if is_debug():
            logger.info(
                "VOICE_WAIT_END elapsed_ms=%s streamSid=%s callSid=%s",
                elapsed,
                stream_sid_ref.get("streamSid"),
                call_sid,
            )

    try:
        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                break

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                if is_debug():
                    logger.info("TWILIO_WS_BAD_JSON")
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
                stream_sid_ref["streamSid"] = start_info["streamSid"]
                call_sid = start_info["callSid"]
                from_number = start_info["from_number"]
                session_ctx["tenant_id"] = start_info["tenant_id"]
                session_ctx["tenant_mode"] = start_info["tenant_mode"]
                session_ctx["rid"] = start_info["rid"] or call_sid
                if is_debug():
                    logger.info(
                        "TWILIO_WS_START streamSid=%s callSid=%s from=%s tenant=%s tenant_mode=%s rid=%s",
                        stream_sid_ref["streamSid"],
                        call_sid,
                        from_number,
                        session_ctx["tenant_id"],
                        session_ctx["tenant_mode"],
                        session_ctx["rid"],
                    )
                    logger.info(
                        "VOICE_FLOW_A_START tenant_id=%s tenant_mode=%s rid=%s",
                        session_ctx["tenant_id"],
                        session_ctx["tenant_mode"],
                        session_ctx["rid"],
                    )

                if VOZ_FLOW_A_OPENAI_BRIDGE and openai_ws is None:
                    try:
                        started = await _start_openai_bridge(
                            websocket=websocket,
                            send_lock=send_lock,
                            stream_sid_ref=stream_sid_ref,
                            buffers=buffers,
                            wait_ctl=wait_ctl,
                            stop=stop,
                        )
                    except Exception as exc:
                        started = None
                        if is_debug():
                            logger.info("OPENAI_CONNECT_FAILED err=%s", exc)
                    if started is not None:
                        openai_ws, openai_in_q, openai_sender_task, openai_receiver_task = started
                continue

            if event == "media":
                media_bytes = parse_twilio_media(data)
                if media_bytes is None:
                    if is_debug():
                        logger.info(
                            "TWILIO_WS_MEDIA_INVALID streamSid=%s",
                            stream_sid_ref["streamSid"],
                        )
                    continue

                if openai_in_q is not None:
                    _enqueue_audio_append(openai_in_q, base64.b64encode(media_bytes).decode("ascii"))
                    audio_in_count += 1
                    if is_debug():
                        if audio_in_count == 1 or audio_in_count % 50 == 0:
                            logger.info(
                                "OPENAI_AUDIO_IN count=%s qsize=%s",
                                audio_in_count,
                                openai_in_q.qsize(),
                            )

                # Example integration point: once routing/skills exist, call notify_wait_start()
                # when a tool begins and notify_wait_end() when it completes.
                continue

            if is_twilio_stop(data):
                if is_debug():
                    logger.info(
                        "TWILIO_WS_STOP streamSid=%s callSid=%s",
                        stream_sid_ref["streamSid"],
                        call_sid,
                    )
                notify_wait_end()
                break

    finally:
        notify_wait_end()
        stop.set()
        if openai_ws is not None:
            try:
                await openai_ws.close()
            except Exception:
                pass
        try:
            await sender_task
        except Exception:
            pass
        if openai_sender_task is not None:
            try:
                await openai_sender_task
            except Exception:
                pass
        if openai_receiver_task is not None:
            try:
                await openai_receiver_task
            except Exception:
                pass

        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()

        _ = from_number
        _ = session_ctx
        _ = notify_wait_start


# --- Local (deterministic) checks used by selftests() -------------------------

def _has_ws_route(app: FastAPI, path: str) -> bool:
    return any(getattr(route, "path", None) == path for route in app.routes)


# --- Feature contract hooks --------------------------------------------------

def selftests() -> dict:
    # Parsers
    start_evt = {
        "event": "start",
        "start": {
            "streamSid": "MZ123",
            "callSid": "CA123",
            "customParameters": {
                "tenant_id": " tenant-a ",
                "tenant": "blocked",
                "from_number": " +15551234567 ",
            },
        },
    }
    start_parsed = parse_twilio_start(start_evt)
    if start_parsed != {
        "streamSid": "MZ123",
        "callSid": "CA123",
        "from_number": "+15551234567",
        "tenant_id": "tenant-a",
        "tenant_mode": None,
        "rid": "CA123",
    }:
        return {"ok": False, "message": "parse_twilio_start failed"}

    if parse_twilio_start({"event": "start", "start": {"customParameters": {"tenant": "x"}}})[
        "tenant_id"
    ] is not None:
        return {"ok": False, "message": "tenant_id allowlist failed"}

    mode_ok = parse_twilio_start(
        {
            "event": "start",
            "start": {"callSid": "CA_MODE", "customParameters": {"tenant_mode": "dedicated"}},
        }
    )["tenant_mode"]
    if mode_ok != "dedicated":
        return {"ok": False, "message": "tenant_mode extraction failed"}

    rid_ok = parse_twilio_start(
        {
            "event": "start",
            "start": {"callSid": "CA_RID", "customParameters": {"rid": "RID123"}},
        }
    )["rid"]
    if rid_ok != "RID123":
        return {"ok": False, "message": "rid extraction failed"}

    if parse_twilio_media({"event": "media", "media": {"payload": "aGVsbG8="}}) != b"hello":
        return {"ok": False, "message": "parse_twilio_media valid payload failed"}

    if parse_twilio_media({"event": "media", "media": {"payload": "*"}}) is not None:
        return {"ok": False, "message": "parse_twilio_media malformed payload failed"}

    if not is_twilio_stop({"event": "stop"}) or is_twilio_stop({"event": "media"}):
        return {"ok": False, "message": "is_twilio_stop failed"}

    # Waiting-audio controller (pure, deterministic)
    buffers = OutgoingAudioBuffers()
    cfg = WaitingAudioConfig(
        enabled=True,
        trigger_ms=800,
        period_ms=1500,
        chime_frames=(b"a" * _TWILIO_FRAME_BYTES, b"b" * _TWILIO_FRAME_BYTES),
    )
    ctl = WaitingAudioController(cfg=cfg)
    ctl.wait_start(now_ms=0)
    ctl.update(now_ms=799, buffers=buffers)
    if ctl.thinking_audio_active or buffers.aux:
        return {"ok": False, "message": "waiting audio started too early"}
    ctl.update(now_ms=800, buffers=buffers)
    if not ctl.thinking_audio_active or len(buffers.aux) != 2:
        return {"ok": False, "message": "waiting audio did not enqueue chime on trigger"}

    ctl.on_user_speech_started(buffers=buffers)
    if ctl.thinking_audio_active or buffers.aux:
        return {"ok": False, "message": "speech_started did not stop/clear aux"}

    # Bridge helpers (pure, deterministic)
    remainder = bytearray()
    frames1 = _chunk_mulaw_frames(remainder, b"x" * 200)
    frames2 = _chunk_mulaw_frames(remainder, b"y" * 120)
    if len(frames1) != 1 or len(frames2) != 1:
        return {"ok": False, "message": "mu-law frame chunking failed"}
    if len(frames1[0]) != _TWILIO_FRAME_BYTES or len(frames2[0]) != _TWILIO_FRAME_BYTES:
        return {"ok": False, "message": "mu-law frame size invariant failed"}

    clear_msg = _build_twilio_clear_message("MZ_TEST")
    if clear_msg != {"event": "clear", "streamSid": "MZ_TEST"}:
        return {"ok": False, "message": "twilio clear builder failed"}

    session_update = _build_openai_session_update(voice="marin", instructions=None)
    audio_cfg = session_update.get("session", {}).get("audio", {})
    if audio_cfg.get("input", {}).get("format", {}).get("type") != "audio/pcmu":
        return {"ok": False, "message": "session.update input format must be audio/pcmu"}
    if audio_cfg.get("output", {}).get("format", {}).get("type") != "audio/pcmu":
        return {"ok": False, "message": "session.update output format must be audio/pcmu"}

    # Route mounting (flag gating)
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

    tenant_ok = parse_twilio_start(
        {
            "event": "start",
            "start": {"customParameters": {"tenant_id": " tenant-a ", "tenant": "wrong"}},
        }
    )["tenant_id"]
    if tenant_ok != "tenant-a":
        return {"ok": False, "message": "tenant_id strip/allowlist failed"}

    tenant_blocked = parse_twilio_start(
        {"event": "start", "start": {"customParameters": {"tenant": "wrong"}}}
    )["tenant_id"]
    if tenant_blocked is not None:
        return {"ok": False, "message": "tenant_id must come from allowlist only"}

    rid_fallback = parse_twilio_start({"event": "start", "start": {"callSid": "CA_FALLBACK"}})["rid"]
    if rid_fallback != "CA_FALLBACK":
        return {"ok": False, "message": "rid fallback to callSid failed"}

    # Aux chime must default OFF unless explicitly enabled.
    if os.getenv("VOICE_WAIT_CHIME_ENABLED") is None and VOICE_WAIT_CHIME_ENABLED:
        return {"ok": False, "message": "VOICE_WAIT_CHIME_ENABLED must default OFF"}

    # Bridge must default OFF unless explicitly enabled.
    if os.getenv("VOZ_FLOW_A_OPENAI_BRIDGE") is None and VOZ_FLOW_A_OPENAI_BRIDGE:
        return {"ok": False, "message": "VOZ_FLOW_A_OPENAI_BRIDGE must default OFF"}

    return {"ok": True, "message": "voice_flow_a security checks ok"}


def load_profile() -> dict:
    return {"hint": "ws-parse", "p50_ms": 10, "p95_ms": 50}


FEATURE = {
    "key": "voice_flow_a",
    "router": router,
    "enabled_env": "VOZ_FEATURE_VOICE_FLOW_A",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
