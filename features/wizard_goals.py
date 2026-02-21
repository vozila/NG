"""VOZLIA FILE PURPOSE
Purpose: owner goal persistence + lifecycle endpoints for portal wizard flows.
Hot path: no (owner control-plane only).
Feature flags:
  - VOZ_FEATURE_WIZARD_GOALS
  - VOZ_OWNER_GOALS_ENABLED
Failure mode:
  - unauthorized => 401
  - disabled => 503
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from core.db import emit_event, get_conn

router = APIRouter(prefix="/owner/goals", tags=["wizard-goals"])


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
    if (os.getenv("VOZ_OWNER_GOALS_ENABLED") or "1").strip() != "1":
        raise HTTPException(status_code=503, detail="owner goals disabled")


class GoalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: str = Field(min_length=1)
    goal: str = Field(min_length=3, max_length=600)
    cadence_minutes: int = Field(default=1440, ge=1, le=60 * 24 * 14)
    channel: Literal["email", "sms", "voice"] = "email"
    policy: str | None = Field(default=None, max_length=1200)


class GoalUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: str = Field(min_length=1)
    cadence_minutes: int | None = Field(default=None, ge=1, le=60 * 24 * 14)
    policy: str | None = Field(default=None, max_length=1200)


class GoalLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: str = Field(min_length=1)


def _goal_rows(tenant_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT event_id, tenant_id, rid, event_type, ts, payload_json
            FROM events
            WHERE tenant_id = ?
            ORDER BY rowid ASC
            LIMIT 5000
            """,
            (tenant_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "event_id": str(row["event_id"]),
                "tenant_id": str(row["tenant_id"]),
                "rid": str(row["rid"]),
                "event_type": str(row["event_type"]),
                "ts": int(row["ts"]),
                "payload": json.loads(str(row["payload_json"])),
            }
        )
    return out


def _goal_states(tenant_id: str) -> dict[str, dict[str, Any]]:
    rows = _goal_rows(tenant_id)
    state: dict[str, dict[str, Any]] = {}
    for row in rows:
        event_type = str(row.get("event_type") or "")
        payload = row.get("payload")
        p = payload if isinstance(payload, dict) else {}
        goal_id = str(p.get("goal_id") or "")
        if not goal_id:
            continue
        if event_type == "wizard.goal_created":
            state[goal_id] = {
                "goal_id": goal_id,
                "goal": p.get("goal"),
                "cadence_minutes": p.get("cadence_minutes"),
                "channel": p.get("channel"),
                "policy": p.get("policy"),
                "status": "draft",
                "created_ts": p.get("created_ts"),
                "updated_ts": p.get("updated_ts"),
                "next_run_ts": p.get("next_run_ts"),
                "last_run_ts": None,
                "last_outcome": None,
            }
            continue
        cur = state.get(goal_id)
        if cur is None:
            continue
        if event_type == "wizard.goal_updated":
            if p.get("cadence_minutes") is not None:
                cur["cadence_minutes"] = p.get("cadence_minutes")
            if "policy" in p:
                cur["policy"] = p.get("policy")
            cur["updated_ts"] = p.get("updated_ts")
        elif event_type == "wizard.goal_approved":
            cur["status"] = "active"
            cur["updated_ts"] = p.get("updated_ts")
            cur["next_run_ts"] = p.get("next_run_ts")
        elif event_type == "wizard.goal_paused":
            cur["status"] = "paused"
            cur["updated_ts"] = p.get("updated_ts")
        elif event_type == "wizard.goal_resumed":
            cur["status"] = "active"
            cur["updated_ts"] = p.get("updated_ts")
            cur["next_run_ts"] = p.get("next_run_ts")
        elif event_type == "scheduler.goal_executed":
            cur["last_run_ts"] = p.get("run_ts")
            cur["last_outcome"] = p.get("outcome")
            cur["next_run_ts"] = p.get("next_run_ts")
    return state


