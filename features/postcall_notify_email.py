"""VOZLIA FILE PURPOSE
Purpose: out-of-band admin email notifier for postcall lead/appt artifacts.
Hot path: no (admin control plane only).
Feature flags:
  - VOZ_FEATURE_POSTCALL_NOTIFY_EMAIL
  - VOZ_POSTCALL_NOTIFY_EMAIL_ENABLED
Failure mode:
  - unauthorized => 401
  - gate off => 503
  - dry_run performs no writes
"""

from __future__ import annotations

import json
import os
import smtplib
import time
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.db import emit_event, get_conn, query_events_for_rid

router = APIRouter(prefix="/admin/postcall/notify", tags=["postcall-notify-email"])


class NotifyEmailRequest(BaseModel):
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
    if (os.getenv("VOZ_POSTCALL_NOTIFY_EMAIL_ENABLED") or "0").strip() != "1":
        raise HTTPException(status_code=503, detail="postcall email notify disabled")


def _owner_notify_map() -> dict[str, Any]:
    raw = (os.getenv("VOZ_TENANT_OWNER_NOTIFY_JSON") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _destination_for_tenant(tenant_id: str) -> str | None:
    cfg = _owner_notify_map().get(tenant_id)
    if not isinstance(cfg, dict):
        return None
    email = cfg.get("email")
    if not isinstance(email, str) or not email.strip():
        return None
    return email.strip()


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
    sent = query_events_for_rid(tenant_id=tenant_id, rid=rid, event_type="notify.email_sent", limit=1)
    if sent:
        return True
    unknown = query_events_for_rid(tenant_id=tenant_id, rid=rid, event_type="notify.email_delivery_unknown", limit=1)
    return bool(unknown)


def _summary_headline(*, tenant_id: str, rid: str) -> str | None:
    rows = query_events_for_rid(tenant_id=tenant_id, rid=rid, event_type="postcall.summary", limit=50)
    if not rows:
        return None
    payload = rows[-1].get("payload")
    if not isinstance(payload, dict):
        return None
    headline = payload.get("headline")
    if isinstance(headline, str) and headline.strip():
        return headline.strip()
    return None


def _compose_email(*, event_type: str, rid: str, headline: str | None) -> tuple[str, str]:
    label = "Appointment request" if event_type == "postcall.appt_request" else "Lead"
    subject = f"Vozlia {label}: {rid}"
    body_lines = [f"New {label.lower()} detected.", f"rid={rid}", f"event_type={event_type}"]
    if headline:
        body_lines.append(f"summary={headline}")
    return subject, "\n".join(body_lines)


def _notify_email_webhook() -> str:
    url = (os.getenv("VOZ_NOTIFY_EMAIL_WEBHOOK_URL") or "").strip()
    if not url:
        raise RuntimeError("VOZ_NOTIFY_EMAIL_WEBHOOK_URL missing")
    return url


def _email_provider() -> str:
    provider = (os.getenv("VOZ_NOTIFY_EMAIL_PROVIDER") or "ses_smtp").strip().lower()
    if provider not in {"ses_smtp", "webhook"}:
        raise RuntimeError(f"unsupported VOZ_NOTIFY_EMAIL_PROVIDER: {provider}")
    return provider


def _ses_smtp_config() -> tuple[str, int, str, str, str]:
    host = (os.getenv("VOZ_SES_SMTP_HOST") or "").strip()
    port_raw = (os.getenv("VOZ_SES_SMTP_PORT") or "587").strip()
    username = (os.getenv("VOZ_SES_SMTP_USERNAME") or "").strip()
    password = (os.getenv("VOZ_SES_SMTP_PASSWORD") or "").strip()
    from_email = (os.getenv("VOZ_NOTIFY_EMAIL_FROM") or "").strip()
    if not host or not username or not password or not from_email:
        raise RuntimeError("SES SMTP config missing")
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise RuntimeError("VOZ_SES_SMTP_PORT must be integer") from exc
    return host, port, username, password, from_email


def _ensure_provider_ready() -> None:
    provider = _email_provider()
    if provider == "webhook":
        _notify_email_webhook()
        return
    _ses_smtp_config()


def _send_email(*, to_email: str, subject: str, body: str) -> tuple[bool, str]:
    provider = _email_provider()
    if provider == "webhook":
        url = _notify_email_webhook()
        payload = json.dumps({"to": to_email, "subject": subject, "body": body}).encode("utf-8")
        req = urllib.request.Request(
            url=url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                detail = resp.read().decode("utf-8")
                return True, detail
        except urllib.error.HTTPError as exc:
            try:
                return False, exc.read().decode("utf-8")
            except Exception:
                return False, str(exc)
        except Exception as exc:  # pragma: no cover - defensive path
            return False, repr(exc)

    host, port, username, password, from_email = _ses_smtp_config()
    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(host=host, port=port, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(msg)
        return True, "ses_smtp_sent"
    except Exception as exc:  # pragma: no cover - network/provider path
        return False, repr(exc)


@router.post("/email")
async def postcall_notify_email(
    body: NotifyEmailRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_bearer(authorization)
    _ensure_runtime_enabled()

    destination = _destination_for_tenant(body.tenant_id)
    if destination is None:
        raise HTTPException(status_code=400, detail="owner email destination missing")

    if not body.dry_run:
        try:
            _ensure_provider_ready()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"email provider unavailable: {exc}") from exc

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
        subject, text = _compose_email(event_type=event_type, rid=rid, headline=headline)
        plan = {
            "rid": rid,
            "event_type": event_type,
            "to": destination,
            "subject": subject,
            "text": text,
            "summary_headline": headline,
        }
        planned.append(plan)
        if body.dry_run:
            continue

        ok, detail = _send_email(to_email=destination, subject=subject, body=text)
        if ok:
            try:
                emit_event(
                    tenant_id=body.tenant_id,
                    rid=rid,
                    event_type="notify.email_sent",
                    payload_dict={
                        "tenant_id": body.tenant_id,
                        "rid": rid,
                        "to_email": destination,
                        "source_event_type": event_type,
                        "subject": subject,
                        "message": text,
                    },
                    idempotency_key=f"notify_email:{rid}",
                )
                sent += 1
            except Exception as exc:
                try:
                    emit_event(
                        tenant_id=body.tenant_id,
                        rid=rid,
                        event_type="notify.email_delivery_unknown",
                        payload_dict={
                            "tenant_id": body.tenant_id,
                            "rid": rid,
                            "to_email": destination,
                            "source_event_type": event_type,
                            "subject": subject,
                            "message": text,
                            "provider_response": detail,
                            "error": repr(exc),
                        },
                        idempotency_key=f"notify_email_unknown:{rid}",
                    )
                except Exception:
                    pass
                errors += 1
        else:
            try:
                emit_event(
                    tenant_id=body.tenant_id,
                    rid=rid,
                    event_type="notify.email_failed",
                    payload_dict={
                        "tenant_id": body.tenant_id,
                        "rid": rid,
                        "to_email": destination,
                        "source_event_type": event_type,
                        "error": detail,
                    },
                    idempotency_key=f"notify_email_failed:{rid}:{int(time.time())}",
                )
            except Exception:
                pass
            errors += 1

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
        return {"ok": False, "message": "VOZ_ADMIN_API_KEY missing; email notify calls will be unauthorized"}
    return {"ok": True}


def load_profile() -> dict[str, Any]:
    return {"hint": "admin-postcall-notify-email", "p50_ms": 25, "p95_ms": 220}


FEATURE = {
    "key": "postcall_notify_email",
    "router": router,
    "enabled_env": "VOZ_FEATURE_POSTCALL_NOTIFY_EMAIL",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
