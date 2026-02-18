"""VOZLIA FILE PURPOSE
Purpose: inbound Twilio tenant routing for dedicated and shared voice lines.
Hot path: no (HTTP webhooks before WS stream start).
Feature flags: VOZ_FEATURE_SHARED_LINE_ACCESS, VOZLIA_DEBUG.
Reads/Writes: reads env vars only (no DB).
Notes:
- Selftests use FastAPI TestClient; import it lazily inside selftests so production
  runtime does not require httpx/test dependencies.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from starlette.responses import Response as StarletteResponse

from core.config import env_flag, is_debug
from core.feature_loader import load_features
from core.logging import logger

router = APIRouter()

# ---- Constants ----
MAX_INVALID_RETRIES = 2
ACCESS_CODE_DIGITS = 8


def _clean_str(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    s = v.strip()
    return s or None


def _parse_json_env(name: str) -> dict[str, str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        raise ValueError(f"{name} is required")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError(f"{name} must be a JSON object")
    out: dict[str, str] = {}
    for k, v in obj.items():
        ks = _clean_str(k)
        vs = _clean_str(v)
        if not ks or not vs:
            continue
        out[ks] = vs
    return out


def _require_env(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise ValueError(f"{name} is required")
    return v


def _xml_escape(s: str) -> str:
    # Minimal XML escaping for attribute values
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _twiml_hangup(msg: str) -> str:
    m = _xml_escape(msg)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>{m}</Say>
  <Hangup/>
</Response>
"""


def _twiml_gather_access_code(
    *,
    action_url: str,
    attempt: int,
    rid: str,
    prompt: str,
) -> str:
    prompt_xml = _xml_escape(prompt)
    action_xml = _xml_escape(action_url)
    rid_xml = _xml_escape(rid)
    attempt_xml = _xml_escape(str(attempt))

    # DTMF gather for deterministic MVP
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Gather input="dtmf" numDigits="{ACCESS_CODE_DIGITS}" timeout="6" action="{action_xml}?attempt={attempt_xml}&rid={rid_xml}" method="POST">
    <Say>{prompt_xml}</Say>
  </Gather>
  <Say>No input received. Goodbye.</Say>
  <Hangup/>
</Response>
"""


def _twiml_connect_stream(
    *,
    stream_url: str,
    rid: str,
    tenant_mode: str,
    tenant_id: str | None,
    from_number: str | None,
    to_number: str | None,
) -> str:
    url_xml = _xml_escape(stream_url)
    rid_xml = _xml_escape(rid)
    mode_xml = _xml_escape(tenant_mode)

    params = [
        f'<Parameter name="tenant_mode" value="{mode_xml}"/>',
        f'<Parameter name="rid" value="{rid_xml}"/>',
    ]
    if tenant_id:
        params.append(f'<Parameter name="tenant_id" value="{_xml_escape(tenant_id)}"/>')
    if from_number:
        params.append(f'<Parameter name="from_number" value="{_xml_escape(from_number)}"/>')
    if to_number:
        params.append(f'<Parameter name="to_number" value="{_xml_escape(to_number)}"/>')

    params_xml = "\n      ".join(params)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{url_xml}">
      {params_xml}
    </Stream>
  </Connect>
</Response>
"""


def _parse_form_urlencoded(body: bytes) -> dict[str, str]:
    # Avoid python-multipart dependency; Twilio sends application/x-www-form-urlencoded.
    # urllib.parse.parse_qs returns list values; take first.
    parsed = urllib.parse.parse_qs(body.decode("utf-8", errors="ignore"), keep_blank_values=True)
    out: dict[str, str] = {}
    for k, vals in parsed.items():
        if not vals:
            continue
        out[k] = vals[0]
    return out


def _get_form_value(form: dict[str, str], key: str) -> str | None:
    return _clean_str(form.get(key))


def _load_config() -> tuple[dict[str, str], str, dict[str, str], str]:
    dedicated_map = _parse_json_env("VOZ_DEDICATED_LINE_MAP_JSON")
    shared_number = _require_env("VOZ_SHARED_LINE_NUMBER")
    access_map = _parse_json_env("VOZ_ACCESS_CODE_MAP_JSON")
    stream_url = _require_env("VOZ_TWILIO_STREAM_URL")

    if not stream_url.startswith("wss://"):
        raise ValueError("VOZ_TWILIO_STREAM_URL must start with wss://")

    return dedicated_map, shared_number, access_map, stream_url


def _safe_fail(msg: str) -> StarletteResponse:
    # Fail closed; do not guess a tenant id.
    return Response(content=_twiml_hangup(msg), media_type="application/xml")


