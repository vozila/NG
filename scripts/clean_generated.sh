#!/usr/bin/env bash
set -euo pipefail

# Clean local generated artifacts so feature branches only commit ticket-allowed files.
# Usage:
#   bash scripts/clean_generated.sh

if [ -f "ops/QUALITY_REPORTS/latest_regression.json" ]; then
  git checkout -- ops/QUALITY_REPORTS/latest_regression.json || true
fi

rm -rf __pycache__ .pytest_cache .ruff_cache .mypy_cache || true
find core features scripts tests -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
