"""VOZLIA FILE PURPOSE
Purpose: owner-facing action endpoints for inbox lead triage/handled state.
Hot path: no (owner control-plane writes only).
Feature flags:
  - VOZ_FEATURE_OWNER_INBOX_ACTIONS
  - VOZ_OWNER_INBOX_ENABLED
Failure mode:
  - unauthorized => 401
  - disabled => 503
"""

from __future__ import annotations

import os
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from core.db import emit_event, query_events_for_rid

router = APIRouter(prefix="/owner/inbox/actions", tags=["owner-inbox-actions"])


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
    if (os.getenv("VOZ_OWNER_INBOX_ENABLED") or "0").strip() != "1":
        raise HTTPException(status_code=503, detail="owner inbox disabled")


class QualifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: str = Field(min_length=1)
    rid: str = Field(min_length=1)
    qualified: bool
    reason: str | None = Field(default=None, max_length=500)


class HandledRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: str = Field(min_length=1)
    rid: str = Field(min_length=1)
    handled: bool
    channel: Literal["phone", "sms", "email", "unknown"] = "unknown"
    note: str | None = Field(default=None, max_length=500)


def _latest_payload(tenant_id: str, rid: str, event_type: str) -> dict[str, Any] | None:
    rows = query_events_for_rid(tenant_id=tenant_id, rid=rid, event_type=event_type, limit=1)
    if not rows:
        return None
    payload = rows[-1].get("payload")
    return payload if isinstance(payload, dict) else None


@router.post("/qualify")
async def owner_inbox_qualify(
    body: QualifyRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()
    event_id = emit_event(
        tenant_id=body.tenant_id,
        rid=body.rid,
        event_type="owner.inbox.lead_qualified",
        payload_dict={
            "tenant_id": body.tenant_id,
            "rid": body.rid,
            "qualified": body.qualified,
            "reason": body.reason,
        },
        idempotency_key=f"owner_inbox_qualified:{body.rid}:{int(body.qualified)}:{body.reason or ''}",
    )
    return {"ok": True, "tenant_id": body.tenant_id, "rid": body.rid, "event_id": event_id}


@router.post("/handled")
async def owner_inbox_handled(
    body: HandledRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()
    event_id = emit_event(
        tenant_id=body.tenant_id,
        rid=body.rid,
        event_type="owner.inbox.handled_set",
        payload_dict={
            "tenant_id": body.tenant_id,
            "rid": body.rid,
            "handled": body.handled,
            "channel": body.channel,
            "note": body.note,
        },
        idempotency_key=f"owner_inbox_handled:{body.rid}:{int(body.handled)}:{body.channel}:{body.note or ''}",
    )
    return {"ok": True, "tenant_id": body.tenant_id, "rid": body.rid, "event_id": event_id}


@router.get("/state")
async def owner_inbox_state(
    tenant_id: str = Query(..., min_length=1),
    rid: str = Query(..., min_length=1),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()
    qualified = _latest_payload(tenant_id, rid, "owner.inbox.lead_qualified")
    handled = _latest_payload(tenant_id, rid, "owner.inbox.handled_set")
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "rid": rid,
        "state": {
            "qualified": qualified.get("qualified") if isinstance(qualified, dict) else None,
            "qualified_reason": qualified.get("reason") if isinstance(qualified, dict) else None,
            "handled": handled.get("handled") if isinstance(handled, dict) else None,
            "handled_channel": handled.get("channel") if isinstance(handled, dict) else None,
            "handled_note": handled.get("note") if isinstance(handled, dict) else None,
        },
    }


def selftests() -> dict[str, Any]:
    return {"ok": True}


def security_checks() -> dict[str, Any]:
    if _owner_api_key() is None:
        return {"ok": False, "message": "VOZ_OWNER_API_KEY missing; inbox action calls will be unauthorized"}
    return {"ok": True}


def load_profile() -> dict[str, Any]:
    return {"hint": "owner-inbox-actions", "p50_ms": 12, "p95_ms": 110}


FEATURE = {
    "key": "owner_inbox_actions",
    "router": router,
    "enabled_env": "VOZ_FEATURE_OWNER_INBOX_ACTIONS",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}