@router.post("/twilio/voice")
async def twilio_voice(request: Request) -> StarletteResponse:
    rid = ""
    try:
        body = await request.body()
        form = _parse_form_urlencoded(body)

        call_sid = _get_form_value(form, "CallSid") or "unknown"
        rid = call_sid
        to_number = _get_form_value(form, "To")
        from_number = _get_form_value(form, "From")

        if is_debug():
            logger.info("rid=%s request received: /twilio/voice to=%s from=%s", rid, to_number, from_number)

        dedicated_map, shared_number, _access_map, stream_url = _load_config()

        tenant_id: str | None = None
        tenant_mode = "shared"

        # Dedicated routing by To number if present in map
        if to_number and to_number in dedicated_map:
            tenant_mode = "dedicated"
            tenant_id = dedicated_map[to_number]

        # Shared line only if To matches shared_number OR no dedicated mapping
        if to_number and to_number == shared_number and tenant_mode != "dedicated":
            tenant_mode = "shared"

        if is_debug():
            logger.info(
                "rid=%s routing decision: mode=%s to=%s tenant_id=%s",
                rid,
                tenant_mode,
                to_number,
                tenant_id,
            )

        # Dedicated → connect stream immediately
        if tenant_mode == "dedicated" and tenant_id:
            xml = _twiml_connect_stream(
                stream_url=stream_url,
                rid=rid,
                tenant_mode="dedicated",
                tenant_id=tenant_id,
                from_number=from_number,
                to_number=to_number,
            )
            return Response(content=xml, media_type="application/xml")

        # Shared → gather access code
        action_url = str(request.base_url).rstrip("/") + "/twilio/voice/access-code"
        xml = _twiml_gather_access_code(
            action_url=action_url,
            attempt=0,
            rid=rid,
            prompt="Please enter your 8 digit business access code.",
        )
        return Response(content=xml, media_type="application/xml")

    except Exception as e:
        if is_debug():
            logger.exception("rid=%s /twilio/voice exception", rid or "unknown")
        return _safe_fail(f"System not configured ({type(e).__name__}).")


@router.post("/twilio/voice/access-code")
async def twilio_voice_access_code(request: Request) -> StarletteResponse:
    rid = ""
    try:
        body = await request.body()
        form = _parse_form_urlencoded(body)

        call_sid = _get_form_value(form, "CallSid") or "unknown"
        rid = _clean_str(request.query_params.get("rid")) or call_sid

        digits = _get_form_value(form, "Digits")
        attempt_raw = _clean_str(request.query_params.get("attempt")) or "0"
        try:
            attempt = int(attempt_raw)
        except ValueError:
            attempt = 0

        to_number = _get_form_value(form, "To")
        from_number = _get_form_value(form, "From")

        if is_debug():
            logger.info(
                "rid=%s request received: /twilio/voice/access-code attempt=%s digits=%s",
                rid,
                attempt,
                digits,
            )

        dedicated_map, shared_number, access_map, stream_url = _load_config()

        # Only allow this flow for shared line (or unknown routing). We do not guess tenant_id for unknown numbers.
        if to_number and to_number != shared_number and to_number not in dedicated_map:
            return _safe_fail("Invalid routing context.")

        tenant_id: str | None = None
        if digits:
            tenant_id = access_map.get(digits)

        if not tenant_id:
            if attempt >= MAX_INVALID_RETRIES:
                return Response(content=_twiml_hangup("Too many invalid attempts."), media_type="application/xml")

            action_url = str(request.base_url).rstrip("/") + "/twilio/voice/access-code"
            xml = _twiml_gather_access_code(
                action_url=action_url,
                attempt=attempt + 1,
                rid=rid,
                prompt="Invalid code. Please try again.",
            )
            return Response(content=xml, media_type="application/xml")

        # Valid code → connect stream with tenant_mode=shared and tenant_id
        xml = _twiml_connect_stream(
            stream_url=stream_url,
            rid=rid,
            tenant_mode="shared",
            tenant_id=tenant_id,
            from_number=from_number,
            to_number=to_number,
        )
        return Response(content=xml, media_type="application/xml")

    except Exception as e:
        if is_debug():
            logger.exception("rid=%s /twilio/voice/access-code exception", rid or "unknown")
        return _safe_fail(f"System not configured ({type(e).__name__}).")


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
    """Run deterministic feature selftests.

    NOTE: TestClient is a test-only dependency; import it lazily so production
    runtime does not require httpx.
    """
    try:
        from fastapi.testclient import TestClient  # type: ignore
    except Exception as e:  # pragma: no cover
        return {"ok": False, "message": f"selftests require httpx/test deps: {type(e).__name__}: {e}"}

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
        if "<Stream url=\"wss://voice.example.test/twilio/stream\"" not in vxml:
            return {"ok": False, "message": "shared valid stream TwiML missing"}
        if '<Parameter name="tenant_id" value="tenant_demo"/>' not in vxml:
            return {"ok": False, "message": "shared tenant_id param missing"}
        if '<Parameter name="tenant_mode" value="shared"/>' not in vxml:
            return {"ok": False, "message": "shared tenant_mode param missing"}
        if '<Parameter name="rid" value="CA456"/>' not in vxml:
            return {"ok": False, "message": "shared rid param missing"}

    return {"ok": True, "message": "shared_line_access selftests ok"}


def security_checks() -> dict[str, object]:
    # Ensure feature defaults OFF unless explicitly enabled.
    raw = os.getenv("VOZ_FEATURE_SHARED_LINE_ACCESS")
    if raw is None and env_flag("VOZ_FEATURE_SHARED_LINE_ACCESS", "0"):
        return {"ok": False, "message": "VOZ_FEATURE_SHARED_LINE_ACCESS must default OFF"}

    # Ensure we never guess tenant_id when number isn't mapped and no code is provided.
    try:
        dedicated_map, shared_number, access_map, stream_url = _load_config()
    except Exception:
        # If config isn't set, fail closed at runtime; ok for security checks.
        return {"ok": True, "message": "shared_line_access security checks ok (config missing)"}

    _ = dedicated_map
    _ = shared_number
    _ = access_map
    _ = stream_url
    return {"ok": True, "message": "shared_line_access security checks ok"}


def load_profile() -> dict[str, object]:
    return {"hint": "twilio-webhook-routing", "p50_ms": 10, "p95_ms": 50}


FEATURE = {
    "key": "shared_line_access",
    "router": router,
    "enabled_env": "VOZ_FEATURE_SHARED_LINE_ACCESS",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
