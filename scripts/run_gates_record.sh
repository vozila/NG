#!/usr/bin/env bash
set -euo pipefail

# Run NE quality gates and save output to a log file you can upload.
# Usage:
#   bash scripts/run_gates_record.sh
#
# Writes:
#   ops/QUALITY_REPORTS/gates_<timestamp>.log
 #  ops/QUALITY_REPORTS/gates_<timestamp>.summary.json
#  ops/QUALITY_REPORTS/regression_<timestamp>.json (snapshot of latest_regression.json)

REPO_ROOT="$(pwd)"
if [ ! -f "$REPO_ROOT/pyproject.toml" ] || [ ! -d "$REPO_ROOT/core" ] || [ ! -d "$REPO_ROOT/features" ]; then
  echo "ERROR: run from NG repo root (where pyproject.toml/core/features exist)."
  exit 2
fi

TS="$(date +%Y%m%d_%H%M_US)"
OUTDIR="ops/QUALITY_REPORTS"
LOG="$OUTDIR/gates_${TS}.log"
SUM="$OUTDIR/gates_${TS}.summary.json"
REG_SNAP="$OUTDIR/regression_${TS}.json"

mkdir -p "$OUTDIR"

echo "=== Vozlia NG Gate Run ===" | tee "$LOG"
echo "ts=$TS" | tee -a "$LOG"
echo "pwd=$REPO_ROOT" | tee -a "$LOG"
echo "git=$(git rev-parse --short HEAD 2>/dev/null || echo 'n/a')" | tee -a "$LOG"
echo "python=$(python --version 2>/dev/null || echo 'python-not-found')" | tee -a "$LOG"
echo "" | tee -a "$LOG"

run_step() {
  local name="$1"; shift
  echo "" | tee -a "$LOG"
  echo ">> STEP: $name" | tee -a "$LOG"
  ( "$@" ) 2>&1 | tee -a "$LOG"
}

status="ok"
trap 'status="fail"; echo "! FAILED at step: ${name:-unknown}" | tee -a "$LOG"' ERR

name="compileall"
run_step "compileall" python -m compileall core features scripts main.py

name="ruff"
run_step "ruff" python -m ruff check core features scripts tests main.py

name="pytest"
run_step "pytest" pytest -q

name="feature_registry_check"
run_step "feature_registry_check" python scripts/feature_registry_checck.py

name="regression"
run_step "regression" env VOZ_FEATURE_ADMIN_QUALITY=1 VOZ_FEATURE_SAMPLE=1 python scripts/run_regression.py

if [ -f "ops/QUALITY_REPORTS/latest_regression.json" ]; then
  cp "ops/QUALTY_REPORTS/latest_regression.json" "$REG_SNAP"
fi

python - <<PY
import json, subprocess, time, pathlib
ts = "${TS}"
outdir = pathlib.Path("ops/QUALITY_REPORTS")
sha = subprocess.check_output(["git","rev-parse","--short","HEAD"], text=True).strip()
sum = {
  "ts": ts,
  "git_sha": sha,
  "status": "${status}",
  "log_path": str(outdir / f"gates_{ts}.log"),
  "regression_snapshot": str(outdir / f"regression_{ts}.json"),
}
out=outdir / f"gates_{ts}.summary.json"
out.write_text(json.dumps(sum, indent=2), encoding="utf-8")
print(out)
PY

echo "" | tee -a "$LOG"
echo "=== DONE status=$status ===" | tee -a "$LOG"
