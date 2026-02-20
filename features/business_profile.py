"""VOZLIA FILE PURPOSE
Purpose: owner-authenticated business profile CRUD for tenant voice context.
Hot path: no (owner control-plane writes/reads only).
Feature flags:
  - VOZ_FEATURE_BUSINESS_PROFILE
  - VOZ_OWNER_BUSINESS_PROFILE_ENABLED
Failure mode:
  - unauthorized => 401
  - disabled => 503
  - validation/query errors => deterministic 400
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from core.db import emit_event, get_conn

router = APIRouter(prefix="/owner/business/profile", tags=["business-profile"])

_PROFILE_UPSERT = "owner.business_profile.upserted"
_PROFILE_DELETED = "owner.business_profile.deleted"


def _owner_api_key() -> str | None:
    key = (os.getenv("VOZ_OWNER_API_KEY") or "").strip()
    return key or None


def _authorized(auth_header: str | None) -> bool:
    configured = _owner_api_key()
    if not configured or not isinstance(auth_header, str):
        return False
    prefix = "Bearer "
    if not auth_header.startswith(prefix):
        return False
    token = auth_header[len(prefix) :].strip()
    return token == configured


def _require_owner_bearer(authorization: str | None) -> None:
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")


def _ensure_runtime_enabled() -> None:
    if (os.getenv("VOZ_OWNER_BUSINESS_PROFILE_ENABLED") or "1").strip() != "1":
        raise HTTPException(status_code=503, detail="business profile disabled")


class BusinessProfileUpsertRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    business_name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=160)
    timezone: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=200)
    services: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=1000)


def _latest_profile_event(tenant_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT event_id, event_type, payload_json
            FROM events
            WHERE tenant_id = ? AND event_type IN (?, ?)
            ORDER BY rowid DESC
            LIMIT 1
            """,
            (tenant_id, _PROFILE_UPSERT, _PROFILE_DELETED),
        ).fetchone()
    if row is None:
        return None

    payload = json.loads(str(row["payload_json"]))
    p = payload if isinstance(payload, dict) else {}
    return {"event_type": str(row["event_type"]), "payload": p}


@router.get("")
async def business_profile_get(
    tenant_id: str = Query(..., min_length=1),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()
    latest = _latest_profile_event(tenant_id)
    if latest is None or latest["event_type"] == _PROFILE_DELETED:
        return {"ok": True, "tenant_id": tenant_id, "profile": None}
    payload = dict(latest["payload"])
    payload.pop("tenant_id", None)
    return {"ok": True, "tenant_id": tenant_id, "profile": payload}


@router.put("")
async def business_profile_put(
    body: BusinessProfileUpsertRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()
    payload = body.model_dump()
    event_id = emit_event(
        tenant_id=body.tenant_id,
        rid=f"business-profile:{body.tenant_id}",
        event_type=_PROFILE_UPSERT,
        payload_dict=payload,
    )
    return {
        "ok": True,
        "tenant_id": body.tenant_id,
        "event_id": event_id,
        "profile": {k: v for k, v in payload.items() if k != "tenant_id"},
    }


@router.delete("")
async def business_profile_delete(
    tenant_id: str = Query(..., min_length=1),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()
    event_id = emit_event(
        tenant_id=tenant_id,
        rid=f"business-profile:{tenant_id}",
        event_type=_PROFILE_DELETED,
        payload_dict={"tenant_id": tenant_id, "deleted": True},
    )
    return {"ok": True, "tenant_id": tenant_id, "event_id": event_id, "deleted": True}


def selftests() -> dict[str, Any]:
    return {"ok": True}


def security_checks() -> dict[str, Any]:
    if _owner_api_key() is None:
        return {"ok": False, "message": "VOZ_OWNER_API_KEY missing; business profile calls will be unauthorized"}
    return {"ok": True}


def load_profile() -> dict[str, Any]:
    return {"hint": "business-profile", "p50_ms": 15, "p95_ms": 120}


FEATURE = {
    "key": "business_profile",
    "router": router,
    "enabled_env": "VOZ_FEATURE_BUSINESS_PROFILE",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
