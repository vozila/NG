"""VOZLIA FILE PURPOSE
Purpose: out-of-band post-call extraction endpoint (summary/lead/appointment request).
Hot path: no (admin control plane only).
Feature flags:
  - VOZ_FEATURE_POSTCALL_EXTRACT
  - VOZ_POSTCALL_EXTRACT_ENABLED
Failure mode:
  - unauthorized => 401
  - missing transcript facts => 404
  - schema-invalid extraction => write postcall.extract_failed and return 422
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.config import is_debug
from core.db import emit_event, query_events_for_rid
from core.logging import logger

router = APIRouter(prefix="/admin/postcall", tags=["postcall-extract"])


def _dbg(msg: str) -> None:
    if is_debug():
        logger.info(msg)


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: str = Field(min_length=1)
    rid: str = Field(min_length=1)
    ai_mode: Literal["customer", "owner"]
    idempotency_key: str = Field(min_length=1)


class SummaryJSON(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    headline: str = Field(min_length=1, max_length=180)
    bullet_points: list[str] = Field(min_length=1, max_length=5)
    sentiment: Literal["positive", "neutral", "negative"]
    urgency: Literal["low", "medium", "high"] = "low"
    action_items: list[str] = Field(default_factory=list, max_length=5)


class LeadJSON(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    qualified: bool
    score: int = Field(ge=0, le=100)
    stage: Literal["hot", "warm", "cold"]
    reasons: list[str] = Field(min_length=1, max_length=5)
    callback_requested: bool = False
    talk_to_owner: bool = False
    preferred_contact: Literal["phone", "sms", "email", "unknown"] = "unknown"


class AppointmentRequestJSON(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    requested: bool
    channel: Literal["phone", "sms", "email", "unknown"]
    preferred_window: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractOutputJSON(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    summary: SummaryJSON
    lead: LeadJSON
    appt_request: AppointmentRequestJSON


def _configured_api_keys() -> list[str]:
    keys: list[str] = []
    for env_name in ("VOZ_ADMIN_API_KEY",):
        value = (os.getenv(env_name) or "").strip()
        if value:
            keys.append(value)
    return keys


def _authorized(auth_header: str | None) -> bool:
    configured = _configured_api_keys()
    if not configured or not isinstance(auth_header, str):
        return False
    prefix = "Bearer "
    if not auth_header.startswith(prefix):
        return False
    token = auth_header[len(prefix) :].strip()
    return token in configured


def _require_bearer(authorization: str | None) -> None:
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")


def _extract_transcript_text(*, tenant_id: str, rid: str) -> tuple[str, int]:
    rows: list[dict[str, Any]] = []
    for event_type in ("flow_a.transcript_completed", "call.transcript.completed"):
        rows.extend(
            query_events_for_rid(
                tenant_id=tenant_id,
                rid=rid,
                event_type=event_type,
                limit=1000,
            )
        )
    rows.sort(key=lambda r: (int(r.get("ts", 0)), str(r.get("event_id", ""))))

    lines: list[str] = []
    hit_count = 0
    for row in rows:
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        for key in ("transcript", "text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                lines.append(value.strip())
                hit_count += 1
                break
    transcript = "\n".join(lines).strip()
    return transcript, hit_count


def _pick_sentiment(transcript_lower: str) -> str:
    if any(w in transcript_lower for w in ("angry", "upset", "frustrated", "bad", "issue")):
        return "negative"
    if any(w in transcript_lower for w in ("great", "good", "thanks", "perfect", "love")):
        return "positive"
    return "neutral"


def _heuristic_propose_json(*, transcript: str, ai_mode: str) -> dict[str, Any]:
    # Deterministic fallback contract; output is still strictly schema-validated.
    lower = transcript.lower()
    clipped = " ".join(transcript.split())
    if len(clipped) > 140:
        clipped = clipped[:140].rstrip() + "..."

    requested = any(
        token in lower for token in ("appointment", "book", "schedule", "meeting", "call me", "next week")
    )
    callback_requested = any(token in lower for token in ("call me", "callback", "call back"))
    talk_to_owner = any(token in lower for token in ("owner", "manager", "supervisor"))
    hot = any(token in lower for token in ("buy", "ready", "price", "quote", "contract", "sign"))
    score = 80 if hot else 45
    stage = "hot" if hot else "warm"
    sentiment = _pick_sentiment(lower)
    urgency = "high" if talk_to_owner else ("medium" if requested or hot else "low")

    preferred_window: str | None = None
    m = re.search(r"\b(tomorrow|monday|tuesday|wednesday|thursday|friday|next week)\b", lower)
    if m:
        preferred_window = m.group(1)

    headline = f"{ai_mode} call: {clipped or 'no transcript content'}"
    return {
        "summary": {
            "headline": headline,
            "bullet_points": [
                f"Transcript chars: {len(transcript)}",
                f"Appointment requested: {requested}",
            ],
            "sentiment": sentiment,
            "urgency": urgency,
            "action_items": ["owner follow-up requested"] if talk_to_owner else [],
        },
        "lead": {
            "qualified": hot,
            "score": score,
            "stage": stage if hot else "cold" if "not interested" in lower else stage,
            "reasons": ["purchase intent detected" if hot else "follow-up needed"],
            "callback_requested": callback_requested,
            "talk_to_owner": talk_to_owner,
            "preferred_contact": "phone" if callback_requested else "unknown",
        },
        "appt_request": {
            "requested": requested,
            "channel": "phone",
            "preferred_window": preferred_window,
            "confidence": 0.9 if requested else 0.35,
        },
    }


def _model_extract_enabled() -> bool:
    return (os.getenv("VOZ_POSTCALL_EXTRACT_MODEL_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _model_name() -> str:
    return (os.getenv("VOZ_POSTCALL_EXTRACT_MODEL") or "gpt-4o-mini").strip() or "gpt-4o-mini"


def _openai_api_key() -> str | None:
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    return key or None


def _extract_response_text(response_obj: dict[str, Any]) -> str:
    text = response_obj.get("output_text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    output = response_obj.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                for key in ("text", "output_text"):
                    value = part.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
    raise ValueError("model output_text missing")


def _model_propose_json(*, transcript: str, ai_mode: str) -> dict[str, Any]:
    api_key = _openai_api_key()
    if api_key is None:
        raise RuntimeError("OPENAI_API_KEY missing")

    schema = ExtractOutputJSON.model_json_schema()
    system_prompt = (
        "You extract structured call outcomes from a transcript. "
        "Output JSON only, exactly matching the schema. "
        "Do not invent facts; if uncertain choose conservative values."
    )
    user_prompt = f"ai_mode={ai_mode}\n\nTranscript:\n{transcript}"
    request_body = {
        "model": _model_name(),
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
        ],
        "temperature": 0,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "postcall_extract",
                "schema": schema,
                "strict": True,
            }
        },
    }
    req = urllib.request.Request(
        url="https://api.openai.com/v1/responses",
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        raise RuntimeError(f"model_request_failed:{e}") from e

    response_obj = json.loads(raw)
    output_text = _extract_response_text(response_obj)
    parsed = json.loads(output_text)
    if not isinstance(parsed, dict):
        raise ValueError("model output must be a JSON object")
    return parsed


def _llm_propose_json(*, transcript: str, ai_mode: str) -> dict[str, Any]:
    if not _model_extract_enabled():
        _dbg("POSTCALL_EXTRACT_FALLBACK_USED reason=model_disabled")
        return _heuristic_propose_json(transcript=transcript, ai_mode=ai_mode)
    try:
        out = _model_propose_json(transcript=transcript, ai_mode=ai_mode)
        _dbg(f"POSTCALL_EXTRACT_MODEL_USED model={_model_name()} ai_mode={ai_mode}")
        return out
    except Exception as e:
        _dbg(f"POSTCALL_EXTRACT_FALLBACK_USED reason=model_error err={e!r}")
        return _heuristic_propose_json(transcript=transcript, ai_mode=ai_mode)


def _emit_failure_event(*, tenant_id: str, rid: str, idempotency_key: str, reason: str) -> None:
    emit_event(
        tenant_id=tenant_id,
        rid=rid,
        event_type="postcall.extract_failed",
        payload_dict={"tenant_id": tenant_id, "rid": rid, "reason": reason},
        idempotency_key=f"postcall_extract:{rid}:{idempotency_key}:failed",
    )


@router.post("/extract")
async def postcall_extract(
    body: ExtractRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_bearer(authorization)
    if (os.getenv("VOZ_POSTCALL_EXTRACT_ENABLED") or "0").strip() != "1":
        raise HTTPException(status_code=503, detail="postcall extraction disabled")

    transcript, transcript_events = _extract_transcript_text(tenant_id=body.tenant_id, rid=body.rid)
    if not transcript:
        raise HTTPException(status_code=404, detail="transcript_not_found")

    proposal = _llm_propose_json(transcript=transcript, ai_mode=body.ai_mode)
    try:
        parsed = ExtractOutputJSON.model_validate(proposal)
    except ValidationError as e:
        _emit_failure_event(
            tenant_id=body.tenant_id,
            rid=body.rid,
            idempotency_key=body.idempotency_key,
            reason=f"schema_invalid:{e.errors()[0].get('type', 'validation_error')}",
        )
        raise HTTPException(status_code=422, detail="schema_invalid") from e

    base_idem = f"postcall_extract:{body.rid}:{body.idempotency_key}"
    summary_event_id = emit_event(
        tenant_id=body.tenant_id,
        rid=body.rid,
        event_type="postcall.summary",
        payload_dict={
            "tenant_id": body.tenant_id,
            "rid": body.rid,
            "ai_mode": body.ai_mode,
            "transcript_events": transcript_events,
            **parsed.summary.model_dump(),
        },
        idempotency_key=f"{base_idem}:summary",
    )
    emitted: dict[str, str] = {"summary": summary_event_id}
    if body.ai_mode == "customer":
        lead_event_id = emit_event(
            tenant_id=body.tenant_id,
            rid=body.rid,
            event_type="postcall.lead",
            payload_dict={
                "tenant_id": body.tenant_id,
                "rid": body.rid,
                "ai_mode": body.ai_mode,
                **parsed.lead.model_dump(),
            },
            idempotency_key=f"{base_idem}:lead",
        )
        emitted["lead"] = lead_event_id

        if parsed.appt_request.requested:
            appt_event_id = emit_event(
                tenant_id=body.tenant_id,
                rid=body.rid,
                event_type="postcall.appt_request",
                payload_dict={
                    "tenant_id": body.tenant_id,
                    "rid": body.rid,
                    "ai_mode": body.ai_mode,
                    **parsed.appt_request.model_dump(),
                },
                idempotency_key=f"{base_idem}:appt_request",
            )
            emitted["appt_request"] = appt_event_id

    return {"ok": True, "rid": body.rid, "tenant_id": body.tenant_id, "events": emitted}


def selftests() -> dict[str, Any]:
    sample = _llm_propose_json(transcript="please schedule a meeting tomorrow", ai_mode="owner")
    parsed = ExtractOutputJSON.model_validate(sample)
    return {"ok": True, "appointment_requested": parsed.appt_request.requested}


def security_checks() -> dict[str, Any]:
    if not _configured_api_keys():
        return {"ok": False, "message": "VOZ_ADMIN_API_KEY required for auth"}
    return {"ok": True}


def load_profile() -> dict[str, Any]:
    return {"hint": "admin-postcall-extract", "p50_ms": 30, "p95_ms": 300}


FEATURE = {
    "key": "postcall_extract",
    "router": router,
    "enabled_env": "VOZ_FEATURE_POSTCALL_EXTRACT",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
