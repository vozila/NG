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

    access_code_map = _parse_json_env("VOZ_ACCESS_CODE_MAP_JSON")
    dedicated_line_map = _parse_json_env("VOZ_DEDICATED_LINE_MAP_JSON")

    stream_url = _clean_str(os.getenv("VOZ_TWILIO_STREAM_URL", ""))
    if not stream_url:
        raise ValueError("VOZ_TWILIO_STREAM_URL missing")
    if not stream_url.startswith("wss://"):
        raise ValueError("VOZ_TWILIO_STREAM_URL must start with wss://")

    return {
        "shared_line_number": shared_line_number,
        "access_code_map": access_code_map,
        "dedicated_line_map": dedicated_line_map,
        "stream_url": stream_url,
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
        _log(rid, f"routing decision: mode=dedicated to={to_number} tenant_id={tenant_id}")
        twiml = _twiml_connect_stream(
            stream_url=stream_url,
            rid=rid,
            tenant_mode="dedicated",
            tenant_id=tenant_id,
            from_number=from_number,
            to_number=to_number,
        )
        return Response(content=twiml, media_type="application/xml")

    # Shared routing (default)
    if to_number != shared_line_number:
        _log(rid, f"routing decision: mode=reject to={to_number} tenant_id=None")
        twiml = _twiml_say_hangup("Wrong number.")
