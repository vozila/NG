"""VOZLIA FILE PURPOSE
Purpose: owner-authenticated deterministic analytics query endpoint (QuerySpec + safe executor).
Hot path: no (owner control-plane only).
Feature flags:
  - VOZ_FEATURE_OWNER_ANALYTICS_QUERY
  - VOZ_OWNER_ANALYTICS_QUERY_ENABLED
Failure mode:
  - unauthorized => 401
  - invalid query spec => 422
  - invalid time window => 400
"""

from __future__ import annotations

import os
import sqlite3
import time
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.config import is_debug
from core.db import get_conn
from core.logging import logger

router = APIRouter(prefix="/owner/analytics", tags=["owner-analytics-query"])

MAX_WINDOW_S = 7 * 24 * 60 * 60
DEFAULT_WINDOW_S = 24 * 60 * 60

MetricName = Literal["count_calls", "count_leads", "count_appt_requests", "count_transcripts"]
DimensionName = Literal["day", "event_type", "ai_mode"]
ModeName = Literal["customer", "owner"]
EventFilterName = Literal[
    "flow_a.call_started",
    "flow_a.call_stopped",
    "flow_a.transcript_completed",
    "postcall.summary",
    "postcall.lead",
    "postcall.appt_request",
]

METRIC_EVENT_TYPE: dict[MetricName, str] = {
    "count_calls": "flow_a.call_started",
    "count_leads": "postcall.lead",
    "count_appt_requests": "postcall.appt_request",
    "count_transcripts": "flow_a.transcript_completed",
}


def _dbg(msg: str) -> None:
    if is_debug():
        logger.info(msg)


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


class QueryFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    event_types: list[EventFilterName] = Field(default_factory=list)
    ai_modes: list[ModeName] = Field(default_factory=list)


class QuerySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    metrics: list[MetricName] = Field(min_length=1, max_length=8)
    dimensions: list[DimensionName] = Field(default_factory=list, max_length=3)
    filters: QueryFilters = Field(default_factory=QueryFilters)
    limit: int = Field(default=100, ge=1, le=200)

    @model_validator(mode="after")
    def _dedupe_validate(self) -> "QuerySpec":
        if len(set(self.metrics)) != len(self.metrics):
            raise ValueError("metrics must be unique")
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError("dimensions must be unique")
        if len(set(self.filters.event_types)) != len(self.filters.event_types):
            raise ValueError("filters.event_types must be unique")
        if len(set(self.filters.ai_modes)) != len(self.filters.ai_modes):
            raise ValueError("filters.ai_modes must be unique")
        return self


class AnalyticsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: str = Field(min_length=1)
    since_ts: int | None = Field(default=None, ge=0)
    until_ts: int | None = Field(default=None, ge=0)
    query: QuerySpec


def _resolve_window(since_ts: int | None, until_ts: int | None) -> tuple[int, int]:
    now = int(time.time())
    end = int(until_ts) if until_ts is not None else now
    start = int(since_ts) if since_ts is not None else max(0, end - DEFAULT_WINDOW_S)
    if start > end:
        raise HTTPException(status_code=400, detail="since_ts must be <= until_ts")
    if (end - start) > MAX_WINDOW_S:
        raise HTTPException(status_code=400, detail="window exceeds max 7 days")
    return start, end


