"""VOZLIA FILE PURPOSE
Purpose: inbound Twilio tenant routing for dedicated and shared voice lines.
Hot path: no (HTTP webhooks before WS stream start).
Feature flags: VOZ_FEATURE_SHARED_LINE_ACCESS, VOZLIA_DEBUG.
Failure mode: safe-fail TwiML ("System not configured") and hang up when config is invalid.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from html import escape
from typing import Any
from urllib.parse import parse_qsl, quote

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.testclient import TestClient

from core.config import env_flag, is_debug
from core.feature_loader import load_features
from core.logging import logger

router = APIRouter()

MAX_INVALID_RETRIES = 2


@dataclass(frozen=True)
class RoutingConfig:
    dedicated_map: dict[str, str]
    shared_line_number: str
    access_code_map: dict[str, str]
    stream_url: str


def _clean(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    s = v.strip()
    return s or None


def _safe_debug(message: str, *, rid: str | None = None) -> None:
    if not is_debug():
        return
    if rid:
        logger.info("rid=%s %s", rid, message)
        return
    logger.info(message)


def _parse_json_map(var_name: str) -> dict[str, str] | None:
    raw = os.getenv(var_name)
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None

    out: dict[str, str] = {}
    for k, v in obj.items():
        key = _clean(k)
        val = _clean(v)
        if key is None or val is None:
            return None
        out[key] = val
    return out


def _load_config() -> RoutingConfig | None:
    dedicated_map = _parse_json_map("VOZ_DEDICATED_LINE_MAP_JSON")
    access_code_map = _parse_json_map("VOZ_ACCESS_CODE_MAP_JSON")
    shared_line_number = _clean(os.getenv("VOZ_SHARED_LINE_NUMBER"))
    stream_url = _clean(os.getenv("VOZ_TWILIO_STREAM_URL")) or "wss://example.invalid/twilio/stream"

    if dedicated_map is None or access_code_map is None or shared_line_number is None:
        return None

    if not stream_url.startswith("wss://"):
        return None

    return RoutingConfig(
        dedicated_map=dedicated_map,
        shared_line_number=shared_line_number,
        access_code_map=access_code_map,
        stream_url=stream_url,
    )


def _xml_response(body: str) -> Response:
    return Response(content=body, media_type="text/xml")


def _twiml_say_hangup(message: str) -> Response:
    msg = escape(message, quote=True)
    return _xml_response(f"<Response><Say>{msg}</Say><Hangup/></Response>")


def _twiml_connect_stream(*, stream_url: str, tenant_id: str, tenant_mode: str, rid: str) -> Response:
    s_url = escape(stream_url, quote=True)
    p_tenant_id = escape(tenant_id, quote=True)
    p_tenant_mode = escape(tenant_mode, quote=True)
    p_rid = escape(rid, quote=True)
    return _xml_response(
        "<Response>"
        "<Connect>"
        f'<Stream url="{s_url}">'
        f'<Parameter name="tenant_id" value="{p_tenant_id}"/>'
        f'<Parameter name="tenant_mode" value="{p_tenant_mode}"/>'
        f'<Parameter name="rid" value="{p_rid}"/>'
        "</Stream>"
        "</Connect>"
        "</Response>"
    )


def _twiml_gather_access_code(*, action_url: str, prompt: str) -> Response:
    action = escape(action_url, quote=True)
    prompt_escaped = escape(prompt, quote=True)
    return _xml_response(
        "<Response>"
        f'<Gather input="dtmf" numDigits="8" timeout="8" action="{action}" method="POST">'
        f"<Say>{prompt_escaped}</Say>"
        "</Gather>"
        "<Say>We did not receive input.</Say>"
        "<Hangup/>"
        "</Response>"
    )


def _build_access_action(*, attempt: int, rid: str) -> str:
    return f"/twilio/voice/access-code?attempt={attempt}&rid={quote(rid, safe='')}"


def _parse_attempt(value: Any) -> int:
    if isinstance(value, str):
        try:
            n = int(value)
        except ValueError:
            return 0
        return max(0, min(n, MAX_INVALID_RETRIES + 1))
    return 0


def _read_rid(form: dict[str, Any], fallback: str | None = None) -> str:
    call_sid = _clean(form.get("CallSid"))
    if call_sid:
        return call_sid
    fb = _clean(fallback)
    if fb:
        return fb
    return "unknown"


def _read_digits(form: dict[str, Any]) -> str:
    digits = _clean(form.get("Digits"))
    return digits or ""


async def _read_form_urlencoded(request: Request) -> dict[str, str]:
    body = await request.body()
    if not body:
        return {}
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError:
        decoded = body.decode("latin-1", errors="ignore")
    return dict(parse_qsl(decoded, keep_blank_values=True))


@router.post("/twilio/voice")
async def twilio_voice_entry(request: Request) -> Response:
    form = await _read_form_urlencoded(request)
    rid = _read_rid(form)
    _safe_debug("request received: twilio voice webhook", rid=rid)

    cfg = _load_config()
    if cfg is None:
        _safe_debug("routing decision: config invalid", rid=rid)
        return _twiml_say_hangup("System not configured")

    to_number = _clean(form.get("To"))
    if to_number is None:
        _safe_debug("routing decision: missing To", rid=rid)
        return _twiml_say_hangup("System not configured")

    tenant_id = cfg.dedicated_map.get(to_number)
    if tenant_id:
        _safe_debug(
            f"routing decision: mode=dedicated to={to_number} tenant_id={tenant_id}",
            rid=rid,
        )
        _safe_debug(
            f"returning TwiML: connect stream url={cfg.stream_url}",
            rid=rid,
        )
        return _twiml_connect_stream(
            stream_url=cfg.stream_url,
            tenant_id=tenant_id,
            tenant_mode="dedicated",
            rid=rid,
        )

    if to_number == cfg.shared_line_number:
        _safe_debug(
            f"routing decision: mode=shared to={to_number} prompt_access_code",
            rid=rid,
        )
        return _twiml_gather_access_code(
            action_url=_build_access_action(attempt=0, rid=rid),
            prompt="Please enter your 8 digit access code.",
        )

    _safe_debug(f"routing decision: no route to={to_number}", rid=rid)
    return _twiml_say_hangup("System not configured")


@router.post("/twilio/voice/access-code")
async def twilio_voice_access_code(request: Request) -> Response:
    form = await _read_form_urlencoded(request)
    q = request.query_params

    rid = _read_rid(form, fallback=q.get("rid"))
    attempt = _parse_attempt(q.get("attempt"))
    digits = _read_digits(form)

    _safe_debug(f"request received: access code callback attempt={attempt}", rid=rid)

    cfg = _load_config()
    if cfg is None:
        _safe_debug("routing decision: config invalid", rid=rid)
        return _twiml_say_hangup("System not configured")

    tenant_id = cfg.access_code_map.get(digits)
    if tenant_id:
        _safe_debug(
            f"routing decision: mode=shared tenant_id={tenant_id} code_valid=1",
            rid=rid,
        )
        _safe_debug(
            f"returning TwiML: connect stream url={cfg.stream_url}",
            rid=rid,
        )
        return _twiml_connect_stream(
            stream_url=cfg.stream_url,
            tenant_id=tenant_id,
            tenant_mode="shared",
            rid=rid,
        )

    next_attempt = attempt + 1
    if next_attempt <= MAX_INVALID_RETRIES:
        _safe_debug(
            f"routing decision: mode=shared code_valid=0 reprompt={next_attempt}",
            rid=rid,
        )
        return _twiml_gather_access_code(
            action_url=_build_access_action(attempt=next_attempt, rid=rid),
            prompt="Invalid code. Please re-enter your 8 digit access code.",
        )

    _safe_debug("routing decision: mode=shared code_valid=0 max_retries_exceeded", rid=rid)
    return _twiml_say_hangup("Invalid access code")


def _has_route(app: FastAPI, path: str) -> bool:
    return any(getattr(route, "path", None) == path for route in app.routes)


@contextmanager
def _temp_env(values: dict[str, str | None]) -> Iterator[None]:
    old: dict[str, str | None] = {}
    for key, value in values.items():
        old[key] = os.getenv(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def selftests() -> dict[str, object]:
    base_env = {
        "VOZ_FEATURE_SAMPLE": "0",
        "VOZ_FEATURE_ADMIN_QUALITY": "0",
        "VOZ_FEATURE_ACCESS_GATE": "0",
        "VOZ_FEATURE_WHATSAPP_IN": "0",
        "VOZ_FEATURE_VOICE_FLOW_A": "0",
        "VOZ_DEDICATED_LINE_MAP_JSON": '{"+15550001111":"tenant_abc"}',
        "VOZ_SHARED_LINE_NUMBER": "+15550002222",
        "VOZ_ACCESS_CODE_MAP_JSON": '{"12345678":"tenant_demo"}',
        "VOZ_TWILIO_STREAM_URL": "wss://voice.example.test/twilio/stream",
    }

    with _temp_env({**base_env, "VOZ_FEATURE_SHARED_LINE_ACCESS": "0"}):
        app_off = FastAPI()
        load_features(app_off)
        if _has_route(app_off, "/twilio/voice"):
            return {"ok": False, "message": "route mounted while feature disabled"}

    with _temp_env({**base_env, "VOZ_FEATURE_SHARED_LINE_ACCESS": "1"}):
        app = FastAPI()
        load_features(app)
        client = TestClient(app)

        dedicated = client.post(
            "/twilio/voice",
            data={"CallSid": "CA123", "To": "+15550001111"},
        )
        if dedicated.status_code != 200:
            return {"ok": False, "message": "dedicated webhook failed"}
        dxml = dedicated.text
        if "<Stream url=\"wss://voice.example.test/twilio/stream\"" not in dxml:
            return {"ok": False, "message": "dedicated stream TwiML missing"}
        if '<Parameter name="tenant_id" value="tenant_abc"/>' not in dxml:
            return {"ok": False, "message": "dedicated tenant_id param missing"}
        if '<Parameter name="tenant_mode" value="dedicated"/>' not in dxml:
            return {"ok": False, "message": "dedicated tenant_mode param missing"}
        if '<Parameter name="rid" value="CA123"/>' not in dxml:
            return {"ok": False, "message": "dedicated rid param missing"}

        shared_step1 = client.post(
            "/twilio/voice",
            data={"CallSid": "CA456", "To": "+15550002222"},
        )
        if shared_step1.status_code != 200:
            return {"ok": False, "message": "shared step1 webhook failed"}
        s1xml = shared_step1.text
        if "<Gather " not in s1xml or "numDigits=\"8\"" not in s1xml:
            return {"ok": False, "message": "shared step1 gather missing"}

        invalid = client.post(
            "/twilio/voice/access-code?attempt=0&rid=CA456",
            data={"CallSid": "CA456", "Digits": "00000000"},
        )
        if invalid.status_code != 200:
            return {"ok": False, "message": "shared invalid code callback failed"}
        ixml = invalid.text
        if "<Gather " not in ixml or "Invalid code" not in ixml:
            return {"ok": False, "message": "invalid code should reprompt"}

        valid = client.post(
            "/twilio/voice/access-code?attempt=1&rid=CA456",
            data={"CallSid": "CA456", "Digits": "12345678"},
        )
        if valid.status_code != 200:
            return {"ok": False, "message": "shared valid code callback failed"}
        vxml = valid.text
        if '<Parameter name="tenant_id" value="tenant_demo"/>' not in vxml:
            return {"ok": False, "message": "shared tenant_id param missing"}
        if '<Parameter name="tenant_mode" value="shared"/>' not in vxml:
            return {"ok": False, "message": "shared tenant_mode param missing"}
        if '<Parameter name="rid" value="CA456"/>' not in vxml:
            return {"ok": False, "message": "shared rid param missing"}

    return {"ok": True, "message": "shared_line_access selftests ok"}


def security_checks() -> dict[str, object]:
    enabled = env_flag("VOZ_FEATURE_SHARED_LINE_ACCESS", "0")
    raw = os.getenv("VOZ_FEATURE_SHARED_LINE_ACCESS")
    if raw is None and enabled:
        return {"ok": False, "message": "VOZ_FEATURE_SHARED_LINE_ACCESS must default OFF"}

    if _load_config() is None:
        return {"ok": True, "message": "shared_line_access security ok (safe-fail config)"}

    if MAX_INVALID_RETRIES < 1:
        return {"ok": False, "message": "MAX_INVALID_RETRIES must be >= 1"}

    return {"ok": True, "message": "shared_line_access security ok"}


def load_profile() -> dict[str, object]:
    return {"hint": "http-twiml", "p50_ms": 15, "p95_ms": 75}


FEATURE = {
    "key": "shared_line_access",
    "router": router,
    "enabled_env": "VOZ_FEATURE_SHARED_LINE_ACCESS",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
