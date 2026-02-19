"""VOZLIA FILE PURPOSE
Purpose: owner-only deterministic summary analytics over event-store facts.
Hot path: no (owner control-plane reads only).
Feature flags: VOZ_FEATURE_OWNER_INSIGHTS.
Failure mode: auth failures => 401; bad window input => 400.
"""

from __future__ import annotations

import os
import sqlite3
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from core.config import is_debug
from core.db import get_conn
from core.logging import logger

router = APIRouter(prefix="/owner/insights", tags=["owner-insights"])

DEFAULT_WINDOW_S = 24 * 60 * 60
MAX_WINDOW_S = 7 * 24 * 60 * 60


def _dbg(msg: str) -> None:
    if is_debug():
        logger.info(msg)


def _owner_api_key() -> str | None:
    key = os.getenv("VOZ_OWNER_API_KEY", "").strip()
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


def _resolve_window(since_ts: int | None, until_ts: int | None) -> tuple[int, int]:
    now = int(time.time())
    end = int(until_ts) if until_ts is not None else now
    if end < 0:
        raise HTTPException(status_code=400, detail="until_ts must be >= 0")
    start = int(since_ts) if since_ts is not None else max(0, end - DEFAULT_WINDOW_S)
    if start < 0:
        raise HTTPException(status_code=400, detail="since_ts must be >= 0")
    if start > end:
        raise HTTPException(status_code=400, detail="since_ts must be <= until_ts")
    if (end - start) > MAX_WINDOW_S:
        start = end - MAX_WINDOW_S
    return start, end


def _count_event(conn, *, tenant_id: str, event_type: str, since_ts: int, until_ts: int) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM events
        WHERE tenant_id = ? AND event_type = ? AND ts >= ? AND ts <= ?
        """,
        (tenant_id, event_type, since_ts, until_ts),
    ).fetchone()
    return int(row["c"]) if row is not None else 0


def _count_qualified_leads(conn, *, tenant_id: str, since_ts: int, until_ts: int) -> int:
    # Preferred: JSON-aware count over structured payload field.
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM events
            WHERE tenant_id = ? AND event_type = 'postcall.lead'
              AND ts >= ? AND ts <= ?
              AND json_extract(payload_json, '$.qualified') = 1
            """,
            (tenant_id, since_ts, until_ts),
        ).fetchone()
        return int(row["c"]) if row is not None else 0
    except sqlite3.OperationalError:
        # Fallback for SQLite builds without JSON1.
        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM events
            WHERE tenant_id = ? AND event_type = 'postcall.lead'
              AND ts >= ? AND ts <= ?
              AND payload_json LIKE '%"qualified":true%'
            """,
            (tenant_id, since_ts, until_ts),
        ).fetchone()
        return int(row["c"]) if row is not None else 0


@router.get("/summary")
async def owner_insights_summary(
    tenant_id: str = Query(..., min_length=1),
    since_ts: int | None = Query(default=None),
    until_ts: int | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    start, end = _resolve_window(since_ts, until_ts)
    _dbg(f"OWNER_INSIGHTS_SUMMARY tenant_id={tenant_id} since_ts={start} until_ts={end}")

    with get_conn() as conn:
        call_started = _count_event(
            conn,
            tenant_id=tenant_id,
            event_type="flow_a.call_started",
            since_ts=start,
            until_ts=end,
        )
        call_stopped = _count_event(
            conn,
            tenant_id=tenant_id,
            event_type="flow_a.call_stopped",
            since_ts=start,
            until_ts=end,
        )
        transcript_completed = _count_event(
            conn,
            tenant_id=tenant_id,
            event_type="flow_a.transcript_completed",
            since_ts=start,
            until_ts=end,
        )
        postcall_summary = _count_event(
            conn,
            tenant_id=tenant_id,
            event_type="postcall.summary",
            since_ts=start,
            until_ts=end,
        )
        leads_total = _count_event(
            conn,
            tenant_id=tenant_id,
            event_type="postcall.lead",
            since_ts=start,
            until_ts=end,
        )
        appt_requests = _count_event(
            conn,
            tenant_id=tenant_id,
            event_type="postcall.appt_request",
            since_ts=start,
            until_ts=end,
        )
        leads_qualified = _count_qualified_leads(
            conn,
            tenant_id=tenant_id,
            since_ts=start,
            until_ts=end,
        )

        latest_row = conn.execute(
            """
            SELECT rid, ts
            FROM events
            WHERE tenant_id = ? AND ts >= ? AND ts <= ?
            ORDER BY ts DESC, event_id DESC
            LIMIT 1
            """,
            (tenant_id, start, end),
        ).fetchone()

    latest = None
    if latest_row is not None:
        latest = {"rid": str(latest_row["rid"]), "ts": int(latest_row["ts"])}

    return {
        "ok": True,
        "tenant_id": tenant_id,
        "window": {"since_ts": start, "until_ts": end},
        "counts": {
            "call_started": call_started,
            "call_stopped": call_stopped,
            "transcript_completed": transcript_completed,
            "postcall_summary": postcall_summary,
            "leads_total": leads_total,
            "leads_qualified": leads_qualified,
            "appt_requests": appt_requests,
        },
        "latest": latest,
    }


def selftests() -> dict[str, Any]:
    return {"ok": True}


def security_checks() -> dict[str, Any]:
    if _owner_api_key() is None:
        return {"ok": False, "message": "VOZ_OWNER_API_KEY missing; owner insights calls will be unauthorized"}
    return {"ok": True}


def load_profile() -> dict[str, Any]:
    return {"hint": "owner-insights-summary", "p50_ms": 10, "p95_ms": 90}


FEATURE = {
    "key": "owner_insights",
    "router": router,
    "enabled_env": "VOZ_FEATURE_OWNER_INSIGHTS",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
