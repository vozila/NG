"""VOZLIA FILE PURPOSE
Purpose: Voice Flow A websocket adapter with deterministic barge-in/backlog controls.
Hot path: yes (WS media loop); logic is intentionally lightweight.
Feature flags: VOZ_FEATURE_VOICE_FLOW_A.
Failure mode: malformed events are ignored; WS remains alive until stop/disconnect.
"""

from __future__ import annotations

import base64
import json
import os
import time
from collections import deque
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.config import env_flag, is_debug
from core.logging import logger

router = APIRouter()

_ALLOWED_TENANT_KEYS = ("tenant_id", "tenant", "tenantId", "x_tenant_id")
_OPENAI_VAD_START_TYPES = {
    "input_audio_buffer.speech_started",
    "input_audio_buffer.speech_start",
    "conversation.user.speech.started",
}


@contextmanager
def _env_override(name: str, value: str | None) -> Iterator[None]:
    old = os.getenv(name)
    try:
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
        yield
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


def _int_env(name: str, default: int, *, min_value: int, max_value: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    if not raw.isdigit():
        return default
    value = int(raw)
    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str):
            out = value.strip()
            if out:
                return out
    return ""


def parse_twilio_start(d: dict[str, Any]) -> dict[str, str]:
    start = d.get("start") if isinstance(d.get("start"), dict) else {}
    custom = start.get("customParameters") if isinstance(start.get("customParameters"), dict) else {}

    tenant_id = ""
    for key in _ALLOWED_TENANT_KEYS:
        tenant_id = _first_str(custom.get(key))
        if tenant_id:
            break

    return {
        "stream_sid": _first_str(d.get("streamSid"), start.get("streamSid")),
        "call_sid": _first_str(start.get("callSid")),
        "from_number": _first_str(start.get("from"), custom.get("from_number"), custom.get("from")),
        "tenant_id": tenant_id,
    }


def parse_twilio_media(d: dict[str, Any]) -> bytes | None:
    media = d.get("media")
    if not isinstance(media, dict):
        return None
    payload = media.get("payload")
    if not isinstance(payload, str) or not payload:
        return None
    try:
        return base64.b64decode(payload, validate=True)
    except Exception:
        return None


def is_twilio_stop(d: dict[str, Any]) -> bool:
    return d.get("event") == "stop"


def is_openai_user_speech_start(d: dict[str, Any]) -> bool:
    event_type = d.get("type")
    if isinstance(event_type, str) and event_type in _OPENAI_VAD_START_TYPES:
        return True

    vad = d.get("vad")
    if isinstance(vad, dict) and vad.get("speech_started") is True:
        return True
    return False


def build_openai_cancel() -> dict[str, str]:
    return {"type": "response.cancel"}


def build_twilio_clear(stream_sid: str) -> dict[str, str]:
    return {"event": "clear", "streamSid": stream_sid}


class VoiceFlowAController:
    def __init__(
        self,
        *,
        send_openai: Callable[[dict[str, Any]], None],
        send_twilio: Callable[[dict[str, Any]], None],
        max_backlog_frames: int,
        pace_ms: int,
    ) -> None:
        self._send_openai = send_openai
        self._send_twilio = send_twilio
        self._max_backlog_frames = max_backlog_frames
        self._pace_ms = pace_ms

        self.stream_sid = ""
        self.assistant_speaking = False
        self._next_emit_ms = 0
        self._outbound: deque[str] = deque()
        self.dropped_frames = 0

    @property
    def backlog_frames(self) -> int:
        return len(self._outbound)

    def backlog_payloads(self) -> list[str]:
        return list(self._outbound)

    def set_stream_sid(self, stream_sid: str) -> None:
        self.stream_sid = (stream_sid or "").strip()

    def enqueue_assistant_frame(self, payload_b64: str) -> None:
        if not payload_b64:
            return
        self.assistant_speaking = True
        while len(self._outbound) >= self._max_backlog_frames:
            self._outbound.popleft()
            self.dropped_frames += 1
        self._outbound.append(payload_b64)

    def _barge_in(self) -> None:
        if not self.assistant_speaking:
            return

        self._send_openai(build_openai_cancel())
        if self.stream_sid:
            self._send_twilio(build_twilio_clear(self.stream_sid))

        self._outbound.clear()
        self.assistant_speaking = False

    def handle_openai_event(self, d: dict[str, Any]) -> None:
        if is_openai_user_speech_start(d):
            self._barge_in()

    def next_twilio_media(self, now_ms: int) -> dict[str, Any] | None:
        if not self.stream_sid:
            return None
        if not self._outbound:
            return None
        if now_ms < self._next_emit_ms:
            return None

        payload = self._outbound.popleft()
        self._next_emit_ms = now_ms + self._pace_ms
        if not self._outbound:
            self.assistant_speaking = False

        return {
            "event": "media",
            "streamSid": self.stream_sid,
            "media": {"payload": payload},
        }


