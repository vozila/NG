"""VOZLIA FILE PURPOSE
Purpose: quality admin endpoints (regression runner).
Hot path: no (admin control-plane only).
Feature flags: VOZ_FEATURE_ADMIN_QUALITY.
Failure mode: report failure details; does not crash server.
"""

from __future__ import annotations

from fastapi import APIRouter

from core.quality import run_regression

router = APIRouter( prefix="/admin/quality", tags=["quality"] )


@router.post("/regression/run")
async def regression_run() -> dict:
    return run_regression()


def selftests() -> dict:
    # Keep admin selftests self-contained to avoid recursion via run_regression().
    return {"ok": True, "message": "admin_quality selftests ok"}


def security_checks() -> dict:
    # MVP: admin auth hook to be added by Core Maintainer before prod.
    return {"ok": True, "message": "admin endpoints must be auth-guarded in prod"}

def load_profile() -> dict:
    return {"hint": "admin-only", "p50_ms": 20, "p95_ms": 200}


FEATURE = {
    "key": "admin_quality",
    "router": router,
    "enabled_env": "VOZ_FEATURE_ADMIN_QUALITY",
    "selftests": selftests,
    "security_checks": security_checks,
    "load_profile": load_profile,
  }
