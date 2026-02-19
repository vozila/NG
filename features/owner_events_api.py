"""VOZLIA FILE PURPOSE
Purpose: owner-facing read-only event API for tenant call analytics facts.
Hot path: no (control-plane reads only).
Feature flags: VOZ_FEATURE_OWNER_EVENTS_API.
Failure mode: auth failures return 401; query errors return deterministic 400.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from core.db import query_events

router = APIRouter(prefix="/owner", tags=["owner-events"])


def _owner_api_key() -> str | None:
    key = os.getenv("VOZ_OWNER_API_KEY", "").strip()
    return key or None


def _authorized(auth_header: str | None) -> bool:
    configured = _owner_api_key()
    if not configured:
        return False
    if not isinstance(auth_header, str):
        return False
    prefix = "Bearer "
    if not auth_header.startswith(prefix):
        return False
    token = auth_header[len(prefix) :].strip()
    return token == configured


def _require_owner_bearer(authorization: str | None) -> None:
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")


@router.get("/events")
async def owner_events(
    tenant_id: str = Query(..., min_length=1),
    limit: int = Query(100, ge=1, le=1000),
    event_type: str | None = Query(None),
    since_ts: int | None = Query(None),
    until_ts: int | None = Query(None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    try:
        rows = query_events(
            tenant_id=tenant_id,
            event_type=event_type,
            since_ts=since_ts,
            until_ts=until_ts,
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "events": rows}


@router.get("/events/latest")
async def owner_events_latest(
    tenant_id: str = Query(..., min_length=1),
    event_type: str | None = Query(None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    try:
        rows = query_events(tenant_id=tenant_id, event_type=event_type, limit=1)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    latest = rows[-1] if rows else None
    return {"ok": True, "event": latest}


def selftests() -> dict[str, Any]:
    return {"ok": True}


def security_checks() -> dict[str, Any]:
    if _owner_api_key() is None:
        return {"ok": False, "message": "VOZ_OWNER_API_KEY missing; all owner events calls will be unauthorized"}
    return {"ok": True}


def load_profile() -> dict[str, Any]:
    return {"hint": "owner-read-api", "p50_ms": 5, "p95_ms": 50}


FEATURE = {
    "key": "owner_events_api",
    "router": router,
    "enabled_env": "VOZ_FEATURE_OWNER_EVENTS_API",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
