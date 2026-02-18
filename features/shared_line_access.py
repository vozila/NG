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
AI_MODES = {"customer", "owner"}


def _clean_str(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    s = v.strip()
    return s or None


def _parse_json_env(name: str) -> dict[str, str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception as e:  # pragma: no cover
        raise ValueError(f"{name} invalid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{name} must be a JSON object")
    out: dict[str, str] = {}
    for k, v in data.items():
        ks = _clean_str(k)
        vs = _clean_str(v)
        if not ks or not vs:
            raise ValueError(f"{name} must map non-empty strings")
        out[ks] = vs
    return out


def _parse_access_code_routing_env(name: str) -> dict[str, dict[str, str]]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception as e:  # pragma: no cover
        raise ValueError(f"{name} invalid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{name} must be a JSON object")

    out: dict[str, dict[str, str]] = {}
    for code, spec in data.items():
        if not isinstance(code, str) or len(code) != ACCESS_CODE_DIGITS or not code.isdigit():
            raise ValueError(f"{name} must map 8-digit codes")
        if not isinstance(spec, dict):
            raise ValueError(f"{name} value must include tenant_id and ai_mode")
        tenant_id = _clean_str(spec.get("tenant_id"))
        ai_mode = _clean_str(spec.get("ai_mode"))
        if not tenant_id or not ai_mode:
            raise ValueError(f"{name} value must include tenant_id and ai_mode")
        if ai_mode not in AI_MODES:
            raise ValueError(f"{name} ai_mode must be 'customer' or 'owner'")
        out[code] = {"tenant_id": tenant_id, "ai_mode": ai_mode}
    return out


def _resolve_access_code(cfg: dict[str, Any], code: str) -> tuple[str, str] | None:
    dual_mode_access: bool = cfg["dual_mode_access"]
    access_code_routing: dict[str, dict[str, str]] = cfg["access_code_routing"]
    client_access_code_map: dict[str, str] = cfg["client_access_code_map"]
    access_code_map: dict[str, str] = cfg["access_code_map"]

    # Legacy behavior: single owner map only.
    if not dual_mode_access:
        owner_tenant = access_code_map.get(code)
        if owner_tenant:
            return owner_tenant, "owner"
        return None

    # Dual mode behavior (preferred): explicit routing table.
    if access_code_routing:
        spec = access_code_routing.get(code)
        if not spec:
            return None
        return spec["tenant_id"], spec["ai_mode"]

    client_tenant = client_access_code_map.get(code)
    if client_tenant:
        return client_tenant, "customer"

    owner_tenant = access_code_map.get(code)
    if owner_tenant:
        return owner_tenant, "owner"

    return None


def _xml_escape(s: str) -> str:
    # Minimal XML escaping for TwiML. Order matters (& first).
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _twiml_say_hangup(message: str) -> str:
    m = _xml_escape(message)
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

    # IMPORTANT: Build the full action URL first, then XML-escape the entire URL so
    # the query separator "&" becomes "&amp;" inside the TwiML attribute.
    # Twilio’s TwiML XML parser is strict here.
    full_action_url = f"{action_url}?attempt={attempt}&rid={rid}"
    action_xml = _xml_escape(full_action_url)

    # DTMF gather for deterministic MVP
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Gather input="dtmf" numDigits="{ACCESS_CODE_DIGITS}" timeout="6" action="{action_xml}" method="POST">
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
    ai_mode: str | None,
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
    if ai_mode:
        params.append(f'<Parameter name="ai_mode" value="{_xml_escape(ai_mode)}"/>')
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
    for k, v in parsed.items():
        if not v:
            continue
        out[k] = v[0]
    return out


def _load_config() -> dict[str, Any]:
    # Required base config
    shared_line_number = _clean_str(os.getenv("VOZ_SHARED_LINE_NUMBER", ""))
    if not shared_line_number:
        raise ValueError("VOZ_SHARED_LINE_NUMBER missing")

    dual_mode_access = env_flag("VOZ_DUAL_MODE_ACCESS")
    access_code_map = _parse_json_env("VOZ_ACCESS_CODE_MAP_JSON")
    client_access_code_map = _parse_json_env("VOZ_CLIENT_ACCESS_CODE_MAP_JSON")
    access_code_routing = (
        _parse_access_code_routing_env("VOZ_ACCESS_CODE_ROUTING_JSON") if dual_mode_access else {}
    )
    dedicated_line_map = _parse_json_env("VOZ_DEDICATED_LINE_MAP_JSON")
    access_code_prompt = _clean_str(os.getenv("VOZ_ACCESS_CODE_PROMPT", "")) or "Please enter your 8-digit access code."

    stream_url = _clean_str(os.getenv("VOZ_TWILIO_STREAM_URL", ""))
    if not stream_url:
        raise ValueError("VOZ_TWILIO_STREAM_URL missing")
    if not stream_url.startswith("wss://"):
        raise ValueError("VOZ_TWILIO_STREAM_URL must start with wss://")

    return {
        "shared_line_number": shared_line_number,
        "dual_mode_access": dual_mode_access,
        "access_code_map": access_code_map,
        "client_access_code_map": client_access_code_map,
        "access_code_routing": access_code_routing,
        "dedicated_line_map": dedicated_line_map,
        "stream_url": stream_url,
        "access_code_prompt": access_code_prompt,
    }


def _rid_from_call_sid(call_sid: str | None) -> str:
    # rid is our trace id for this call; default to a timestamped placeholder if missing.
    if call_sid:
        return call_sid
    return f"RID_{int(time.time() * 1000)}"


def _log(rid: str, msg: str) -> None:
    if is_debug():
        logger.info("vozlia_ng rid=%s %s", rid, msg)


@contextmanager
def _feature_enabled_guard() -> Iterator[None]:
    if not env_flag("VOZ_FEATURE_SHARED_LINE_ACCESS"):
        raise RuntimeError("Feature disabled: VOZ_FEATURE_SHARED_LINE_ACCESS=0")
    yield


@router.post("/twilio/voice")
async def twilio_voice(request: Request) -> StarletteResponse:
    """
    Entry point for inbound calls.
    - Dedicated line: if 'To' matches VOZ_DEDICATED_LINE_MAP_JSON key, route immediately to stream with tenant_id.
    - Shared line: if 'To' matches VOZ_SHARED_LINE_NUMBER, prompt for access code (DTMF gather).
    """
    with _feature_enabled_guard():
        cfg = _load_config()

    body = await request.body()
    form = _parse_form_urlencoded(body)
    call_sid = _clean_str(form.get("CallSid"))
    rid = _rid_from_call_sid(call_sid)
    to_number = _clean_str(form.get("To"))
    from_number = _clean_str(form.get("From"))

    _log(rid, f"request received: /twilio/voice to={to_number} from={from_number}")

    shared_line_number: str = cfg["shared_line_number"]
    dedicated_line_map: dict[str, str] = cfg["dedicated_line_map"]
    stream_url: str = cfg["stream_url"]

    # Dedicated routing
    tenant_id = dedicated_line_map.get(to_number or "")
    if tenant_id:
        _log(rid, f"routing decision: mode=dedicated to={to_number} tenant_id={tenant_id} ai_mode=customer")
        twiml = _twiml_connect_stream(
            stream_url=stream_url,
            rid=rid,
            tenant_mode="dedicated",
            tenant_id=tenant_id,
            ai_mode="customer",
            from_number=from_number,
            to_number=to_number,
        )
        return Response(content=twiml, media_type="application/xml")

    # Shared routing (default)
    if to_number != shared_line_number:
        _log(rid, f"routing decision: mode=reject to={to_number} tenant_id=None")
        twiml = _twiml_say_hangup("Wrong number.")
        return Response(content=twiml, media_type="application/xml")

    _log(rid, f"routing decision: mode=shared to={to_number} tenant_id=None ai_mode=None")
    # IMPORTANT: action URL is escaped inside _twiml_gather_access_code
    action_url = str(request.url_for("twilio_voice_access_code"))
    twiml = _twiml_gather_access_code(
        action_url=action_url,
        attempt=0,
        rid=rid,
        prompt=cfg["access_code_prompt"],
    )
    return Response(content=twiml, media_type="application/xml")


@router.post("/twilio/voice/access-code", name="twilio_voice_access_code")
async def twilio_voice_access_code(request: Request) -> StarletteResponse:
    """
    DTMF callback for shared line:
    - Validate Digits against VOZ_ACCESS_CODE_MAP_JSON.
    - If valid: connect to stream with tenant_id
    - Else: retry up to MAX_INVALID_RETRIES then hang up.
    """
    with _feature_enabled_guard():
        cfg = _load_config()

    q = dict(request.query_params)
    attempt = int(q.get("attempt", "0") or "0")
    rid = _clean_str(q.get("rid"))

    body = await request.body()
    form = _parse_form_urlencoded(body)
    call_sid = _clean_str(form.get("CallSid"))
    rid = rid or _rid_from_call_sid(call_sid)

    digits = _clean_str(form.get("Digits")) or ""
    to_number = _clean_str(form.get("To"))
    from_number = _clean_str(form.get("From"))

    _log(rid, f"request received: /twilio/voice/access-code attempt={attempt} digits={digits}")

    stream_url: str = cfg["stream_url"]

    resolved = _resolve_access_code(cfg, digits)
    if resolved:
        tenant_id, ai_mode = resolved
        _log(rid, f"ACCESS_CODE_ACCEPTED tenant_id={tenant_id} ai_mode={ai_mode}")
        _log(
            rid,
            f"routing decision: mode=shared to={to_number} tenant_id={tenant_id} ai_mode={ai_mode}",
        )
        twiml = _twiml_connect_stream(
            stream_url=stream_url,
            rid=rid,
            tenant_mode="shared",
            tenant_id=tenant_id,
            ai_mode=ai_mode,
            from_number=from_number,
            to_number=to_number,
        )
        return Response(content=twiml, media_type="application/xml")

    # Invalid digits
    attempt += 1
    if attempt <= MAX_INVALID_RETRIES:
        _log(rid, f"access denied: retry attempt={attempt}")
        action_url = str(request.url_for("twilio_voice_access_code"))
        twiml = _twiml_gather_access_code(
            action_url=action_url,
            attempt=attempt,
            rid=rid,
            prompt="Invalid code. Please try again.",
        )
        return Response(content=twiml, media_type="application/xml")

    _log(rid, "access denied: max retries")
    twiml = _twiml_say_hangup("Invalid access code. Goodbye.")
    return Response(content=twiml, media_type="application/xml")


@router.get("/_healthz")
async def healthz() -> PlainTextResponse:
    return PlainTextResponse("ok")


def _attach(app: FastAPI) -> None:
    app.include_router(router)


def selftests() -> dict[str, Any]:
    # Import lazily so production runtime doesn't need dev deps.
    from fastapi.testclient import TestClient  # type: ignore

    app = FastAPI()
    _attach(app)

    # Enable feature for test
    os.environ["VOZ_FEATURE_SHARED_LINE_ACCESS"] = "1"
    os.environ["VOZ_DUAL_MODE_ACCESS"] = "1"
    os.environ["VOZ_SHARED_LINE_NUMBER"] = "+15551234567"
    os.environ["VOZ_ACCESS_CODE_MAP_JSON"] = '{"12345678":"tenant_owner"}'
    os.environ["VOZ_CLIENT_ACCESS_CODE_MAP_JSON"] = '{"87654321":"tenant_client"}'
    os.environ["VOZ_ACCESS_CODE_ROUTING_JSON"] = (
        '{"12345678":{"tenant_id":"tenant_demo","ai_mode":"owner"},'
        '"87654321":{"tenant_id":"tenant_demo","ai_mode":"customer"}}'
    )
    os.environ["VOZ_DEDICATED_LINE_MAP_JSON"] = "{}"
    os.environ["VOZ_TWILIO_STREAM_URL"] = "wss://example.com/twilio/stream"

    c = TestClient(app)

    # Shared line should return Gather and MUST escape '&' in action URL query string (XML-safe).
    r = c.post(
        "/twilio/voice",
        data={"CallSid": "CA_TEST", "To": "+15551234567", "From": "+15550001111"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200
    body = r.text
    assert "<Gather" in body
    assert "action=" in body
    # Ensure query separator is XML-escaped
    assert "&amp;" in body

    # Valid OWNER access code should Connect/Stream with ai_mode=owner.
    r2 = c.post(
        "/twilio/voice/access-code?attempt=0&rid=CA_TEST",
        data={
            "CallSid": "CA_TEST",
            "To": "+15551234567",
            "From": "+15550001111",
            "Digits": "12345678",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r2.status_code == 200
    assert "<Connect>" in r2.text
    assert "<Stream" in r2.text
    assert "tenant_demo" in r2.text
    assert 'name="ai_mode" value="owner"' in r2.text

    # Valid CUSTOMER access code should Connect/Stream with ai_mode=customer.
    r3 = c.post(
        "/twilio/voice/access-code?attempt=0&rid=CA_TEST",
        data={
            "CallSid": "CA_TEST",
            "To": "+15551234567",
            "From": "+15550001111",
            "Digits": "87654321",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r3.status_code == 200
    assert "<Connect>" in r3.text
    assert "<Stream" in r3.text
    assert "tenant_demo" in r3.text
    assert 'name="ai_mode" value="customer"' in r3.text

    # Invalid code should retry and eventually hang up.
    r4 = c.post(
        "/twilio/voice/access-code?attempt=0&rid=CA_TEST",
        data={
            "CallSid": "CA_TEST",
            "To": "+15551234567",
            "From": "+15550001111",
            "Digits": "00000000",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r4.status_code == 200
    assert "<Gather" in r4.text

    r5 = c.post(
        "/twilio/voice/access-code?attempt=1&rid=CA_TEST",
        data={
            "CallSid": "CA_TEST",
            "To": "+15551234567",
            "From": "+15550001111",
            "Digits": "00000000",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r5.status_code == 200
    assert "<Gather" in r5.text

    r6 = c.post(
        "/twilio/voice/access-code?attempt=2&rid=CA_TEST",
        data={
            "CallSid": "CA_TEST",
            "To": "+15551234567",
            "From": "+15550001111",
            "Digits": "00000000",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r6.status_code == 200
    assert "<Hangup/>" in r6.text

    return {"ok": True}


def security_checks() -> dict[str, Any]:
    # Feature is webhook-only and reads env vars; no DB access.
    # Enforce HTTPS/WSS requirements at config load time.
    return {"ok": True}


def load_profile() -> dict[str, Any]:
    # Webhook endpoints: very light (parse form + emit TwiML). No load harness here.
    return {"ok": True}


FEATURE = {
    "key": "shared_line_access",
    "router": router,
    "enabled_env": "VOZ_FEATURE_SHARED_LINE_ACCESS",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}


def mount(app: FastAPI) -> None:
    """
    Called by feature loader in some setups; safe to no-op if already mounted.
    """
    _attach(app)


def install_into_app(app: FastAPI) -> None:
    """
    Compatibility hook for older bootstraps.
    """
    _attach(app)


def ensure_features_loaded(app: FastAPI) -> None:
    """
    If you are booting a minimal app and want all enabled features registered.
    """
    load_features(app)