def _json1_available(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute("SELECT json_extract('{\"x\":1}', '$.x') AS v").fetchone()
        return bool(row) and int(row["v"]) == 1
    except Exception:
        return False


def _ai_mode_expr(*, json1: bool) -> str:
    if json1:
        return "COALESCE(json_extract(payload_json, '$.ai_mode'), 'unknown')"
    return (
        "CASE "
        "WHEN payload_json LIKE '%\"ai_mode\":\"owner\"%' THEN 'owner' "
        "WHEN payload_json LIKE '%\"ai_mode\":\"customer\"%' THEN 'customer' "
        "ELSE 'unknown' END"
    )


@router.post("/query")
async def owner_analytics_query(
    body: AnalyticsRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    if (os.getenv("VOZ_OWNER_ANALYTICS_QUERY_ENABLED") or "0").strip() != "1":
        raise HTTPException(status_code=503, detail="owner analytics query disabled")

    start, end = _resolve_window(body.since_ts, body.until_ts)

    with get_conn() as conn:
        json1 = _json1_available(conn)
        ai_mode_expr = _ai_mode_expr(json1=json1)
        dimension_expr: dict[DimensionName, str] = {
            "day": "strftime('%Y-%m-%d', ts, 'unixepoch')",
            "event_type": "event_type",
            "ai_mode": ai_mode_expr,
        }

        select_parts: list[str] = []
        group_parts: list[str] = []
        order_parts: list[str] = []
        for dim in body.query.dimensions:
            expr = dimension_expr[dim]
            select_parts.append(f"{expr} AS {dim}")
            group_parts.append(expr)
            order_parts.append(dim)

        for metric in body.query.metrics:
            et = METRIC_EVENT_TYPE[metric]
            select_parts.append(f"SUM(CASE WHEN event_type = '{et}' THEN 1 ELSE 0 END) AS {metric}")

        where = ["tenant_id = ?", "ts >= ?", "ts <= ?"]
        params: list[Any] = [body.tenant_id, start, end]
        if body.query.filters.event_types:
            placeholders = ",".join("?" for _ in body.query.filters.event_types)
            where.append(f"event_type IN ({placeholders})")
            params.extend(body.query.filters.event_types)
        if body.query.filters.ai_modes:
            placeholders = ",".join("?" for _ in body.query.filters.ai_modes)
            where.append(f"{ai_mode_expr} IN ({placeholders})")
            params.extend(body.query.filters.ai_modes)

        sql = f"SELECT {', '.join(select_parts)} FROM events WHERE {' AND '.join(where)}"
        if group_parts:
            sql += f" GROUP BY {', '.join(group_parts)}"
            sql += f" ORDER BY {', '.join(order_parts)}"
            sql += " LIMIT ?"
            params.append(body.query.limit)

        rows = conn.execute(sql, params).fetchall()

    out_rows: list[dict[str, Any]] = []
    totals: dict[str, int] = {metric: 0 for metric in body.query.metrics}
    for row in rows:
        obj: dict[str, Any] = {}
        for dim in body.query.dimensions:
            obj[dim] = row[dim]
        for metric in body.query.metrics:
            v = int(row[metric] or 0)
            obj[metric] = v
            totals[metric] += v
        out_rows.append(obj)

    if not body.query.dimensions:
        # For non-grouped queries, ensure one row shape even when no rows exist.
        if not out_rows:
            zero_row = {metric: 0 for metric in body.query.metrics}
            out_rows.append(zero_row)

    _dbg(
        f"OWNER_ANALYTICS_QUERY tenant_id={body.tenant_id} since_ts={start} "
        f"until_ts={end} metrics={body.query.metrics} dims={body.query.dimensions}"
    )
    return {
        "ok": True,
        "tenant_id": body.tenant_id,
        "window": {"since_ts": start, "until_ts": end},
        "query": body.query.model_dump(),
        "rows": out_rows,
        "totals": totals,
    }


def selftests() -> dict[str, Any]:
    return {"ok": True}


def security_checks() -> dict[str, Any]:
    if _owner_api_key() is None:
        return {"ok": False, "message": "VOZ_OWNER_API_KEY missing; owner analytics query will be unauthorized"}
    return {"ok": True}


def load_profile() -> dict[str, Any]:
    return {"hint": "owner-analytics-query", "p50_ms": 20, "p95_ms": 140}


FEATURE = {
    "key": "owner_analytics_query",
    "router": router,
    "enabled_env": "VOZ_FEATURE_OWNER_ANALYTICS_QUERY",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
