from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import features.admin_quality as admin_quality


ROOT = Path(__file__).resolve().parent.parent


def test_run_regression_script_invocation_has_stable_import_path() -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["VOZ_FEATURE_SAMPLE"] = "1"
    env["VOZ_FEATURE_ADMIN_QUALITY"] = "1"
    proc = subprocess.run(
        [sys.executable, "scripts/run_regression.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode in (0, 2)
    assert "status" in proc.stdout


def test_admin_quality_selftests_do_not_recurse_and_are_fast(monkeypatch) -> None:
    called = {"run_regression": False}

    def _run_regression() -> dict:
        called["run_regression"] = True
        return {"status": "ok"}

    monkeypatch.setattr(admin_quality, "run_regression", _run_regression)

    t0 = time.perf_counter()
    out = admin_quality.selftests()
    dt = time.perf_counter() - t0

    assert called["run_regression"] is False
    assert out.get("ok") is True
    assert dt < 0.5
