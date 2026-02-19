from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from core.app import create_app
from core.quality import run_regression
from core.registry import FeatureSpec, set_enabled
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


def test_admin_quality_regression_endpoint_requires_admin_bearer(monkeypatch) -> None:
    monkeypatch.setenv("VOZ_FEATURE_ADMIN_QUALITY", "1")
    monkeypatch.setenv("VOZ_ADMIN_API_KEY", "admin-secret")
    monkeypatch.setenv("VOZ_FEATURE_SAMPLE", "0")

    app = create_app()
    client = TestClient(app)

    unauthorized = client.post("/admin/quality/regression/run")
    assert unauthorized.status_code == 401

    authorized = client.post(
        "/admin/quality/regression/run",
        headers={"Authorization": "Bearer admin-secret"},
    )
    assert authorized.status_code == 200
    assert "status" in authorized.json()


def test_run_regression_records_selftest_exception_in_message() -> None:
    def _boom() -> dict:
        raise RuntimeError("boom")

    spec = FeatureSpec(
        key="boom_feature",
        enabled_env="VOZ_FEATURE_BOOM",
        router=object(),
        selftests=_boom,
        security_checks=lambda: {"ok": True},
        load_profile=lambda: {"ok": True},
    )
    set_enabled({"boom_feature": spec})
    try:
        out = run_regression()
    finally:
        set_enabled({})

    assert out["status"] == "fail"
    result = out["results"][0]
    assert result["feature"] == "boom_feature"
    assert result["ok"] is False
    assert result["message"] == "RuntimeError: boom"
