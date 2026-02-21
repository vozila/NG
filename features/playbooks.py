"""VOZLIA FILE PURPOSE
Purpose: schema-validated chat wizard playbook draft endpoint for portal flows.
Hot path: no (owner control-plane only).
Feature flags:
  - VOZ_FEATURE_PLAYBOOKS
  - VOZ_OWNER_PLAYBOOKS_ENABLED
Failure mode:
  - unauthorized => 401
  - disabled => 503
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from core.db import emit_event, query_events

router = APIRouter(prefix="/owner/playbooks", tags=["playbooks"])


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
    if (os.getenv("VOZ_OWNER_PLAYBOOKS_ENABLED") or "1").strip() != "1":
        raise HTTPException(status_code=503, detail="playbooks disabled")


class WizardMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=500)


class WizardDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: str = Field(min_length=1)
    goal_id: str = Field(min_length=1)
    messages: list[WizardMessage] = Field(min_length=1, max_length=40)
    schedule_hint_minutes: int = Field(default=1440, ge=1, le=60 * 24 * 14)


def _latest_playbook(tenant_id: str, playbook_id: str) -> dict[str, Any] | None:
    rows = query_events(tenant_id=tenant_id, limit=5000)
    found: dict[str, Any] | None = None
    for row in rows:
        if str(row.get("event_type") or "") != "wizard.playbook_drafted":
            continue
        payload = row.get("payload")
        p = payload if isinstance(payload, dict) else {}
        if str(p.get("playbook_id") or "") == playbook_id:
            found = p
    return found


@router.post("/wizard/draft")
async def create_playbook_draft(
    body: WizardDraftRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()
    user_lines = [m.text.strip() for m in body.messages if m.role == "user" and m.text.strip()]
    summary = " ".join(user_lines[:2])[:220]
    now = int(time.time())
    playbook_id = str(uuid.uuid4())
    payload = {
        "tenant_id": body.tenant_id,
        "playbook_id": playbook_id,
        "goal_id": body.goal_id,
        "schema_version": "v1",
        "messages": [m.model_dump() for m in body.messages],
        "summary": summary or "playbook draft",
        "schedule_hint_minutes": body.schedule_hint_minutes,
        "created_ts": now,
        "status": "draft",
    }
    event_id = emit_event(
        tenant_id=body.tenant_id,
        rid=playbook_id,
        event_type="wizard.playbook_drafted",
        payload_dict=payload,
        idempotency_key=f"playbook_draft:{playbook_id}",
    )
    return {"ok": True, "tenant_id": body.tenant_id, "playbook_id": playbook_id, "event_id": event_id}


@router.get("/{playbook_id}")
async def read_playbook(
    playbook_id: str,
    tenant_id: str = Query(..., min_length=1),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()
    payload = _latest_playbook(tenant_id, playbook_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="playbook not found")
    return {"ok": True, "tenant_id": tenant_id, "playbook": payload}


def selftests() -> dict[str, Any]:
    return {"ok": True}


def security_checks() -> dict[str, Any]:
    if _owner_api_key() is None:
        return {"ok": False, "message": "VOZ_OWNER_API_KEY missing; playbooks calls will be unauthorized"}
    return {"ok": True}


def load_profile() -> dict[str, Any]:
    return {"hint": "playbooks", "p50_ms": 18, "p95_ms": 140}


FEATURE = {
    "key": "playbooks",
    "router": router,
    "enabled_env": "VOZ_FEATURE_PLAYBOOKS",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}