def _new_controller(
    send_openai: Callable[[dict[str, Any]], None],
    send_twilio: Callable[[dict[str, Any]], None],
) -> VoiceFlowAController:
    return VoiceFlowAController(
        send_openai=send_openai,
        send_twilio=send_twilio,
        max_backlog_frames=_int_env("VOICE_OUTBOUND_MAX_FRAMES", 120, min_value=1, max_value=2000),
        pace_ms=_int_env("VOICE_OUTBOUND_PACE_MS", 20, min_value=1, max_value=1000),
    )


@router.websocket("/twilio/stream")
async def twilio_stream(websocket: WebSocket) -> None:
    await websocket.accept()

    def _send_openai(_event: dict[str, Any]) -> None:
        # OpenAI WS bridge is owned by a separate slice; this callback remains lightweight.
        return

    async def _send_twilio_async(event: dict[str, Any]) -> None:
        await websocket.send_text(json.dumps(event))

    twilio_outbound: list[dict[str, Any]] = []

    def _send_twilio(event: dict[str, Any]) -> None:
        twilio_outbound.append(event)

    state = _new_controller(send_openai=_send_openai, send_twilio=_send_twilio)

    try:
        while True:
            packet = await websocket.receive_json()
            if not isinstance(packet, dict):
                continue

            event = packet.get("event")
            if event == "start":
                start = parse_twilio_start(packet)
                state.set_stream_sid(start["stream_sid"])
                if is_debug():
                    logger.info(
                        "VOICE_FLOW_A_START stream_sid=%s call_sid=%s tenant_id=%s",
                        start["stream_sid"],
                        start["call_sid"],
                        start["tenant_id"],
                    )
            elif event == "media":
                _ = parse_twilio_media(packet)
                if is_debug() and state.stream_sid:
                    logger.info("VOICE_FLOW_A_MEDIA stream_sid=%s", state.stream_sid)
            elif is_twilio_stop(packet):
                if is_debug() and state.stream_sid:
                    logger.info("VOICE_FLOW_A_STOP stream_sid=%s", state.stream_sid)
                break

            now_ms = int(time.time() * 1000)
            media_event = state.next_twilio_media(now_ms)
            if media_event is not None:
                twilio_outbound.append(media_event)

            while twilio_outbound:
                await _send_twilio_async(twilio_outbound.pop(0))

    except WebSocketDisconnect:
        if is_debug():
            logger.info("VOICE_FLOW_A_DISCONNECT")


def _has_voice_route() -> bool:
    from core.app import create_app

    app = create_app()
    return any(
        getattr(route, "path", None) == "/twilio/stream"
        for route in app.routes
    )


def selftests() -> dict[str, Any]:
    start = parse_twilio_start(
        {
            "event": "start",
            "streamSid": "MZ111",
            "start": {
                "callSid": "CA111",
                "from": "+15550001111",
                "customParameters": {
                    "tenant_id": "tenant-a",
                    "ignored": "x",
                },
            },
        }
    )
    if start["stream_sid"] != "MZ111" or start["tenant_id"] != "tenant-a":
        return {"ok": False, "message": "twilio start parse failed"}

    raw = b"test-frame"
    payload = base64.b64encode(raw).decode("ascii")
    media = parse_twilio_media({"event": "media", "media": {"payload": payload}})
    if media != raw:
        return {"ok": False, "message": "twilio media parse failed"}

    if parse_twilio_media({"event": "media", "media": {"payload": "%%%"}}) is not None:
        return {"ok": False, "message": "invalid media payload accepted"}

    if not is_twilio_stop({"event": "stop"}):
        return {"ok": False, "message": "stop event parse failed"}

    with _env_override("VOZ_FEATURE_VOICE_FLOW_A", "0"):
        off_mounted = _has_voice_route()
    with _env_override("VOZ_FEATURE_VOICE_FLOW_A", "1"):
        on_mounted = _has_voice_route()

    if off_mounted or not on_mounted:
        return {"ok": False, "message": "route mounting failed for OFF/ON states"}

    return {"ok": True, "message": "voice_flow_a selftests ok"}


def security_checks() -> dict[str, Any]:
    default_off = env_flag("VOZ_FEATURE_VOICE_FLOW_A", "0") is False
    tenant_ok = parse_twilio_start(
        {
            "event": "start",
            "start": {
                "customParameters": {
                    "tenant_id": "good",
                    "malicious_tenant": "bad",
                }
            },
        }
    )["tenant_id"] == "good"

    if not default_off:
        return {"ok": False, "message": "VOZ_FEATURE_VOICE_FLOW_A must default OFF"}
    if not tenant_ok:
        return {"ok": False, "message": "tenant_id extraction not allowlist-only"}
    return {"ok": True, "message": "voice_flow_a security checks ok"}


def load_profile() -> dict[str, Any]:
    return {"hint": "ws-voice-hot-path", "p50_ms": 10, "p95_ms": 50}


FEATURE = {
    "key": "voice_flow_a",
    "router": router,
    "enabled_env": "VOZ_FEATURE_VOICE_FLOW_A",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
