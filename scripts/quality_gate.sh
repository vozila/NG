#!/usr/bin/env bash
set -euo pipefail

python -m compileall .
python -m ruff check .
pytest -q
python scripts/feature_registry_check.py
VOZ_FEATURE_ADMIN_QUALITY=1 VOZ_FEATURE_SAMPLE=1 python scripts/run_regression.py
