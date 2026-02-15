"""VOZLIA FILE PURPOSE
Purpose: minimal sample feature for Day 0 regression coverage.
Hot path: no.
Feature flags: VOZ_FEATURE_SAMPLE.
Failure mode: disabled by default.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

router = APIRouter()


@router.get("/sample/ping")
async def ping() -> dict[str, bool]:
    return {"ok": True}


@dataclass
class SelfTestResult:
    ok: bool
    message: str = ""


def selftests() -> SelfTestResult:
    # deterministic; no network / DB
    return SelfTestResult(ok=True, message="sample selftest ok")


def security_checks() -> SelfTestResult:
    # MVP: ensure no tenant data is accessed without scoping (none here)
    return SelfTestResult(ok=True, message="sample security ok")


def load_profile() -> dict:
    return {"hint": "negligible", "p50_ms": 1, "p95_ms": 5}


FEATURE = {
    "key": "sample",
    "router": router,
    "enabled_env": "VOZ_FEATURE_SAMPLE",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
}
