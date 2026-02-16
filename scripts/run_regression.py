"""Run NG regression (no HTTP).

Writes: ops/QUALITY_REPORTS/latest_regression.json
Exit: 0 if all ok, 2 otherwise.

Supported invocation from repo root:
  python scripts/run_regression.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.app import create_app  # noqa: E402
from core.quality import run_regression  # noqa: E402


def main() -> int:
    _app = create_app()
    _ = _app  # keep lint happy
    report = run_regression()
    print(report)
    return 0 if report.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
