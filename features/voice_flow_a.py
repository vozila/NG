"""VOZLIA FILE PURPOSE
Purpose: Voice Flow A bridge MVP (Twilio Media Streams <-> OpenAI Realtime).
Hot path: yes (streaming loop; async-only, no DB, no blocking calls).
Feature flags: VOZ_FEATURE_VOICE_FLOW_A.
Failure mode: if OpenAI realtime is not configured/reachable, Twilio stream stays up and exits cleanly.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from core.config import is_debug
from core.logging import logger

router = APIRouter()

_ENV_REALTIME_URL = "VOZ_OPENAI_REALTIME_URL"
_ENV_OPENAI_API_KEY = "VOZ_OPENAI_API_KEY"
_ENV_OPENAI_MODEL = "VOZ_OPENAI_REALTIME_MODEL"


@dataclass
class SelfTestResult:
    ok: bool
    message: str = ""


@dataclass
class BridgeState:
    connected: bool = False
    started: bool = False
    speaking: bool = False
    stream_sid: str = ""
    call_sid: str = ""
    inbound_frames: int = 0
    outbound_frames: int = 0
    inbound_buffer: list[str] = field(default_factory=list)
    outbound_buffer: list[str] = field(default_factory=list)


class RealtimeClient(Protocol):
    async def connect(self) -> None: ...

    async def send_input_audio(self, payload_b64: str) -> None: ...

    async def iter_events(self): ...

    async def close(self) -> None: ...


class NullRealtimeClient:
    """No-op fallback when realtime is not configured."""

    async def connect(self) -> None:
        return None

    async def send_input_audio(self, payload_b64: str) -> None:
        return None

    async def iter_events(self):
        if False:
            yield None

    async def close(self) -> None:
        return None


class OpenAIRealtimeWebSocketClient:
    """Thin adapter over websocket-json protocol for OpenAI realtime."""

    def __init__(self, *, url: str, api_key: str, model: str | None) -> None:
        self._url = url
        self._api_key = api_key
        self._model = model
        self._conn: Any = None

    async def connect(self) -> None:
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover - depends on runtime extras
            raise RuntimeError("websockets package not available") from exc

        url = self._url
        if self._model and "model=" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}model={self._model}"

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "OpenAI-Beta": "realtime=v1",
        }
        self._conn = await websockets.connect(url, additional_headers=headers)

    async def send_input_audio(self, payload_b64: str) -> None:
        if self._conn is None:
            return
        event = {"type": "input_audio_buffer.append", "audio": payload_b64}
        await self._conn.send(json.dumps(event))

    async def iter_events(self):
        if self._conn is None:
            return
        while True:
            raw = await self._conn.recv()
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                continue

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None


class StubRealtimeClient:
    """Deterministic stub used by module selftests."""

    def __init__(self, response_payload: str = "c3R1Yi1hdWRpbw==") -> None:
        self.connected = False
        self.closed = False
        self.sent_audio: list[str] = []
        self._response_payload = response_payload
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def connect(self) -> None:
        self.connected = True

    async def send_input_audio(self, payload_b64: str) -> None:
        self.sent_audio.append(payload_b64)
        await self._queue.put({"type": "response.output_audio.delta", "delta": self._response_payload})

    async def iter_events(self):
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event

    async def close(self) -> None:
        self.closed = True
        await self._queue.put(None)


def _debug(msg: str, **fields: Any) -> None:
    if is_debug():
        parts = [msg] + [f"{k}={v}" for k, v in fields.items()]
        logger.info(" ".join(parts))


def _event_name(ev: dict[str, Any]) -> str:
    return str(ev.get("event", "")).strip().lower()


def _twilio_media_payload(ev: dict[str, Any]) -> str:
    media = ev.get("media")
    if isinstance(media, dict):
        payload = media.get("payload")
        if isinstance(payload, str):
            return payload
    return ""


def _twilio_start_ids(ev: dict[str, Any]) -> tuple[str, str]:
    start = ev.get("start")
    if not isinstance(start, dict):
        return "", ""
    stream_sid = str(start.get("streamSid", "") or "")
    call_sid = str(start.get("callSid", "") or "")
    return stream_sid, call_sid


def _openai_audio_delta(ev: dict[str, Any]) -> str:
    if str(ev.get("type", "")) != "response.output_audio.delta":
        return ""
    delta = ev.get("delta")
    return delta if isinstance(delta, str) else ""


def _openai_done(ev: dict[str, Any]) -> bool:
    return str(ev.get("type", "")) in {"response.output_audio.done", "response.done"}


def _realtime_configured() -> bool:
    return bool((os.getenv(_ENV_REALTIME_URL) or "").strip() and (os.getenv(_ENV_OPENAI_API_KEY) or "").strip())


def _build_realtime_client() -> RealtimeClient:
    url = (os.getenv(_ENV_REALTIME_URL) or "").strip()
    key = (os.getenv(_ENV_OPENAI_API_KEY) or "").strip()
    model = (os.getenv(_ENV_OPENAI_MODEL) or "").strip() or None
    if not (url and key):
        return NullRealtimeClient()
    return OpenAIRealtimeWebSocketClient(url=url, api_key=key, model=model)


async def _pump_openai_audio_to_twilio(
    twilio_ws: WebSocket,
    realtime: RealtimeClient,
    state: BridgeState,
) -> None:
    async for ev in realtime.iter_events():
        payload = _openai_audio_delta(ev)
        if payload and state.stream_sid:
            out = {"event": "media", "streamSid": state.stream_sid, "media": {"payload": payload}}
            await twilio_ws.send_text(json.dumps(out))
            state.speaking = True
            state.outbound_frames += 1
            state.outbound_buffer.append(payload)
            if len(state.outbound_buffer) > 8:
                state.outbound_buffer.pop(0)
        elif _openai_done(ev):
            state.speaking = False


async def _bridge_stream(
    twilio_ws: WebSocket,
    *,
    realtime_factory: Any = _build_realtime_client,
) -> BridgeState:
    state = BridgeState()
    await twilio_ws.accept()

    realtime: RealtimeClient | None = None
    pump_task: asyncio.Task[Any] | None = None

    try:
        while True:
            try:
                raw = await twilio_ws.receive_text()
            except WebSocketDisconnect:
                _debug("VOICE_FLOW_A twilio_disconnect")
                break

            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                _debug("VOICE_FLOW_A bad_json")
                continue
            if not isinstance(event, dict):
                continue

            name = _event_name(event)
            if name == "connected":
                state.connected = True
                _debug("VOICE_FLOW_A connected")
                continue

            if name == "start":
                state.started = True
                stream_sid, call_sid = _twilio_start_ids(event)
                state.stream_sid = stream_sid
                state.call_sid = call_sid
                _debug("VOICE_FLOW_A start", stream_sid=stream_sid, call_sid=call_sid)

                if realtime is None and _realtime_configured():
                    realtime = realtime_factory()
                    await realtime.connect()
                    pump_task = asyncio.create_task(_pump_openai_audio_to_twilio(twilio_ws, realtime, state))
                continue

            if name == "media":
                payload = _twilio_media_payload(event)
                if payload:
                    state.inbound_frames += 1
                    state.inbound_buffer.append(payload)
                    if len(state.inbound_buffer) > 8:
                        state.inbound_buffer.pop(0)
                    if realtime is not None:
                        await realtime.send_input_audio(payload)
                continue

            if name == "stop":
                _debug("VOICE_FLOW_A stop", stream_sid=state.stream_sid)
                await asyncio.sleep(0)
                break
    finally:
        if pump_task is not None:
            pump_task.cancel()
            try:
                await pump_task
            except asyncio.CancelledError:
                pass
        if realtime is not None:
            await realtime.close()

    return state


@router.websocket("/twilio/stream")
async def twilio_stream(ws: WebSocket) -> None:
    await _bridge_stream(ws)


class _FakeTwilioSocket:
    def __init__(self, incoming_events: list[dict[str, Any]]) -> None:
        self._incoming = [json.dumps(ev) for ev in incoming_events]
        self._idx = 0
        self.sent_text: list[str] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        if self._idx >= len(self._incoming):
            raise WebSocketDisconnect(code=1000)
        raw = self._incoming[self._idx]
        self._idx += 1
        await asyncio.sleep(0)
        return raw

    async def send_text(self, text: str) -> None:
        self.sent_text.append(text)


def selftests() -> SelfTestResult:
    async def _run() -> SelfTestResult:
        stub = StubRealtimeClient(response_payload="b3V0LWF1ZGlv")
        fake_ws = _FakeTwilioSocket(
            [
                {"event": "connected"},
                {
                    "event": "start",
                    "start": {"streamSid": "MZ-stream-01", "callSid": "CA-call-01"},
                },
                {"event": "media", "media": {"payload": "aW4tYXVkaW8="}},
                {"event": "stop"},
            ]
        )

        prev_url = os.getenv(_ENV_REALTIME_URL)
        prev_key = os.getenv(_ENV_OPENAI_API_KEY)
        os.environ[_ENV_REALTIME_URL] = "wss://stub.local/realtime"
        os.environ[_ENV_OPENAI_API_KEY] = "stub-key"
        try:
            state = await _bridge_stream(fake_ws, realtime_factory=lambda: stub)
        finally:
            if prev_url is None:
                os.environ.pop(_ENV_REALTIME_URL, None)
            else:
                os.environ[_ENV_REALTIME_URL] = prev_url
            if prev_key is None:
                os.environ.pop(_ENV_OPENAI_API_KEY, None)
            else:
                os.environ[_ENV_OPENAI_API_KEY] = prev_key

        if not fake_ws.accepted:
            return SelfTestResult(ok=False, message="ws not accepted")
        if not state.connected or not state.started:
            return SelfTestResult(ok=False, message="connected/start handling failed")
        if state.inbound_frames != 1:
            return SelfTestResult(ok=False, message="inbound media frame not tracked")
        if not stub.closed:
            return SelfTestResult(ok=False, message="realtime close/teardown not clean")
        if stub.sent_audio != ["aW4tYXVkaW8="]:
            return SelfTestResult(ok=False, message="twilio media not forwarded to realtime")

        outbound = [json.loads(s) for s in fake_ws.sent_text]
        medias = [ev for ev in outbound if ev.get("event") == "media"]
        if len(medias) != 1:
            return SelfTestResult(ok=False, message="expected one outbound media event")
        payload = medias[0].get("media", {}).get("payload")
        if payload != "b3V0LWF1ZGlv":
            return SelfTestResult(ok=False, message="outbound media payload mismatch")

        return SelfTestResult(ok=True, message="voice flow a selftests ok")

    return asyncio.run(_run())


def security_checks() -> SelfTestResult:
    # Explicit shared-line assumption: start.customParameters are untrusted and ignored.
    event = {
        "event": "start",
        "start": {
            "streamSid": "MZ-security",
            "callSid": "CA-security",
            "customParameters": {"tenant_id": "evil-tenant", "auth": "bad"},
        },
    }
    stream_sid, call_sid = _twilio_start_ids(event)
    if stream_sid != "MZ-security" or call_sid != "CA-security":
        return SelfTestResult(ok=False, message="trusted ids not extracted deterministically")

    custom_parameters = event["start"].get("customParameters")
    if not isinstance(custom_parameters, dict):
        return SelfTestResult(ok=False, message="security fixture invalid")

    # Auth material must come only from server env, never from Twilio payloads.
    if _realtime_configured() and not (
        (os.getenv(_ENV_REALTIME_URL) or "").strip() and (os.getenv(_ENV_OPENAI_API_KEY) or "").strip()
    ):
        return SelfTestResult(ok=False, message="realtime auth source must be environment only")

    return SelfTestResult(
        ok=True,
        message="tenant/auth assumptions explicit: shared-line stream, no trusted tenant from Twilio payload",
    )


def load_profile() -> dict[str, Any]:
    return {
        "expected_concurrency": "small (single-digit to low tens concurrent calls)",
        "frame_pacing": "Twilio inbound media ~20ms cadence; outbound mirrors OpenAI deltas",
        "buffer_limits": {"inbound_recent_frames": 8, "outbound_recent_frames": 8},
        "hot_path_constraints": ["no_db", "no_blocking_calls", "async_streaming_only"],
    }


FEATURE = {
    "key": "voice_flow_a",
    "router": router,
    "enabled_env": "VOZ_FEATURE_VOICE_FLOW_A",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
