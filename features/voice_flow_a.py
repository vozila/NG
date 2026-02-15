"""VOZLIA FILE PURPOSE
Purpose: Twilio Media Streams skeleton for Voice Flow A (Slice A+B).
Hot path: yes (websocket loop must stay lightweight and deterministic).
Feature flags: VOZ_FEATURE_VOICE_FLOW_A, VOZLIA_DEBUG.
Failure mode: malformed events are ignored; connection remains stable.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from core.config import env_flag, is_debug
from core.feature_loader import load_features
from core.logging import logger

router = APIRouter()

VOICE_WAIT_SOUND_TRIGGER_MS = int(os.getenv("VOICE_WAIT_SOUND_TRIGGER_MS", "800") or 800)
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
    await websocket.accept()

    stream_sid: str | None = None
    call_sid: str | None = None
    from_number: str | None = None
    tenant_id: str | None = None

    waiting_audio_active: bool = False
    waiting_started_ms: int | None = None

    def notify_wait_start(reason: str) -> None:
        nonlocal waiting_audio_active, waiting_started_ms
        if waiting_audio_active:
            return
        waiting_audio_active = True
        waiting_started_ms = int(time.monotonic() * 1000)
        if is_debug():
            logger.info(
                "VOICE_WAIT_START reason=%s streamSid=%s callSid=%s", reason, stream_sid, call_sid
            )

    def notify_wait_end() -> None:
        nonlocal waiting_audio_active, waiting_started_ms
        if not waiting_audio_active:
            return
        elapsed = (
            int(time.monotonic() * 1000) - waiting_started_ms if waiting_started_ms is not None else 0
        )
        if is_debug():
            logger.info(
                "VOICE_WAIT_END elapsed_ms=%s streamSid=%s callSid=%s",
                elapsed,
                stream_sid,
                call_sid,
            )
        waiting_audio_active = False
        waiting_started_ms = None

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
                stream_sid = start_info["streamSid"]
                call_sid = start_info["callSid"]
                from_number = start_info["from_number"]
                tenant_id = start_info["tenant_id"]
                if is_debug():
                    logger.info(
                        "TWILIO_WS_START streamSid=%s callSid=%s from=%s tenant=%s",
                        stream_sid,
                        call_sid,
                        from_number,
                        tenant_id,
                    )
                continue

            if event == "media":
                media_bytes = parse_twilio_media(data)
                if media_bytes is None:
                    if is_debug():
                        logger.info("TWILIO_WS_MEDIA_INVALID streamSid=%s", stream_sid)
                    continue
                _ = media_bytes

                if waiting_audio_active and waiting_started_ms is not None:
                    elapsed = int(time.monotonic() * 1000) - waiting_started_ms
                    if elapsed >= VOICE_WAIT_SOUND_TRIGGER_MS and is_debug():
                        logger.info(
                            "VOICE_WAIT_THRESHOLD_REACHED elapsed_ms=%s threshold_ms=%s",
                            elapsed,
                            VOICE_WAIT_SOUND_TRIGGER_MS,
                        )
                continue

            if is_twilio_stop(data):
                if is_debug():
                    logger.info("TWILIO_WS_STOP streamSid=%s callSid=%s", stream_sid, call_sid)
                notify_wait_end()
                break

    finally:
        notify_wait_end()
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()

        _ = from_number
        _ = tenant_id
        _ = notify_wait_start


def _has_ws_route(app: FastAPI, path: str) -> bool:
    for route in app.routes:
        if getattr(route, "path", None) == path:
            return True
    return False


def selftests() -> dict:
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
    }:
        return {"ok": False, "message": "parse_twilio_start failed"}

    if parse_twilio_start({"event": "start", "start": {"customParameters": {"tenant": "x"}}})[
        "tenant_id"
    ] is not None:
        return {"ok": False, "message": "tenant_id allowlist failed"}

    if parse_twilio_media({"event": "media", "media": {"payload": "aGVsbG8="}}) != b"hello":
        return {"ok": False, "message": "parse_twilio_media valid payload failed"}

    if parse_twilio_media({"event": "media", "media": {"payload": "*"}}) is not None:
        return {"ok": False, "message": "parse_twilio_media malformed payload failed"}

    if not is_twilio_stop({"event": "stop"}) or is_twilio_stop({"event": "media"}):
        return {"ok": False, "message": "is_twilio_stop failed"}

    env_reset = {
        "VOZ_FEATURE_SAMPLE": "0",
        "VOZ_FEATURE_ADMIN_QUALITY": "0",
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
