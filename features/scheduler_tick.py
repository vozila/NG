"""VOZLIA FILE PURPOSE
Purpose: admin scheduler tick + execution runner MVP for approved active goals.
Hot path: no (admin control-plane only).
Feature flags:
  - VOZ_FEATURE_SCHEDULER_TICK
  - VOZ_SCHEDULER_ENABLED
Failure mode:
  - unauthorized => 401
  - disabled => 503
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.db import emit_event, get_conn

router = APIRouter(prefix="/admin/scheduler", tags=["scheduler-tick"])


def _admin_api_key() -> str | None:
    key = (os.getenv("VOZ_ADMIN_API_KEY") or "").strip()
    return key or None


def _authorized(auth_header: str | None) -> bool:
    configured = _admin_api_key()
    if configured is None or not isinstance(auth_header, str):
        return False
    prefix = "Bearer "
    if not auth_header.startswith(prefix):
        return False
    token = auth_header[len(prefix) :].strip()
    return token == configured


def _require_admin_bearer(authorization: str | None) -> None:
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")


def _ensure_runtime_enabled() -> None:
    if (os.getenv("VOZ_SCHEDULER_ENABLED") or "0").strip() != "1":
        raise HTTPException(status_code=503, detail="scheduler disabled")


class TickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: str = Field(min_length=1)
    limit: int = Field(default=20, ge=1, le=200)
    dry_run: bool = True
    now_ts: int | None = Field(default=None, ge=0)


def _goal_state(tenant_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        raw_rows = conn.execute(
            """
            SELECT event_id, tenant_id, rid, event_type, ts, payload_json
            FROM events
            WHERE tenant_id = ?
            ORDER BY rowid ASC
            LIMIT 5000
            """,
            (tenant_id,),
        ).fetchall()
    rows: list[dict[str, Any]] = []
    for row in raw_rows:
        rows.append(
            {
                "event_id": str(row["event_id"]),
                "tenant_id": str(row["tenant_id"]),
                "rid": str(row["rid"]),
                "event_type": str(row["event_type"]),
                "ts": int(row["ts"]),
                "payload": json.loads(str(row["payload_json"])),
            }
        )
    goals: dict[str, dict[str, Any]] = {}
    for row in rows:
        event_type = str(row.get("event_type") or "")
        payload = row.get("payload")
        p = payload if isinstance(payload, dict) else {}
        goal_id = str(p.get("goal_id") or "")
        if not goal_id:
            continue
        if event_type == "wizard.goal_created":
            goals[goal_id] = {
                "goal_id": goal_id,
                "goal": p.get("goal"),
                "cadence_minutes": int(p.get("cadence_minutes") or 1440),
                "status": "draft",
                "next_run_ts": int(p.get("next_run_ts") or 0),
            }
            continue
        cur = goals.get(goal_id)
        if cur is None:
            continue
        if event_type == "wizard.goal_updated":
            if p.get("cadence_minutes") is not None:
                cur["cadence_minutes"] = int(p.get("cadence_minutes") or 1440)
            if p.get("next_run_ts") is not None:
                cur["next_run_ts"] = int(p.get("next_run_ts") or 0)
        elif event_type == "wizard.goal_approved":
            cur["status"] = "active"
            cur["next_run_ts"] = int(p.get("next_run_ts") or cur.get("next_run_ts") or 0)
        elif event_type == "wizard.goal_paused":
            cur["status"] = "paused"
        elif event_type == "wizard.goal_resumed":
            cur["status"] = "active"
            cur["next_run_ts"] = int(p.get("next_run_ts") or cur.get("next_run_ts") or 0)
        elif event_type == "scheduler.goal_executed":
            if p.get("next_run_ts") is not None:
                cur["next_run_ts"] = int(p.get("next_run_ts") or 0)
    return list(goals.values())


@router.post("/tick")
async def scheduler_tick(body: TickRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_admin_bearer(authorization)
    _ensure_runtime_enabled()
    now = body.now_ts if body.now_ts is not None else int(time.time())
    goals = _goal_state(body.tenant_id)
    due = [g for g in goals if g.get("status") == "active" and int(g.get("next_run_ts") or 0) <= now]
    due.sort(key=lambda g: (int(g.get("next_run_ts") or 0), str(g.get("goal_id") or "")))
    due = due[: body.limit]

    executed: list[dict[str, Any]] = []
    for goal in due:
        goal_id = str(goal.get("goal_id") or "")
        cadence_minutes = int(goal.get("cadence_minutes") or 1440)
        cadence_seconds = max(60, cadence_minutes * 60)
        slot_ts = now - (now % cadence_seconds)
        next_run_ts = slot_ts + cadence_seconds
        rec = {
            "goal_id": goal_id,
            "execution_id": str(uuid.uuid4()),
            "run_ts": now,
            "next_run_ts": next_run_ts,
            "outcome": "executed",
        }
        executed.append(rec)
        if body.dry_run:
            continue
        emit_event(
            tenant_id=body.tenant_id,
            rid=goal_id,
            event_type="scheduler.goal_executed",
            payload_dict={
                "tenant_id": body.tenant_id,
                "goal_id": goal_id,
                "execution_id": rec["execution_id"],
                "run_ts": now,
                "next_run_ts": next_run_ts,
                "outcome": "executed",
            },
            idempotency_key=f"scheduler_tick:{goal_id}:{slot_ts}",
        )

    return {
        "ok": True,
        "tenant_id": body.tenant_id,
        "dry_run": body.dry_run,
        "due_count": len(due),
        "executed_count": len(executed) if not body.dry_run else 0,
        "planned": executed,
    }


def selftests() -> dict[str, Any]:
    return {"ok": True}


def security_checks() -> dict[str, Any]:
    if _admin_api_key() is None:
        return {"ok": False, "message": "VOZ_ADMIN_API_KEY missing; scheduler tick calls will be unauthorized"}
    return {"ok": True}


def load_profile() -> dict[str, Any]:
    return {"hint": "scheduler-tick", "p50_ms": 20, "p95_ms": 180}


FEATURE = {
    "key": "scheduler_tick",
    "router": router,
    "enabled_env": "VOZ_FEATURE_SCHEDULER_TICK",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
