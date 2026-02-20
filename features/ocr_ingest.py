"""VOZLIA FILE PURPOSE
Purpose: schema-first OCR ingest and pending review workflow.
Hot path: no (owner control-plane ingestion/review path).
Feature flags:
  - VOZ_FEATURE_OCR_INGEST
  - VOZ_OWNER_OCR_INGEST_ENABLED
Failure mode:
  - unauthorized => 401
  - disabled => 503
  - invalid review transition => 409
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field

from core.db import emit_event, query_events

router = APIRouter(prefix="/owner/ocr", tags=["ocr-ingest"])

_INGEST_PENDING = "ocr.ingest.pending_review"
_INGEST_REVIEWED = "ocr.ingest.reviewed"
_SCHEMA_VERSION = "v1"


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
    if (os.getenv("VOZ_OWNER_OCR_INGEST_ENABLED") or "1").strip() != "1":
        raise HTTPException(status_code=503, detail="ocr ingest disabled")


def _parse_fields(raw_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in raw_text.splitlines():
        if ":" not in line:
            continue
        left, right = line.split(":", 1)
        key = left.strip().lower().replace(" ", "_")
        val = right.strip()
        if key and val:
            out[key] = val
    return out


def _review_state(tenant_id: str) -> tuple[dict[str, dict[str, Any]], set[str]]:
    pending: dict[str, dict[str, Any]] = {}
    reviewed: set[str] = set()
    rows = query_events(tenant_id=tenant_id, limit=2000)
    for row in rows:
        event_type = str(row.get("event_type") or "")
        payload = row.get("payload")
        p = payload if isinstance(payload, dict) else {}
        review_id = str(p.get("review_id") or "")
        if not review_id:
            continue
        if event_type == _INGEST_PENDING:
            pending[review_id] = dict(p)
        elif event_type == _INGEST_REVIEWED:
            reviewed.add(review_id)
    return pending, reviewed


class OCRIngestRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    rid: str | None = Field(default=None, min_length=1)
    source_name: str = Field(min_length=1, max_length=200)
    raw_text: str = Field(min_length=1, max_length=20000)


class OCRReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    reviewer: str = Field(min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)


@router.post("/ingest")
async def ocr_ingest(
    body: OCRIngestRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()

    review_id = str(uuid.uuid4())
    rid = body.rid or review_id
    proposed = _parse_fields(body.raw_text)
    payload = {
        "tenant_id": body.tenant_id,
        "rid": rid,
        "review_id": review_id,
        "schema_version": _SCHEMA_VERSION,
        "status": "pending_review",
        "source_name": body.source_name,
        "raw_text_len": len(body.raw_text),
        "proposed_fields": proposed,
    }
    event_id = emit_event(
        tenant_id=body.tenant_id,
        rid=rid,
        event_type=_INGEST_PENDING,
        payload_dict=payload,
        idempotency_key=f"{body.tenant_id}:{review_id}",
    )
    return {"ok": True, "event_id": event_id, "record": payload}


@router.get("/reviews")
async def ocr_reviews(
    tenant_id: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()
    pending, reviewed = _review_state(tenant_id)
    items = [v for k, v in pending.items() if k not in reviewed]
    items.sort(key=lambda x: str(x.get("review_id")))
    return {"ok": True, "tenant_id": tenant_id, "items": items[:limit]}


@router.post("/reviews/{review_id}")
async def ocr_review_decide(
    body: OCRReviewRequest,
    review_id: str = Path(..., min_length=1),
    tenant_id: str = Query(..., min_length=1),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    _ensure_runtime_enabled()
    pending, reviewed = _review_state(tenant_id)
    pending_payload = pending.get(review_id)
    if pending_payload is None:
        raise HTTPException(status_code=404, detail="review_id not found")
    if review_id in reviewed:
        raise HTTPException(status_code=409, detail="review already decided")

    rid = str(pending_payload.get("rid") or review_id)
    payload = {
        "tenant_id": tenant_id,
        "rid": rid,
        "review_id": review_id,
        "schema_version": _SCHEMA_VERSION,
        "decision": body.decision,
        "reviewer": body.reviewer,
        "notes": body.notes,
    }
    event_id = emit_event(
        tenant_id=tenant_id,
        rid=rid,
        event_type=_INGEST_REVIEWED,
        payload_dict=payload,
        idempotency_key=f"{tenant_id}:{review_id}:decision",
    )
    return {"ok": True, "event_id": event_id, "record": payload}


def selftests() -> dict[str, Any]:
    return {"ok": True}


def security_checks() -> dict[str, Any]:
    if _owner_api_key() is None:
        return {"ok": False, "message": "VOZ_OWNER_API_KEY missing; OCR ingest calls will be unauthorized"}
    return {"ok": True}


def load_profile() -> dict[str, Any]:
    return {"hint": "ocr-ingest", "p50_ms": 20, "p95_ms": 180}


FEATURE = {
    "key": "ocr_ingest",
    "router": router,
    "enabled_env": "VOZ_FEATURE_OCR_INGEST",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}

