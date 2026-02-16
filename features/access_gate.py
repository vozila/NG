"""VOZLIA FILE PURPOSE
Purpose: shared line access gate (MVP) for keyword-triggered tenant/code capture.
Hot path: no (control-plane style HTTP flow).
Feature flags: VOZ_FEATURE_ACCESS_GATE.
Failure mode: invalid input returns deterministic prompts; no tenant actions before scope.
"""

from __future__ import annotations

import itertools
import os
import re
from dataclasses import dataclass

from fastapi import APIRouter
from pydantic import BaseModel

from core.config import env_flag, is_debug
from core.logging import logger

router = APIRouter()

STATE_INFO = "INFO"
STATE_AWAIT_BUSINESS_CODE = "AWAIT_BUSINESS_CODE_KEYWORD"
STATE_AWAIT_TENANT_ID = "AWAIT_TENANT_ID"
STATE_AWAIT_ACCESS_CODE = "AWAIT_ACCESS_CODE"
STATE_COMPLETE = "COMPLETE"

_KEYWORD = "business code"
_TENANT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_CODE_RE = re.compile(r"^[0-9]{8}$")
_TOKEN_COUNTER = itertools.count(1)
_SESSIONS: dict[str, dict[str, str | bool]] = {}

_PROMPT_INFO = "General support line. Say 'business code' to continue with tenant access."
_PROMPT_TENANT = "Please provide your tenant_id (letters, numbers, '_' or '-')."
_PROMPT_CODE = "Please provide your 8-digit access code."
_PROMPT_CODE_INVALID = "Invalid access code. Enter exactly 8 digits."
_PROMPT_TENANT_INVALID = "Invalid tenant_id. Use letters, numbers, '_' or '-'."


class AccessStartResponse(BaseModel):
    session_token: str
    prompt: str
    state: str
    done: bool


class AccessStepRequest(BaseModel):
    session_token: str
    text: str


def _new_session() -> str:
    token = f"ag-{next(_TOKEN_COUNTER):08d}"
    _SESSIONS[token] = {"state": STATE_INFO, "tenant_id": "", "authenticated": False}
    return token


def _contains_keyword(text: str) -> bool:
    return _KEYWORD in text.strip().lower()


def _normalize_tenant_id(text: str) -> str:
    return text.strip()


def _valid_tenant_id(tenant_id: str) -> bool:
    return bool(_TENANT_RE.fullmatch(tenant_id))


def _valid_access_code(code: str) -> bool:
    return bool(_CODE_RE.fullmatch(code.strip()))


def _registration_stub_payload(tenant_id: str) -> dict[str, object]:
    return {
        "status": "registration_required",
        "tenant_id": tenant_id,
        "registration_fields": ["caller_id", "email", "zip"],
        "require_password_change": True,
    }


def _auth_payload(tenant_id: str) -> dict[str, object]:
    return {
        "status": "authenticated",
        "tenant_id": tenant_id,
        "require_password_change": True,
    }


def _safe_debug(msg: str) -> None:
    if is_debug():
        logger.info(msg)


def _step_session(session: dict[str, str | bool], text: str) -> dict[str, object]:
    state = str(session["state"])
    txt = text or ""

    if state == STATE_INFO:
        session["state"] = STATE_AWAIT_BUSINESS_CODE
        state = STATE_AWAIT_BUSINESS_CODE

    if state == STATE_AWAIT_BUSINESS_CODE:
        if not _contains_keyword(txt):
            return {
                "done": False,
                "state": STATE_AWAIT_BUSINESS_CODE,
                "prompt": _PROMPT_INFO,
            }
        session["state"] = STATE_AWAIT_TENANT_ID
        _safe_debug("ACCESS_GATE transition=AWAIT_TENANT_ID")
        return {"done": False, "state": STATE_AWAIT_TENANT_ID, "prompt": _PROMPT_TENANT}

    if state == STATE_AWAIT_TENANT_ID:
        tenant_id = _normalize_tenant_id(txt)
        if not _valid_tenant_id(tenant_id):
            return {
                "done": False,
                "state": STATE_AWAIT_TENANT_ID,
                "prompt": _PROMPT_TENANT_INVALID,
            }
        session["tenant_id"] = tenant_id
        session["state"] = STATE_AWAIT_ACCESS_CODE
        _safe_debug("ACCESS_GATE transition=AWAIT_ACCESS_CODE")
        return {"done": False, "state": STATE_AWAIT_ACCESS_CODE, "prompt": _PROMPT_CODE}

    if state == STATE_AWAIT_ACCESS_CODE:
        code = txt.strip()
        if not _valid_access_code(code):
            return {"done": False, "state": STATE_AWAIT_ACCESS_CODE, "prompt": _PROMPT_CODE_INVALID}

        tenant_id = str(session.get("tenant_id", "")).strip()
        if not tenant_id:
            return {"done": False, "state": STATE_AWAIT_TENANT_ID, "prompt": _PROMPT_TENANT}

        session["state"] = STATE_COMPLETE
        session["authenticated"] = True
        _safe_debug("ACCESS_GATE transition=COMPLETE")

        if code == "00000000":
            return {"done": True, "state": STATE_COMPLETE, "result": _registration_stub_payload(tenant_id)}
        return {"done": True, "state": STATE_COMPLETE, "result": _auth_payload(tenant_id)}

    return {"done": False, "state": STATE_AWAIT_BUSINESS_CODE, "prompt": _PROMPT_INFO}


