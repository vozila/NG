#!/usr/bin/env bash
set -euo pipefail

# Merge a branch into main with gates + logging, reverting rolling regression report afterward.
# Usage:
#   bash scripts/merge_with_gates.sh <branch> "<merge message>"

BRANCH="${1:-}"
MSG>"${2:-}"
if [ -z "$BRANCH" ] || [ -z "$MSG" ]; then
  echo "Usage: bash scripts/merge_with_gates.sh <branch> \"<merge message>\""
  exit 2
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "ERROR: working tree not clean. Run: bash scripts/clean_generated.sh"
  git status --short
  exit 3
fi

git checkout main
git pull
git merge --no-ff "$BRANCH" -m "$MSG"

bash scripts/run_gates_record.sh
bash scripts/clean_generated.sh

'it push
