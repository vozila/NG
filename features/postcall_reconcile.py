"""VOZLIA FILE PURPOSE
Purpose: admin out-of-band reconcile runner for missed post-call extraction writes.
Hot path: no (admin control plane only).
Feature flags:
  - VOZ_FEATURE_POSTCALL_RECONCILE
  - VOZ_POSTCALL_RECONCILE_ENABLED
Failure mode:
  - unauthorized => 401
  - runtime gate off => 503
  - per-rid extract failures counted in response (batch continues)
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.config import is_debug
from core.db import get_conn, query_events_for_rid
from core.logging import logger

router = APIRouter(prefix="/admin/postcall", tags=["postcall-reconcile"])


def _dbg(msg: str) -> None:
    if is_debug():
        logger.info(msg)


class ReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: str = Field(min_length=1)
    since_ts: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)
    dry_run: bool = False


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


def _self_base_url() -> str:
    configured = (os.getenv("VOZ_SELF_BASE_URL") or "").strip()
    if configured:
        return configured.rstrip("/")
    port = (os.getenv("PORT") or "8000").strip() or "8000"
    return f"http://127.0.0.1:{port}"


def _allowed_self_hosts() -> set[str]:
    hosts = {"127.0.0.1", "localhost", "::1"}
    for name in ("RENDER_EXTERNAL_HOSTNAME", "RENDER_INTERNAL_HOSTNAME"):
        raw = (os.getenv(name) or "").strip().lower()
        if raw:
            hosts.add(raw)
    extra = (os.getenv("VOZ_SELF_BASE_URL_ALLOWED_HOSTS") or "").strip()
    if extra:
        for part in extra.split(","):
            host = part.strip().lower()
            if host:
                hosts.add(host)
    return hosts


def _validated_self_base_url() -> str:
    base = _self_base_url()
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError("VOZ_SELF_BASE_URL must use http or https")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise RuntimeError("VOZ_SELF_BASE_URL missing hostname")
    if host not in _allowed_self_hosts():
        raise RuntimeError(f"VOZ_SELF_BASE_URL host not allowed: {host}")
    return base


def _extract_timeout_s() -> float:
    raw = (os.getenv("VOZ_POSTCALL_RECONCILE_TIMEOUT_MS") or "3000").strip()
    try:
        ms = int(raw)
    except Exception:
        ms = 3000
    ms = max(250, min(ms, 15000))
    return ms / 1000.0


def _reconcile_concurrency() -> int:
    raw = (os.getenv("VOZ_POSTCALL_RECONCILE_CONCURRENCY") or "4").strip()
    try:
        n = int(raw)
    except Exception:
        n = 4
    return max(1, min(n, 10))


def _recent_call_stopped_rows(*, tenant_id: str, since_ts: int, limit: int) -> list[dict[str, Any]]:
    # Recent-first scan avoids repeatedly reconciling old calls when limit is bounded.
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT event_id, tenant_id, rid, event_type, ts, payload_json
            FROM events
            WHERE tenant_id = ? AND event_type = 'flow_a.call_stopped' AND ts >= ?
            ORDER BY ts DESC, event_id DESC
            LIMIT ?
            """,
            (tenant_id, int(since_ts), int(limit)),
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


def _invoke_extract_http(*, tenant_id: str, rid: str, ai_mode: str, idempotency_key: str) -> tuple[int, str]:
    admin_key = _admin_api_key()
    if admin_key is None:
        raise RuntimeError("VOZ_ADMIN_API_KEY missing")

    body = {
        "tenant_id": tenant_id,
        "rid": rid,
        "ai_mode": ai_mode,
        "idempotency_key": idempotency_key,
    }
    req = urllib.request.Request(
        url=f"{_validated_self_base_url()}/admin/postcall/extract",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {admin_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_extract_timeout_s()) as resp:
            return int(getattr(resp, "status", 200)), resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            detail = str(e)
        return int(e.code), detail
    except urllib.error.URLError as e:
        raise RuntimeError(f"extract_request_failed:{e}") from e


async def _trigger_extract(*, tenant_id: str, rid: str, ai_mode: str, idempotency_key: str) -> tuple[int, str]:
    return await asyncio.to_thread(
        _invoke_extract_http,
        tenant_id=tenant_id,
        rid=rid,
        ai_mode=ai_mode,
        idempotency_key=idempotency_key,
    )


@router.post("/reconcile")
async def postcall_reconcile(
    body: ReconcileRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_bearer(authorization)
    if (os.getenv("VOZ_POSTCALL_RECONCILE_ENABLED") or "0").strip() != "1":
        raise HTTPException(status_code=503, detail="postcall reconcile disabled")

    concurrency = _reconcile_concurrency()
    _dbg(
        f"POSTCALL_RECONCILE_START tenant_id={body.tenant_id} since_ts={body.since_ts} "
        f"limit={body.limit} concurrency={concurrency}"
    )

    rows = _recent_call_stopped_rows(
        tenant_id=body.tenant_id,
        since_ts=body.since_ts,
        limit=body.limit,
    )

    attempted = 0
    created = 0
    skipped = 0
    errors = 0
    seen_rids: set[str] = set()

    candidates: list[tuple[str, str]] = []
    for row in rows:
        rid = str(row.get("rid") or "").strip()
        if not rid:
            errors += 1
            continue
        if rid in seen_rids:
            skipped += 1
            continue
        seen_rids.add(rid)

        existing_summary = query_events_for_rid(
            tenant_id=body.tenant_id,
            rid=rid,
            event_type="postcall.summary",
            limit=1,
        )
        if existing_summary:
            skipped += 1
            continue

        payload = row.get("payload")
        ai_mode = payload.get("ai_mode") if isinstance(payload, dict) else None
        if ai_mode not in ("customer", "owner"):
            errors += 1
            continue

        attempted += 1
        candidates.append((rid, ai_mode))

    if not body.dry_run and candidates:
        sem = asyncio.Semaphore(concurrency)

        async def _run_one(rid: str, ai_mode: str) -> tuple[bool, bool]:
            async with sem:
                try:
                    status, _resp = await _trigger_extract(
                        tenant_id=body.tenant_id,
                        rid=rid,
                        ai_mode=ai_mode,
                        idempotency_key=f"reconcile-{rid}-v1",
                    )
                    return (status == 200, status != 200)
                except Exception:
                    return (False, True)

        task_results = await asyncio.gather(*[_run_one(rid, ai_mode) for rid, ai_mode in candidates])
        for was_created, was_error in task_results:
            if was_created:
                created += 1
            if was_error:
                errors += 1

    _dbg(
        f"POSTCALL_RECONCILE_DONE attempted={attempted} created={created} "
        f"skipped={skipped} errors={errors}"
    )
    return {
        "ok": True,
        "tenant_id": body.tenant_id,
        "attempted": attempted,
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "dry_run": body.dry_run,
    }


def selftests() -> dict[str, Any]:
    return {"ok": True}


def security_checks() -> dict[str, Any]:
    if _admin_api_key() is None:
        return {"ok": False, "message": "VOZ_ADMIN_API_KEY missing; reconcile calls will be unauthorized"}
    try:
        _validated_self_base_url()
    except Exception as e:
        return {"ok": False, "message": f"invalid VOZ_SELF_BASE_URL config: {e}"}
    return {"ok": True}


def load_profile() -> dict[str, Any]:
    return {"hint": "admin-reconcile-batch", "p50_ms": 60, "p95_ms": 700}


FEATURE = {
    "key": "postcall_reconcile",
    "router": router,
    "enabled_env": "VOZ_FEATURE_POSTCALL_RECONCILE",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
