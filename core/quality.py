"""VOZLIA FILE PURPOSE
Purpose: regression runner used by /admin/quality and CLI.
Hot path: no.
Feature flags: none (endpoint gating happens in feature module).
Failure mode: report per-feature failures; CLI can exit non-zero.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


from core.registry import enabled_features

REPORT_PATH = Path("ops/QUALITY_REPORTS/latest_regression.json")


def run_regression() -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    ok = True

    for key, spec in enabled_features().items():
        t0 = time.perf_counter()
        try:
            out = spec.selftests()
            if isinstance(out, dict):
                passed = bool(out.get("ok", True))
                msg = out.get("message")
            else:
                passed = bool(getattr(out, "ok", True))
                msg = getattr(out, "message", None)
        except Exception as e:
            passed = False
            msg = f"{type(e).__name__}: {e}"

        dt_ms = (time.perf_counter() - t0) * 1000.0
        ok = ok and passed
        results.append({"feature": key, "ok": passed, "ms": round(dt_ms, 2), "message": msg})

    report = {
        "status": "ok" if ok else "fail",
        "ts": int(time.time()),
        "enabled_features": sorted(enabled_features().keys()),
        "results": results,
        "report_path": str(REPORT_PATH),
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
