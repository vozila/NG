#!/usr/bin/env bash
set -u -o pipefail

OUT_DIR="ops/QUALITY_REPORTS"
TS="$(date +%Y%m%d_%H%M%S)"
LOG_PATH="${OUT_DIR}/gates_${TS}.log"
SUMMARY_PATH="${OUT_DIR}/gates_${TS}.summary.json"
REGRESSION_PATH="${OUT_DIR}/regression_${TS}.json"
LATEST_REGRESSION_PATH="${OUT_DIR}/latest_regression.json"

mkdir -p "${OUT_DIR}"
touch "${LOG_PATH}"

trap 'rc=$?; if [ "${rc}" -ne 0 ]; then echo "run_gates_record failed with exit code ${rc}" | tee -a "${LOG_PATH}"; fi' EXIT

STEP_NAMES=()
STEP_CODES=()

run_step() {
  local name="$1"
  shift
  echo "== ${name}" | tee -a "${LOG_PATH}"
  "$@" >>"${LOG_PATH}" 2>&1
  local rc=$?
  STEP_NAMES+=("${name}")
  STEP_CODES+=("${rc}")
  if [ "${rc}" -eq 0 ]; then
    echo "${name}: ok" | tee -a "${LOG_PATH}"
  else
    echo "${name}: fail (${rc})" | tee -a "${LOG_PATH}"
  fi
}

run_step "compileall" python -m compileall .
run_step "ruff" python -m ruff check .
run_step "pytest" pytest -q
run_step "feature_registry_check" python scripts/feature_registry_check.py
run_step "run_regression" env VOZ_FEATURE_SAMPLE=1 VOZ_FEATURE_ADMIN_QUALITY=1 python scripts/run_regression.py

if [ -f "${LATEST_REGRESSION_PATH}" ]; then
  cp "${LATEST_REGRESSION_PATH}" "${REGRESSION_PATH}"
  REGRESSION_AVAILABLE=true
else
  REGRESSION_AVAILABLE=false
fi

STEP_NAMES_JOINED="$(printf "%s\n" "${STEP_NAMES[@]}")"
STEP_CODES_JOINED="$(printf "%s\n" "${STEP_CODES[@]}")"

export TS SUMMARY_PATH LOG_PATH REGRESSION_PATH REGRESSION_AVAILABLE STEP_NAMES_JOINED STEP_CODES_JOINED
python - <<'PY'
from __future__ import annotations

import json
import os

names = [x for x in os.environ.get("STEP_NAMES_JOINED", "").splitlines() if x]
codes = [int(x) for x in os.environ.get("STEP_CODES_JOINED", "").splitlines() if x]
steps = [{"name": n, "exit_code": c, "ok": c == 0} for n, c in zip(names, codes)]
overall_ok = all(step["ok"] for step in steps)

summary = {
    "ts": os.environ["TS"],
    "status": "ok" if overall_ok else "fail",
    "log_path": os.environ["LOG_PATH"],
    "summary_path": os.environ["SUMMARY_PATH"],
    "regression_artifact": {
        "available": os.environ.get("REGRESSION_AVAILABLE", "false") == "true",
        "path": os.environ["REGRESSION_PATH"],
    },
    "steps": steps,
}

with open(os.environ["SUMMARY_PATH"], "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2)
PY

cat "${SUMMARY_PATH}" | tee -a "${LOG_PATH}"

if [ "${REGRESSION_AVAILABLE}" = true ]; then
  echo "regression artifact: ${REGRESSION_PATH}" | tee -a "${LOG_PATH}"
else
  echo "regression artifact: not available" | tee -a "${LOG_PATH}"
fi

OVERALL_RC=0
for rc in "${STEP_CODES[@]}"; do
  if [ "${rc}" -ne 0 ]; then
    OVERALL_RC=1
    break
  fi
done

exit "${OVERALL_RC}"
