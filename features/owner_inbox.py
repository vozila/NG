"""VOZLIA FILE PURPOSE
Purpose: owner-facing normalized inbox APIs for leads and appointment requests.
Hot path: no (owner control-plane reads only).
Feature flags:
  - VOZ_FEATURE_OWNER_INBOX
  - VOZ_OWNER_INBOX_ENABLED
Failure mode:
  - unauthorized => 401
  - invalid window => 400
  - invalid limit => 422
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from core.config import is_debug
from core.db import get_conn
from core.logging import logger

router = APIRouter(prefix="/owner/inbox", tags=["owner-inbox"])

MAX_WINDOW_S = 7 * 24 * 60 * 60
DEFAULT_WINDOW_S = 24 * 60 * 60


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


def _ensure_runtime_enabled() -> None:
    if (os.getenv("VOZ_OWNER_INBOX_ENABLED") or "0").strip() != "1":
        raise HTTPException(status_code=503, detail="owner inbox disabled")


def _resolve_window(since_ts: int | None, until_ts: int | None) -> tuple[int, int]:
    now = int(time.time())
    end = int(until_ts) if until_ts is not None else now
    start = int(since_ts) if since_ts is not None else max(0, end - DEFAULT_WINDOW_S)
    if start > end:
        raise HTTPException(status_code=400, detail="since_ts must be <= until_ts")
    if (end - start) > MAX_WINDOW_S:
        raise HTTPException(status_code=400, detail="window exceeds max 7 days")
    return start, end


def _fetch_source_rows(*, tenant_id: str, event_type: str, since_ts: int, until_ts: int, limit: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT event_id, tenant_id, rid, event_type, ts, payload_json
            FROM events
            WHERE tenant_id = ? AND event_type = ? AND ts >= ? AND ts <= ?
            ORDER BY ts DESC, event_id DESC
            LIMIT ?
            """,
            (tenant_id, event_type, since_ts, until_ts, int(limit)),
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


def _latest_fields_for_rids(
    *,
    tenant_id: str,
    rids: list[str],
    event_type: str,
    fields: list[str],
) -> dict[str, dict[str, Any]]:
    if not rids:
        return {}
    placeholders = ",".join(["?"] * len(rids))
    params: list[Any] = [tenant_id, event_type, *rids]
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT rid, payload_json, ts, event_id
            FROM events
            WHERE tenant_id = ? AND event_type = ? AND rid IN ({placeholders})
            ORDER BY ts DESC, event_id DESC
            """,
            params,
        ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        rid = str(row["rid"])
        if rid in out:
            continue
        payload = json.loads(str(row["payload_json"]))
        if not isinstance(payload, dict):
            continue
        out[rid] = {field: payload.get(field) for field in fields}
    return out


def _normalize_lead_item(
    *,
    row: dict[str, Any],
    summary_by_rid: dict[str, dict[str, Any]],
    caller_by_rid: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rid = str(row.get("rid") or "")
    payload = row.get("payload")
    p = payload if isinstance(payload, dict) else {}
    summary_headline = summary_by_rid.get(rid, {}).get("headline")
    from_number = caller_by_rid.get(rid, {}).get("from_number")
    to_number = caller_by_rid.get(rid, {}).get("to_number")
    return {
        "rid": rid,
        "ts": int(row.get("ts") or 0),
        "qualified": p.get("qualified"),
        "score": p.get("score"),
        "stage": p.get("stage"),
        "reasons": p.get("reasons"),
        "summary_headline": summary_headline,
        "from_number": from_number if isinstance(from_number, str) else None,
        "to_number": to_number if isinstance(to_number, str) else None,
    }


def _normalize_appt_item(
    *,
    row: dict[str, Any],
    summary_by_rid: dict[str, dict[str, Any]],
    caller_by_rid: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rid = str(row.get("rid") or "")
    payload = row.get("payload")
    p = payload if isinstance(payload, dict) else {}
    summary_headline = summary_by_rid.get(rid, {}).get("headline")
    from_number = caller_by_rid.get(rid, {}).get("from_number")
    to_number = caller_by_rid.get(rid, {}).get("to_number")
    return {
        "rid": rid,
        "ts": int(row.get("ts") or 0),
        "requested": p.get("requested"),
        "channel": p.get("channel"),
        "preferred_window": p.get("preferred_window"),
        "confidence": p.get("confidence"),
        "summary_headline": summary_headline,
        "from_number": from_number if isinstance(from_number, str) else None,
        "to_number": to_number if isinstance(to_number, str) else None,
    }


@router.get("/leads")
async def owner_inbox_leads(
    tenant_id: str = Query(..., min_length=1),
    since_ts: int | None = Query(default=None),
    until_ts: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()
    start, end = _resolve_window(since_ts, until_ts)
    rows = _fetch_source_rows(
        tenant_id=tenant_id,
        event_type="postcall.lead",
        since_ts=start,
        until_ts=end,
        limit=limit,
    )
    rids = [str(row.get("rid") or "") for row in rows if str(row.get("rid") or "").strip()]
    summary_by_rid = _latest_fields_for_rids(
        tenant_id=tenant_id,
        rids=rids,
        event_type="postcall.summary",
        fields=["headline"],
    )
    caller_by_rid = _latest_fields_for_rids(
        tenant_id=tenant_id,
        rids=rids,
        event_type="flow_a.call_started",
        fields=["from_number", "to_number"],
    )
    items = [
        _normalize_lead_item(
            row=row,
            summary_by_rid=summary_by_rid,
            caller_by_rid=caller_by_rid,
        )
        for row in rows
    ]
    _dbg(f"OWNER_INBOX_LEADS tenant_id={tenant_id} since_ts={start} until_ts={end} count={len(items)}")
    return {"ok": True, "tenant_id": tenant_id, "items": items}


@router.get("/appt_requests")
async def owner_inbox_appt_requests(
    tenant_id: str = Query(..., min_length=1),
    since_ts: int | None = Query(default=None),
    until_ts: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()
    start, end = _resolve_window(since_ts, until_ts)
    rows = _fetch_source_rows(
        tenant_id=tenant_id,
        event_type="postcall.appt_request",
        since_ts=start,
        until_ts=end,
        limit=limit,
    )
    rids = [str(row.get("rid") or "") for row in rows if str(row.get("rid") or "").strip()]
    summary_by_rid = _latest_fields_for_rids(
        tenant_id=tenant_id,
        rids=rids,
        event_type="postcall.summary",
        fields=["headline"],
    )
    caller_by_rid = _latest_fields_for_rids(
        tenant_id=tenant_id,
        rids=rids,
        event_type="flow_a.call_started",
        fields=["from_number", "to_number"],
    )
    items = [
        _normalize_appt_item(
            row=row,
            summary_by_rid=summary_by_rid,
            caller_by_rid=caller_by_rid,
        )
        for row in rows
    ]
    _dbg(f"OWNER_INBOX_APPTS tenant_id={tenant_id} since_ts={start} until_ts={end} count={len(items)}")
    return {"ok": True, "tenant_id": tenant_id, "items": items}


def selftests() -> dict[str, Any]:
    return {"ok": True}


def security_checks() -> dict[str, Any]:
    if _owner_api_key() is None:
        return {"ok": False, "message": "VOZ_OWNER_API_KEY missing; owner inbox calls will be unauthorized"}
    return {"ok": True}


def load_profile() -> dict[str, Any]:
    return {"hint": "owner-inbox", "p50_ms": 15, "p95_ms": 140}


FEATURE = {
    "key": "owner_inbox",
    "router": router,
    "enabled_env": "VOZ_FEATURE_OWNER_INBOX",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
