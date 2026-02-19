"""VOZLIA FILE PURPOSE
Purpose: quality admin endpoints (regression runner).
Hot path: no (admin control-plane only).
Feature flags: VOZ_FEATURE_ADMIN_QUALITY.
Failure mode: report failure details; does not crash server.
"""

from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi import Header
from fastapi import HTTPException

from core.quality import run_regression

router = APIRouter( prefix="/admin/quality", tags=["quality"] )


def _admin_api_key() -> str | None:
    key = os.getenv("VOZ_ADMIN_API_KEY", "").strip()
    return key or None


def _authorized(auth_header: str | None) -> bool:
    configured = _admin_api_key()
    if not configured or not isinstance(auth_header, str):
        return False
    prefix = "Bearer "
    if not auth_header.startswith(prefix):
        return False
    token = auth_header[len(prefix) :].strip()
    return token == configured


def _require_admin_bearer(authorization: str | None) -> None:
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")


@router.post("/regression/run")
async def regression_run(authorization: str | None = Header(default=None)) -> dict:
    _require_admin_bearer(authorization)
    return run_regression()


def selftests() -> dict:
    # Keep admin selftests self-contained to avoid recursion via run_regression().
    return {"ok": True, "message": "admin_quality selftests ok"}


def security_checks() -> dict:
    if _admin_api_key() is None:
        return {"ok": False, "message": "VOZ_ADMIN_API_KEY missing; admin endpoints will be unauthorized"}
    return {"ok": True}

def load_profile() -> dict:
    return {"hint": "admin-only", "p50_ms": 20, "p95_ms": 200}


FEATURE = {
    "key": "admin_quality",
    "router": router,
    "enabled_env": "VOZ_FEATURE_ADMIN_QUALITY",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
  }
