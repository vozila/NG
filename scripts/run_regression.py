"""Run NG regression (no HTTP).

Writes: ops/QUALITY_REPORTS/latest_regression.json
Exit: 0 if all ok, 2 otherwise.
"""

from core.app import create_app
from core.quality import run_regression


def main() -> int:
    _app = create_app()
    _ = _app  # keep lint happy
    report = run_regression()
    print(report)
    return 0 if report.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