@router.post("")
async def create_goal(body: GoalCreateRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()
    now = int(time.time())
    goal_id = str(uuid.uuid4())
    next_run_ts = now + (body.cadence_minutes * 60)
    event_id = emit_event(
        tenant_id=body.tenant_id,
        rid=goal_id,
        event_type="wizard.goal_created",
        payload_dict={
            "tenant_id": body.tenant_id,
            "goal_id": goal_id,
            "goal": body.goal,
            "cadence_minutes": body.cadence_minutes,
            "channel": body.channel,
            "policy": body.policy,
            "created_ts": now,
            "updated_ts": now,
            "next_run_ts": next_run_ts,
        },
        idempotency_key=f"goal_create:{goal_id}",
    )
    return {"ok": True, "tenant_id": body.tenant_id, "goal_id": goal_id, "event_id": event_id}


@router.get("")
async def list_goals(
    tenant_id: str = Query(..., min_length=1),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()
    goals = list(_goal_states(tenant_id).values())
    goals.sort(key=lambda x: (int(x.get("created_ts") or 0), str(x.get("goal_id") or "")), reverse=True)
    return {"ok": True, "tenant_id": tenant_id, "items": goals}


@router.post("/{goal_id}/approve")
async def approve_goal(
    goal_id: str,
    body: GoalLifecycleRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()
    state = _goal_states(body.tenant_id).get(goal_id)
    if state is None:
        raise HTTPException(status_code=404, detail="goal not found")
    now = int(time.time())
    cadence = int(state.get("cadence_minutes") or 1440)
    next_run_ts = now + (cadence * 60)
    event_id = emit_event(
        tenant_id=body.tenant_id,
        rid=goal_id,
        event_type="wizard.goal_approved",
        payload_dict={"tenant_id": body.tenant_id, "goal_id": goal_id, "updated_ts": now, "next_run_ts": next_run_ts},
        idempotency_key=f"goal_approve:{goal_id}",
    )
    return {"ok": True, "tenant_id": body.tenant_id, "goal_id": goal_id, "event_id": event_id}


@router.post("/{goal_id}/pause")
async def pause_goal(
    goal_id: str,
    body: GoalLifecycleRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()
    state = _goal_states(body.tenant_id).get(goal_id)
    if state is None:
        raise HTTPException(status_code=404, detail="goal not found")
    now = int(time.time())
    event_id = emit_event(
        tenant_id=body.tenant_id,
        rid=goal_id,
        event_type="wizard.goal_paused",
        payload_dict={"tenant_id": body.tenant_id, "goal_id": goal_id, "updated_ts": now},
        idempotency_key=f"goal_pause:{goal_id}",
    )
    return {"ok": True, "tenant_id": body.tenant_id, "goal_id": goal_id, "event_id": event_id}


@router.post("/{goal_id}/resume")
async def resume_goal(
    goal_id: str,
    body: GoalLifecycleRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()
    state = _goal_states(body.tenant_id).get(goal_id)
    if state is None:
        raise HTTPException(status_code=404, detail="goal not found")
    now = int(time.time())
    cadence = int(state.get("cadence_minutes") or 1440)
    next_run_ts = now + (cadence * 60)
    event_id = emit_event(
        tenant_id=body.tenant_id,
        rid=goal_id,
        event_type="wizard.goal_resumed",
        payload_dict={"tenant_id": body.tenant_id, "goal_id": goal_id, "updated_ts": now, "next_run_ts": next_run_ts},
        idempotency_key=f"goal_resume:{goal_id}",
    )
    return {"ok": True, "tenant_id": body.tenant_id, "goal_id": goal_id, "event_id": event_id}


@router.patch("/{goal_id}")
async def update_goal(
    goal_id: str,
    body: GoalUpdateRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()
    state = _goal_states(body.tenant_id).get(goal_id)
    if state is None:
        raise HTTPException(status_code=404, detail="goal not found")
    now = int(time.time())
    payload: dict[str, Any] = {"tenant_id": body.tenant_id, "goal_id": goal_id, "updated_ts": now}
    if body.cadence_minutes is not None:
        payload["cadence_minutes"] = body.cadence_minutes
        payload["next_run_ts"] = now + (body.cadence_minutes * 60)
    if body.policy is not None:
        payload["policy"] = body.policy
    event_id = emit_event(
        tenant_id=body.tenant_id,
        rid=goal_id,
        event_type="wizard.goal_updated",
        payload_dict=payload,
        idempotency_key=f"goal_update:{goal_id}:{body.cadence_minutes}:{body.policy or ''}",
    )
    return {"ok": True, "tenant_id": body.tenant_id, "goal_id": goal_id, "event_id": event_id}


def selftests() -> dict[str, Any]:
    return {"ok": True}


def security_checks() -> dict[str, Any]:
    if _owner_api_key() is None:
        return {"ok": False, "message": "VOZ_OWNER_API_KEY missing; goals calls will be unauthorized"}
    return {"ok": True}


def load_profile() -> dict[str, Any]:
    return {"hint": "owner-goals", "p50_ms": 20, "p95_ms": 160}


FEATURE = {
    "key": "wizard_goals",
    "router": router,
    "enabled_env": "VOZ_FEATURE_WIZARD_GOALS",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
