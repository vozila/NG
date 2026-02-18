#!/usr/bin/env bash
set -euo pipefail

# autopush.sh
#
# Usage:
#   ./scripts/autopush.sh <branch> [ENVVAR=VALUE ...]
#
# Examples:
#   ./scripts/autopush.sh task-0201
#   ./scripts/autopush.sh task-0201 VOZ_FEATURE_ADMIN_QUALITY=1 VOZ_FEATURE_SHARED_LINE_ACCESS=1
#
# Behavior:
#   - Refuses to run if working tree is dirty (so pushes are deterministic)
#   - Runs scripts/clean_generated.sh if present
#   - Runs scripts/run_gates_record.sh if present; otherwise fallback: compileall + ruff + pytest
#   - Pushes current HEAD to origin/<current-branch> (or selected branch)
#
# Notes:
#   - "python" may not exist on macOS; we auto-detect python3.
#   - You can override python via PYTHON_BIN=/path/to/python.

ts() { date +"%H:%M:%S"; }
log() { echo "[$(ts)] $*"; }
die() { log "ERROR: $*"; exit 2; }

require_cmd() {
  local c="$1"
  command -v "$c" >/dev/null 2>&1 || die "Missing required command: ${c}"
}

pick_python() {
  # User override wins
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    if [[ -x "${PYTHON_BIN}" ]]; then
      echo "${PYTHON_BIN}"
      return 0
    fi
    die "PYTHON_BIN is set but not executable: ${PYTHON_BIN}"
  fi

  # Prefer venv python if active
  if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
    echo "${VIRTUAL_ENV}/bin/python"
    return 0
  fi

  # Fall back to python or python3
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return 0
  fi

  die "Missing required command: python (or python3). Install Python or set PYTHON_BIN."
}

# --- args ---
if [[ $# -lt 1 ]]; then
  die "Usage: $0 <branch> [ENVVAR=VALUE ...]"
fi

TARGET_BRANCH="$1"
shift || true

# Remaining args are optional ENV assignments, e.g. VOZ_FEATURE_X=1
EXTRA_ENV=("$@")

# --- preflight ---
require_cmd git

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || die "Not inside a git repo"
cd "${REPO_ROOT}"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
if [[ -z "${CURRENT_BRANCH}" || "${CURRENT_BRANCH}" == "HEAD" ]]; then
  die "Detached HEAD; checkout a branch first."
fi

# Ensure upstream remote exists
REMOTE="origin"
if ! git remote | grep -qx "${REMOTE}"; then
  REMOTE="$(git remote | head -n 1)"
  [[ -n "${REMOTE}" ]] || die "No git remotes configured."
fi

# Refuse dirty tree
if [[ -n "$(git status --porcelain)" ]]; then
  git status --porcelain >&2
  die "Working tree is dirty. Commit/stash first."
fi

# Ensure we're on the requested branch (or create it)
if [[ "${CURRENT_BRANCH}" != "${TARGET_BRANCH}" ]]; then
  if git show-ref --verify --quiet "refs/heads/${TARGET_BRANCH}"; then
    log "CHECKOUT        ${TARGET_BRANCH}"
    git checkout "${TARGET_BRANCH}"
  else
    log "CREATE_BRANCH   ${TARGET_BRANCH}"
    git checkout -b "${TARGET_BRANCH}"
  fi
fi

# Final dirty check after checkout
if [[ -n "$(git status --porcelain)" ]]; then
  git status --porcelain >&2
  die "Working tree became dirty after checkout. Resolve first."
fi

PY="$(pick_python)"

# --- run optional clean_generated ---
if [[ -f "scripts/clean_generated.sh" ]]; then
  log "CLEAN: scripts/clean_generated.sh"
  bash scripts/clean_generated.sh
fi

# --- run gates with optional env vars ---
if [[ -f "scripts/run_gates_record.sh" ]]; then
  log "GATES: scripts/run_gates_record.sh"
  # shellcheck disable=SC2086
  env "${EXTRA_ENV[@]:-}" bash scripts/run_gates_record.sh
else
  log "GATES: fallback (compileall + ruff + pytest)"
  # compileall
  env "${EXTRA_ENV[@]:-}" "${PY}" -m compileall .
  # ruff (optional but preferred)
  if command -v ruff >/dev/null 2>&1; then
    env "${EXTRA_ENV[@]:-}" ruff check .
  else
    log "WARN: ruff not found; skipping ruff check"
  fi
  # pytest
  env "${EXTRA_ENV[@]:-}" "${PY}" -m pytest -q
fi

# --- push ---
log "FETCH           ${REMOTE}"
git fetch "${REMOTE}" --prune

log "PUSH            ${REMOTE} ${TARGET_BRANCH}"
git push "${REMOTE}" "${TARGET_BRANCH}"

log "DONE"

