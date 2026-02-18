"""VOZLIA FILE PURPOSE
Purpose: Twilio Media Streams handler for Voice Flow A (Slice A–D scaffolding), including a
  first-class “waiting/thinking audio” lane to avoid future regressions with barge-in.
Hot path: YES (WS audio path) — keep work per frame bounded.
Feature flags: VOZ_FEATURE_VOICE_FLOW_A, VOZ_FLOW_A_OPENAI_BRIDGE, VOZLIA_DEBUG.
Reads/Writes: reads env vars only in hot path; no DB calls here.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.config import env_flag, is_debug
from core.logging import logger

router = APIRouter()

# ---- Twilio media constants (G.711 μ-law / PCMU @ 8kHz) ----
_TWILIO_SAMPLE_RATE_HZ = 8000
_TWILIO_FRAME_MS = 20
_TWILIO_FRAME_BYTES = int(_TWILIO_SAMPLE_RATE_HZ * (_TWILIO_FRAME_MS / 1000.0))  # 160 bytes @ 20ms

# ---- Defaults / env ----
_DEFAULT_MAIN_MAX_FRAMES = 200
_DEFAULT_OPENAI_IN_Q_MAX = 200

# ---- Bounded waits/pacing ----
_MAIN_SLEEP_SEC = _TWILIO_FRAME_MS / 1000.0
_AUX_SLEEP_SEC = _TWILIO_FRAME_MS / 1000.0


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    try:
        return int(raw)
    except Exception:
        return default


def _log(msg: str) -> None:
    if is_debug():
        logger.info(msg)


@dataclass
class VoiceBuffers:
    # Two lanes: main (assistant audio) and aux (waiting/thinking audio)
    main: Deque[bytes]
    aux: Deque[bytes]

    # Remainder for chunking model audio into 160-byte frames
    remainder: bytearray

    # caps
    main_max_frames: int


class WaitingAudioController:
    """Controls aux lane playback and barge-in interruption.
    (MVP: just provides stop-on-user-speech hooks; actual waiting audio can be plugged in later.)
    """

    def __init__(self) -> None:
        self._aux_enabled = True

    def on_user_speech_started(self, *, buffers: VoiceBuffers) -> None:
        # Clear aux lane immediately on barge-in
        buffers.aux.clear()
        self._aux_enabled = False

    def on_model_speech_started(self) -> None:
        # Future: could stop aux when model begins speaking
        self._aux_enabled = False

    def on_model_speech_done(self) -> None:
        # Future: allow aux again after model finishes
        self._aux_enabled = True

    @property
    def aux_enabled(self) -> bool:
        return self._aux_enabled


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


def _build_openai_session_update(*, voice: str, instructions: str | None) -> dict[str, Any]:
    # OpenAI Realtime requires session.type="realtime" in session.update payloads.
    # Without it the server returns: missing_required_parameter 'session.type'.
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


# ----------------------------
# OpenAI Realtime bridge
# ----------------------------

async def _openai_ws_connect(*, model: str) -> Any:
    # websockets is a runtime dependency for this feature.
    import websockets  # type: ignore

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY missing")

    url = f"wss://api.openai.com/v1/realtime?model={model}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "OpenAI-Beta": "realtime=v1",
    }
    ws = await websockets.connect(url, extra_headers=headers)
    return ws


async def _openai_send_json(ws: Any, obj: dict[str, Any]) -> None:
    await ws.send(json.dumps(obj))


async def _openai_recv_json(ws: Any) -> dict[str, Any]:
    raw = await ws.recv()
    return json.loads(raw)


async def _twilio_sender_loop(
    twilio_ws: WebSocket,
    buffers: VoiceBuffers,
    wait_ctl: WaitingAudioController,
    *,
    stream_sid: str,
) -> None:
    """Sends audio to Twilio at ~20ms/frame, preferring main lane, then aux."""
    try:
        while True:
            frame: Optional[bytes] = None
            if buffers.main:
                frame = buffers.main.popleft()
                await asyncio.sleep(_MAIN_SLEEP_SEC)
            elif wait_ctl.aux_enabled and buffers.aux:
                frame = buffers.aux.popleft()
                await asyncio.sleep(_AUX_SLEEP_SEC)
            else:
                await asyncio.sleep(0.01)

            if frame is None:
                continue

            payload_b64 = base64.b64encode(frame).decode("ascii")
            msg = {"event": "media", "streamSid": stream_sid, "media": {"payload": payload_b64}}
            await twilio_ws.send_text(json.dumps(msg))
    except asyncio.CancelledError:
        return
    except Exception as e:
        _log(f"TWILIO_SENDER_ERROR err={e!r}")


async def _twilio_to_openai_loop(
    *,
    openai_ws: Any,
    in_q: "asyncio.Queue[str]",
) -> None:
    """Drains base64 μ-law frames (as strings) and forwards them to OpenAI."""
    count = 0
    try:
        while True:
            audio_b64 = await in_q.get()
            await _openai_send_json(openai_ws, {"type": "input_audio_buffer.append", "audio": audio_b64})
            count += 1
            if is_debug() and count in (1, 50, 100, 150, 200) or (is_debug() and count % 50 == 0):
                _log(f"OPENAI_AUDIO_IN count={count} qsize={in_q.qsize()}")
    except asyncio.CancelledError:
        return
    except Exception as e:
        _log(f"OPENAI_AUDIO_IN_LOOP_ERROR err={e!r}")


async def _openai_to_twilio_loop(
    *,
    openai_ws: Any,
    twilio_ws: WebSocket,
    buffers: VoiceBuffers,
    wait_ctl: WaitingAudioController,
    stream_sid: str,
) -> None:
    """Receives OpenAI events; pushes audio deltas to main lane; handles barge-in signals."""
    try:
        while True:
            evt = await _openai_recv_json(openai_ws)
            etype = evt.get("type")

            if etype == "error":
                _log(f"OPENAI_ERROR evt={evt!r}")
                continue

            if etype in ("session.updated", "session.created"):
                _log("OPENAI_SESSION_UPDATED")
                continue

            # Barge-in: caller started speaking; flush Twilio audio buffers.
            if etype == "input_audio_buffer.speech_started":
                buffers.main.clear()
                wait_ctl.on_user_speech_started(buffers=buffers)
                try:
                    await twilio_ws.send_text(json.dumps(_build_twilio_clear_message(stream_sid)))
                    _log("TWILIO_CLEAR_SENT")
                except Exception as e:
                    _log(f"TWILIO_CLEAR_SEND_FAILED err={e!r}")
                continue

            # Audio delta from model
            if etype == "response.output_audio.delta":
                delta_b64 = evt.get("delta")
                if not isinstance(delta_b64, str) or not delta_b64:
                    continue

                try:
                    chunk = base64.b64decode(delta_b64)
                except Exception:
                    continue

                frames = _chunk_mulaw_frames(buffers.remainder, chunk)
                if frames:
                    # Enforce bounded main queue size
                    for f in frames:
                        if len(buffers.main) >= buffers.main_max_frames:
                            # drop oldest to keep latency bounded
                            buffers.main.popleft()
                        buffers.main.append(f)
                if is_debug():
                    _log(f"OPENAI_AUDIO_DELTA frames={len(frames)} main_q={len(buffers.main)}")
                continue

            if etype == "response.done":
                _log("OPENAI_RESPONSE_DONE")
                continue

    except asyncio.CancelledError:
        return
    except Exception as e:
        _log(f"OPENAI_TO_TWILIO_LOOP_ERROR err={e!r}")


@router.websocket("/twilio/stream")
async def twilio_stream(ws: WebSocket) -> None:
    if not env_flag("VOZ_FEATURE_VOICE_FLOW_A"):
        await ws.close(code=1008)
        return

    await ws.accept()

    _log("TWILIO_WS_CONNECTED")

    # Runtime config
    bridge_enabled = env_flag("VOZ_FLOW_A_OPENAI_BRIDGE")
    openai_model = os.getenv("VOZ_OPENAI_REALTIME_MODEL", "gpt-realtime").strip() or "gpt-realtime"
    openai_voice = os.getenv("VOZ_OPENAI_REALTIME_VOICE", "marin").strip() or "marin"
    openai_instructions = os.getenv("VOZ_OPENAI_REALTIME_INSTRUCTIONS", "").strip() or None

    main_max_frames = _env_int("VOICE_MAIN_MAX_FRAMES", _DEFAULT_MAIN_MAX_FRAMES)
    openai_in_q_max = _env_int("VOICE_OPENAI_IN_Q_MAX", _DEFAULT_OPENAI_IN_Q_MAX)

    buffers = VoiceBuffers(
        main=deque(),
        aux=deque(),
        remainder=bytearray(),
        main_max_frames=main_max_frames,
    )
    wait_ctl = WaitingAudioController()

    stream_sid: str | None = None
    rid: str | None = None
    tenant_id: str | None = None
    tenant_mode: str | None = None

    # Bridge tasks
    sender_task: Optional[asyncio.Task] = None
    openai_in_task: Optional[asyncio.Task] = None
    openai_out_task: Optional[asyncio.Task] = None

    openai_ws: Any = None
    openai_in_q: "asyncio.Queue[str]" = asyncio.Queue(maxsize=openai_in_q_max)

    def _drop_oldest_put(q: "asyncio.Queue[str]", item: str) -> None:
        # Drop-oldest policy to keep memory bounded under load.
        try:
            q.put_nowait(item)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
            except Exception:
                pass
            try:
                q.put_nowait(item)
            except Exception:
                pass

    try:
        # Start Twilio sender immediately (it idles until frames exist)
        sender_task = asyncio.create_task(_twilio_sender_loop(ws, buffers, wait_ctl, stream_sid=""))

        while True:
            raw = await ws.receive_text()
            evt = json.loads(raw)
            event_type = evt.get("event")

            if event_type == "start":
                start = evt.get("start") or {}
                stream_sid = start.get("streamSid") or ""
                call_sid = start.get("callSid") or ""
                custom = start.get("customParameters") or {}

                tenant_id = custom.get("tenant_id")
                tenant_mode = custom.get("tenant_mode")
                rid = custom.get("rid") or call_sid

                from_number = custom.get("from_number")
                tenant = tenant_id

                # Patch sender with proper streamSid (restart task to keep it simple)
                if sender_task:
                    sender_task.cancel()
                sender_task = asyncio.create_task(_twilio_sender_loop(ws, buffers, wait_ctl, stream_sid=stream_sid))

                _log(
                    f"TWILIO_WS_START streamSid={stream_sid} callSid={call_sid} from={from_number} "
                    f"tenant={tenant} tenant_mode={tenant_mode} rid={rid}"
                )
                _log(f"VOICE_FLOW_A_START tenant_id={tenant_id} tenant_mode={tenant_mode} rid={rid}")

                if bridge_enabled:
                    try:
                        openai_ws = await _openai_ws_connect(model=openai_model)
                        _log("OPENAI_WS_CONNECTED")
                        await _openai_send_json(
                            openai_ws,
                            _build_openai_session_update(voice=openai_voice, instructions=openai_instructions),
                        )
                        _log("OPENAI_SESSION_UPDATE_SENT")
                        openai_in_task = asyncio.create_task(_twilio_to_openai_loop(openai_ws=openai_ws, in_q=openai_in_q))
                        openai_out_task = asyncio.create_task(
                            _openai_to_twilio_loop(
                                openai_ws=openai_ws,
                                twilio_ws=ws,
                                buffers=buffers,
                                wait_ctl=wait_ctl,
                                stream_sid=stream_sid,
                            )
                        )
                    except Exception as e:
                        _log(f"OPENAI_CONNECT_FAILED err={e!r}")

                continue

            if event_type == "media":
                if not bridge_enabled:
                    continue
                media = evt.get("media") or {}
                payload = media.get("payload")
                if isinstance(payload, str) and payload:
                    _drop_oldest_put(openai_in_q, payload)
                continue

            if event_type == "stop":
                stop = evt.get("stop") or {}
                _log(f"TWILIO_WS_STOP streamSid={stream_sid} callSid={stop.get('callSid')}")
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        _log(f"TWILIO_WS_ERROR err={e!r}")
    finally:
        for t in (openai_in_task, openai_out_task, sender_task):
            if t:
                t.cancel()
        try:
            if openai_ws is not None:
                await openai_ws.close()
        except Exception:
            pass
        try:
            await ws.close()
        except Exception:
            pass


# ---- Feature module contract ----

def selftests() -> dict[str, Any]:
    # Deterministic unit tests live in tests/test_voice_flow_a.py.
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
