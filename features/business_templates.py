"""VOZLIA FILE PURPOSE
Purpose: owner-authenticated business templates v1 catalog and tenant selection.
Hot path: no (owner control-plane only).
Feature flags: VOZ_FEATURE_BUSINESS_TEMPLATES.
Failure mode:
  - unauthorized => 401
  - bad template selection => 400
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from core.db import emit_event, query_events

router = APIRouter(prefix="/owner/business/templates", tags=["business-templates"])

_SELECTED = "owner.business_template.selected"
_CATALOG_DEFAULT = [
    {
        "template_id": "front_desk_general_v1",
        "label": "Front Desk - General",
        "instructions": "Greet callers, collect intent, and route with concise confirmations.",
    },
    {
        "template_id": "med_spa_booking_v1",
        "label": "Med Spa - Booking",
        "instructions": "Prioritize appointment capture, eligibility checks, and gentle upsell prompts.",
    },
]


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


def _catalog() -> list[dict[str, str]]:
    raw = (os.getenv("VOZ_BUSINESS_TEMPLATES_JSON") or "").strip()
    if not raw:
        return list(_CATALOG_DEFAULT)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="VOZ_BUSINESS_TEMPLATES_JSON invalid") from exc
    if not isinstance(parsed, list) or not parsed:
        raise HTTPException(status_code=400, detail="VOZ_BUSINESS_TEMPLATES_JSON must be a non-empty list")
    out: list[dict[str, str]] = []
    for row in parsed:
        if not isinstance(row, dict):
            continue
        template_id = str(row.get("template_id") or "").strip()
        label = str(row.get("label") or "").strip()
        instructions = str(row.get("instructions") or "").strip()
        if not template_id or not label or not instructions:
            continue
        out.append({"template_id": template_id, "label": label, "instructions": instructions})
    if not out:
        raise HTTPException(status_code=400, detail="template catalog has no valid entries")
    return out


def _catalog_map() -> dict[str, dict[str, str]]:
    return {row["template_id"]: row for row in _catalog()}


def _latest_selection(tenant_id: str) -> dict[str, Any] | None:
    rows = query_events(tenant_id=tenant_id, event_type=_SELECTED, limit=200)
    if not rows:
        return None
    payload = rows[-1].get("payload")
    return payload if isinstance(payload, dict) else None


class TemplateSelectionRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    template_id: str = Field(min_length=1)
    custom_instructions: str | None = Field(default=None, max_length=2000)


@router.get("/catalog")
async def templates_catalog(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    return {"ok": True, "version": "v1", "templates": _catalog()}


@router.get("/current")
async def templates_current(
    tenant_id: str = Query(..., min_length=1),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    catalog = _catalog_map()
    selected = _latest_selection(tenant_id)
    if selected is None:
        first = _catalog()[0]
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "selection": {
                "template_id": first["template_id"],
                "label": first["label"],
                "instructions": first["instructions"],
                "custom_instructions": None,
            },
        }
    template_id = str(selected.get("template_id") or "")
    base = catalog.get(template_id)
    if base is None:
        raise HTTPException(status_code=400, detail=f"unknown template_id in history: {template_id}")
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "selection": {
            "template_id": template_id,
            "label": base["label"],
            "instructions": base["instructions"],
            "custom_instructions": selected.get("custom_instructions"),
        },
    }


@router.put("/current")
async def templates_set_current(
    body: TemplateSelectionRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_owner_bearer(authorization)
    catalog = _catalog_map()
    base = catalog.get(body.template_id)
    if base is None:
        raise HTTPException(status_code=400, detail=f"unknown template_id: {body.template_id}")
    payload = body.model_dump()
    event_id = emit_event(
        tenant_id=body.tenant_id,
        rid=f"business-template:{body.tenant_id}",
        event_type=_SELECTED,
        payload_dict=payload,
    )
    return {
        "ok": True,
        "tenant_id": body.tenant_id,
        "event_id": event_id,
        "selection": {
            "template_id": body.template_id,
            "label": base["label"],
            "instructions": base["instructions"],
            "custom_instructions": body.custom_instructions,
        },
    }


def selftests() -> dict[str, Any]:
    return {"ok": True}


def security_checks() -> dict[str, Any]:
    if _owner_api_key() is None:
        return {"ok": False, "message": "VOZ_OWNER_API_KEY missing; business template calls will be unauthorized"}
    return {"ok": True}


def load_profile() -> dict[str, Any]:
    return {"hint": "business-templates", "p50_ms": 10, "p95_ms": 100}


FEATURE = {
    "key": "business_templates",
    "router": router,
    "enabled_env": "VOZ_FEATURE_BUSINESS_TEMPLATES",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}