@router.post("/access/start", response_model=AccessStartResponse)
async def access_start() -> AccessStartResponse:
    token = _new_session()
    _safe_debug("ACCESS_GATE action=start")
    return AccessStartResponse(
        session_token=token,
        prompt=_PROMPT_INFO,
        state=STATE_INFO,
        done=False,
    )


@router.post("/access/step")
async def access_step(req: AccessStepRequest) -> dict[str, object]:
    session = _SESSIONS.get(req.session_token)
    if session is None:
        return {"done": False, "error": "invalid_session_token"}

    out = _step_session(session, req.text)
    out["session_token"] = req.session_token
    return out


@dataclass
class SelfTestResult:
    ok: bool
    message: str = ""


def selftests() -> SelfTestResult:
    token = _new_session()
    session = _SESSIONS[token]

    s1 = _step_session(session, "business code")
    if s1.get("state") != STATE_AWAIT_TENANT_ID:
        return SelfTestResult(ok=False, message="keyword path failed")

    s2 = _step_session(session, "tenant_01")
    if s2.get("state") != STATE_AWAIT_ACCESS_CODE:
        return SelfTestResult(ok=False, message="tenant capture failed")

    s3 = _step_session(session, "12345678")
    if not s3.get("done"):
        return SelfTestResult(ok=False, message="valid code should complete")

    invalid_token = _new_session()
    invalid_session = _SESSIONS[invalid_token]
    _step_session(invalid_session, "business code")
    _step_session(invalid_session, "tenant_02")
    s4 = _step_session(invalid_session, "1234")
    if s4.get("prompt") != _PROMPT_CODE_INVALID:
        return SelfTestResult(ok=False, message="invalid access code rejection failed")

    # Route mounting OFF/ON check through app factory.
    from core.app import create_app

    prev = os.getenv("VOZ_FEATURE_ACCESS_GATE")
    try:
        os.environ["VOZ_FEATURE_ACCESS_GATE"] = "0"
        app_off = create_app()
        off_paths = {r.path for r in app_off.routes}
        if "/access/start" in off_paths or "/access/step" in off_paths:
            return SelfTestResult(ok=False, message="route mounted while OFF")

        os.environ["VOZ_FEATURE_ACCESS_GATE"] = "1"
        app_on = create_app()
        on_paths = {r.path for r in app_on.routes}
        if "/access/start" not in on_paths or "/access/step" not in on_paths:
            return SelfTestResult(ok=False, message="route missing while ON")
    finally:
        if prev is None:
            os.environ.pop("VOZ_FEATURE_ACCESS_GATE", None)
        else:
            os.environ["VOZ_FEATURE_ACCESS_GATE"] = prev

    return SelfTestResult(ok=True, message="access gate selftests ok")


def security_checks() -> SelfTestResult:
    raw = (os.getenv("VOZ_FEATURE_ACCESS_GATE") or "0").strip().lower()
    expected = raw in ("1", "true", "yes", "on")
    if env_flag("VOZ_FEATURE_ACCESS_GATE", "0") != expected:
        return SelfTestResult(ok=False, message="feature flag parse inconsistency")

    token = _new_session()
    session = _SESSIONS[token]
    out = _step_session(session, "12345678")
    if out.get("done"):
        return SelfTestResult(ok=False, message="tenant-scoped completion before tenant_id")

    return SelfTestResult(ok=True, message="access gate security ok")


def load_profile() -> dict[str, object]:
    return {"hint": "http-fsm", "p50_ms": 5, "p95_ms": 20}


FEATURE = {
    "key": "access_gate",
    "router": router,
    "enabled_env": "VOZ_FEATURE_ACCESS_GATE",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
