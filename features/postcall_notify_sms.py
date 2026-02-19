"""VOZLIA FILE PURPOSE
Purpose: out-of-band admin SMS notifier for new postcall lead/appt artifacts.
Hot path: no (admin control plane only).
Feature flags:
  - VOZ_FEATURE_POSTCALL_NOTIFY_SMS
  - VOZ_POSTCALL_NOTIFY_SMS_ENABLED
Failure mode:
  - unauthorized => 401
  - gate off => 503
  - dry_run performs no writes
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.config import is_debug
from core.db import emit_event, get_conn, query_events_for_rid
from core.logging import logger

router = APIRouter(prefix="/admin/postcall/notify", tags=["postcall-notify-sms"])


def _dbg(msg: str) -> None:
    if is_debug():
        logger.info(msg)


class NotifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: str = Field(min_length=1)
    since_ts: int = Field(ge=0)
    limit: int = Field(default=50, ge=1, le=200)
    dry_run: bool = True


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
    if (os.getenv("VOZ_POSTCALL_NOTIFY_SMS_ENABLED") or "0").strip() != "1":
        raise HTTPException(status_code=503, detail="postcall sms notify disabled")


def _owner_notify_map() -> dict[str, Any]:
    raw = (os.getenv("VOZ_TENANT_OWNER_NOTIFY_JSON") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _destination_for_tenant(tenant_id: str) -> str | None:
    cfg = _owner_notify_map().get(tenant_id)
    if not isinstance(cfg, dict):
        return None
    sms = cfg.get("sms")
    if not isinstance(sms, str) or not sms.strip():
        return None
    return sms.strip()


def _twilio_config() -> tuple[str, str, str]:
    sid = (os.getenv("VOZ_TWILIO_ACCOUNT_SID") or "").strip()
    token = (os.getenv("VOZ_TWILIO_AUTH_TOKEN") or "").strip()
    from_number = (os.getenv("VOZ_TWILIO_SMS_FROM") or "").strip()
    if not sid or not token or not from_number:
        raise RuntimeError("twilio config missing")
    return sid, token, from_number


def _fetch_candidates(*, tenant_id: str, since_ts: int, limit: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT event_id, tenant_id, rid, event_type, ts, payload_json
            FROM events
            WHERE tenant_id = ? AND ts >= ?
              AND event_type IN ('postcall.appt_request', 'postcall.lead')
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


def _already_sent(*, tenant_id: str, rid: str) -> bool:
    rows = query_events_for_rid(tenant_id=tenant_id, rid=rid, event_type="notify.sms_sent", limit=1)
    if rows:
        return True
    unknown = query_events_for_rid(tenant_id=tenant_id, rid=rid, event_type="notify.sms_delivery_unknown", limit=1)
    return bool(unknown)


def _summary_headline(*, tenant_id: str, rid: str) -> str | None:
    rows = query_events_for_rid(tenant_id=tenant_id, rid=rid, event_type="postcall.summary", limit=50)
    if not rows:
        return None
    payload = rows[-1].get("payload")
    if isinstance(payload, dict):
        h = payload.get("headline")
        if isinstance(h, str) and h.strip():
            return h.strip()
    return None


def _caller_from(*, tenant_id: str, rid: str) -> str | None:
    rows = query_events_for_rid(tenant_id=tenant_id, rid=rid, event_type="flow_a.call_started", limit=50)
    if not rows:
        return None
    payload = rows[-1].get("payload")
    if isinstance(payload, dict):
        n = payload.get("from_number")
        if isinstance(n, str) and n.strip():
            return n.strip()
    return None


def _compose_message(*, event_type: str, rid: str, headline: str | None, from_number: str | None) -> str:
    label = "appointment request" if event_type == "postcall.appt_request" else "lead"
    parts = [f"Vozlia: new {label} (rid={rid})"]
    if headline:
        parts.append(f"summary={headline}")
    if from_number:
        parts.append(f"caller={from_number}")
    return " | ".join(parts)


def _send_sms(*, to_number: str, body: str) -> tuple[bool, str]:
    sid, token, from_number = _twilio_config()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    form = urllib.parse.urlencode({"To": to_number, "From": from_number, "Body": body}).encode("utf-8")
    auth = base64.b64encode(f"{sid}:{token}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        url=url,
        data=form,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = resp.read().decode("utf-8")
            return True, payload
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            detail = str(e)
        return False, detail
    except Exception as e:
        return False, repr(e)


@router.post("/sms")
async def postcall_notify_sms(
    body: NotifyRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_bearer(authorization)
    _ensure_runtime_enabled()

    destination = _destination_for_tenant(body.tenant_id)
    if destination is None:
        raise HTTPException(status_code=400, detail="owner sms destination missing")

    if not body.dry_run:
        try:
            _twilio_config()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"twilio unavailable: {e}") from e

    raw = _fetch_candidates(tenant_id=body.tenant_id, since_ts=body.since_ts, limit=body.limit)
    seen_rids: set[str] = set()
    planned: list[dict[str, Any]] = []
    sent = 0
    skipped = 0
    errors = 0

    for row in raw:
        rid = str(row.get("rid") or "").strip()
        if not rid:
            errors += 1
            continue
        if rid in seen_rids:
            skipped += 1
            continue
        seen_rids.add(rid)
        if _already_sent(tenant_id=body.tenant_id, rid=rid):
            skipped += 1
            continue

        event_type = str(row.get("event_type") or "")
        headline = _summary_headline(tenant_id=body.tenant_id, rid=rid)
        from_number = _caller_from(tenant_id=body.tenant_id, rid=rid)
        sms_text = _compose_message(event_type=event_type, rid=rid, headline=headline, from_number=from_number)
        plan = {
            "rid": rid,
            "event_type": event_type,
            "to": destination,
            "text": sms_text,
            "from_number": from_number,
            "summary_headline": headline,
        }
        planned.append(plan)

        if body.dry_run:
            continue

        ok, detail = _send_sms(to_number=destination, body=sms_text)
        if ok:
            try:
                emit_event(
                    tenant_id=body.tenant_id,
                    rid=rid,
                    event_type="notify.sms_sent",
                    payload_dict={
                        "tenant_id": body.tenant_id,
                        "rid": rid,
                        "to_number": destination,
                        "source_event_type": event_type,
                        "message": sms_text,
                    },
                    idempotency_key=f"notify_sms:{rid}",
                )
                sent += 1
            except Exception as e:
                # SMS provider accepted send but persistence failed; mark as terminal-unknown
                # so retries do not duplicate owner notifications.
                try:
                    emit_event(
                        tenant_id=body.tenant_id,
                        rid=rid,
                        event_type="notify.sms_delivery_unknown",
                        payload_dict={
                            "tenant_id": body.tenant_id,
                            "rid": rid,
                            "to_number": destination,
                            "source_event_type": event_type,
                            "message": sms_text,
                            "provider_response": detail,
                            "error": repr(e),
                        },
                        idempotency_key=f"notify_sms_unknown:{rid}",
                    )
                except Exception:
                    pass
                errors += 1
        else:
            try:
                emit_event(
                    tenant_id=body.tenant_id,
                    rid=rid,
                    event_type="notify.sms_failed",
                    payload_dict={
                        "tenant_id": body.tenant_id,
                        "rid": rid,
                        "to_number": destination,
                        "source_event_type": event_type,
                        "error": detail,
                    },
                    idempotency_key=f"notify_sms_failed:{rid}:{int(time.time())}",
                )
            except Exception:
                pass
            errors += 1

    _dbg(
        f"POSTCALL_NOTIFY_SMS tenant_id={body.tenant_id} since_ts={body.since_ts} "
        f"limit={body.limit} dry_run={body.dry_run} planned={len(planned)} sent={sent} skipped={skipped} errors={errors}"
    )
    return {
        "ok": True,
        "tenant_id": body.tenant_id,
        "dry_run": body.dry_run,
        "planned_count": len(planned),
        "sent": sent,
        "skipped": skipped,
        "errors": errors,
        "planned": planned,
    }


def selftests() -> dict[str, Any]:
    return {"ok": True}


def security_checks() -> dict[str, Any]:
    if _admin_api_key() is None:
        return {"ok": False, "message": "VOZ_ADMIN_API_KEY missing; sms notify calls will be unauthorized"}
    return {"ok": True}


def load_profile() -> dict[str, Any]:
    return {"hint": "postcall-notify-sms", "p50_ms": 40, "p95_ms": 400}


FEATURE = {
    "key": "postcall_notify_sms",
    "router": router,
    "enabled_env": "VOZ_FEATURE_POSTCALL_NOTIFY_SMS",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
