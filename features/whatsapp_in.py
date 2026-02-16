"""VOZLIA FILE PURPOSE
Purpose: WhatsApp inbound webhook adapter (minimal MVP).
Hot path: yes (inbound handler).
Feature flags: VOZ_FEATURE_WHATSAPP_IN.
Failure mode: normalize defensively, return deterministic stub result.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Any, Iterator

from fastapi import APIRouter

from core.config import is_debug
from core.logging import logger

router = APIRouter()


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str):
            out = value.strip()
            if out:
                return out
    return ""


def _parse_ts(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        if value.isdigit():
            return int(value)
    return int(time.time())


def normalize_inbound(payload: dict[str, Any]) -> dict[str, Any]:
    msg = payload.get("message")
    sender = payload.get("sender")
    recipient = payload.get("recipient")

    text = payload.get("text")
    if not isinstance(text, str):
        text = _first_str(
            text.get("body") if isinstance(text, dict) else None,
            msg.get("text") if isinstance(msg, dict) else None,
            msg.get("body") if isinstance(msg, dict) else None,
            payload.get("body"),
        )
    else:
        text = text.strip()

    media_urls: list[str] = []
    raw_media_urls = payload.get("media_urls")
    if isinstance(raw_media_urls, list):
        media_urls = [u.strip() for u in raw_media_urls if isinstance(u, str) and u.strip()]
    elif isinstance(payload.get("media"), list):
        for item in payload["media"]:
            if isinstance(item, dict):
                url = item.get("url")
                if isinstance(url, str) and url.strip():
                    media_urls.append(url.strip())

    event = {
        "channel": "whatsapp",
        "from": _first_str(
            payload.get("from"),
            sender.get("wa_id") if isinstance(sender, dict) else None,
            sender.get("id") if isinstance(sender, dict) else None,
        ),
        "to": _first_str(
            payload.get("to"),
            recipient.get("wa_id") if isinstance(recipient, dict) else None,
            recipient.get("id") if isinstance(recipient, dict) else None,
        ),
        "text": text,
        "media_urls": media_urls,
        "ts": _parse_ts(payload.get("ts") or payload.get("timestamp")),
    }
    return event


def _engine_stub(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "accepted",
        "engine": "stub",
        "channel": event["channel"],
        "chars": len(event.get("text", "")),
    }


@router.post("/whatsapp/inbound")
async def whatsapp_inbound(payload: dict[str, Any]) -> dict[str, Any]:
    event = normalize_inbound(payload)
    if is_debug():
        logger.info("WHATSAPP_INBOUND from=%s to=%s", event["from"], event["to"])
    # NOTE: tenant routing and resolution belongs to the engine layer.
    result = _engine_stub(event)
    return {"ok": True, "result": result}


@contextmanager
def _env_override(name: str, value: str | None) -> Iterator[None]:
    old = os.getenv(name)
    try:
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
        yield
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


def _has_whatsapp_inbound_route() -> bool:
    from core.app import create_app

    app = create_app()
    return any(
        getattr(route, "path", None) == "/whatsapp/inbound"
        and "POST" in getattr(route, "methods", set())
        for route in app.routes
    )


def selftests() -> dict[str, Any]:
    norm = normalize_inbound(
        {
            "from": "+15550001111",
            "to": "+15559990000",
            "text": "hello",
            "media_urls": ["https://cdn.example/img.jpg"],
            "ts": "1730000000",
        }
    )
    if norm["channel"] != "whatsapp" or norm["text"] != "hello":
        return {"ok": False, "message": "normalization failed for standard payload"}

    missing = normalize_inbound({})
    if missing["channel"] != "whatsapp" or not isinstance(missing["media_urls"], list):
        return {"ok": False, "message": "normalization failed for missing fields payload"}

    with _env_override("VOZ_FEATURE_WHATSAPP_IN", "0"):
        off_mounted = _has_whatsapp_inbound_route()
    with _env_override("VOZ_FEATURE_WHATSAPP_IN", "1"):
        on_mounted = _has_whatsapp_inbound_route()

    if off_mounted or not on_mounted:
        return {"ok": False, "message": "route mounting failed for OFF/ON states"}
    return {"ok": True, "message": "whatsapp_in selftests ok"}


def security_checks() -> dict[str, Any]:
    return {
        "ok": True,
        "message": (
            "TODO: validate provider signature (Twilio or Meta). "
            "No tenant derivation in handler; routing is engine responsibility."
        ),
    }


def load_profile() -> dict[str, Any]:
    return {"hint": "light-inbound-adapter", "p50_ms": 2, "p95_ms": 10}


FEATURE = {
    "key": "whatsapp_in",
    "router": router,
    "enabled_env": "VOZ_FEATURE_WHATSAPP_IN",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
