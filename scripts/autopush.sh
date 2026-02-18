#!/usr/bin/env bash
set -euo pipefail

# scripts/autopush.sh
#
# Purpose:
#   "One command" to clean generated files, optionally run gates, auto-commit any changes,
#   and push the current branch to GitHub.
#
# Default behavior:
#   - Runs scripts/clean_generated.sh (if present)
#   - Runs scripts/quality_gate.sh (if present) unless --no-gates
#   - If any changes exist (tracked or untracked), it stages and commits them
#   - Pushes current branch to origin (sets upstream if missing)
#   - If push is rejected (non-fast-forward), it attempts a pull --rebase then pushes again
#
# Usage examples:
#   bash scripts/autopush.sh task-0200
#   bash scripts/autopush.sh --task task-0200 -m "TASK-0200: tenant routing tweaks"
#   bash scripts/autopush.sh --no-gates task-0200
#   bash scripts/autopush.sh task-0200 VOZ_FEATURE_ADMIN_QUALITY=1 VOZ_FEATURE_SHARED_LINE_ACCESS=1
#
# Notes:
#   - You can pass ENV=VALUE pairs at the end; they will be exported for gates/regression runs.
#   - If a merge/rebase is in progress, we refuse to proceed (can’t safely “just work” through conflicts).

log() { echo "[$(date +%H:%M:%S)] $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

need_cmd git

# --- locate repo root ---
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || die "Not inside a git repository."
cd "$ROOT"

REMOTE="origin"
RUN_GATES=1
TASK_ID=""
COMMIT_MSG=""

# --- parse args ---
# We accept:
#   --task <id>
#   -m/--message <msg>
#   --remote <remote>
#   --no-gates
#   positional first token as task id (if it doesn't start with -)
#   trailing KEY=VALUE env pairs
ENV_KVS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task)
      [[ $# -ge 2 ]] || die "--task requires a value"
      TASK_ID="$2"; shift 2 ;;
    -m|--message)
      [[ $# -ge 2 ]] || die "-m/--message requires a value"
      COMMIT_MSG="$2"; shift 2 ;;
    --remote)
      [[ $# -ge 2 ]] || die "--remote requires a value"
      REMOTE="$2"; shift 2 ;;
    --no-gates)
      RUN_GATES=0; shift ;;
    --)
      shift
      break ;;
    *)
      # first positional non-flag becomes task id (optional)
      if [[ -z "$TASK_ID" && "$1" != -* && "$1" != *=* ]]; then
        TASK_ID="$1"; shift
      else
        break
      fi
      ;;
  esac
done

# collect any remaining env assignments
while [[ $# -gt 0 ]]; do
  if [[ "$1" == *=* ]]; then
    ENV_KVS+=("$1")
    shift
  else
    die "Unknown argument: $1"
  fi
done

# export env vars (for gates/regression)
for kv in "${ENV_KVS[@]}"; do
  export "$kv"
done

# --- sanity checks: merge/rebase in progress ---
MERGE_HEAD="$(git rev-parse --git-path MERGE_HEAD)"
REBASE_APPLY="$(git rev-parse --git-path rebase-apply)"
REBASE_MERGE="$(git rev-parse --git-path rebase-merge)"

if [[ -f "$MERGE_HEAD" ]]; then
  die "Merge in progress (MERGE_HEAD exists). Resolve/commit OR run: git merge --abort"
fi
if [[ -d "$REBASE_APPLY" || -d "$REBASE_MERGE" ]]; then
  die "Rebase in progress. Resolve/continue OR run: git rebase --abort"
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" == "HEAD" ]]; then
  die "Detached HEAD. Checkout a branch before autopush."
fi

# --- optional cleanup of generated artifacts ---
if [[ -x "scripts/clean_generated.sh" ]]; then
  log "CLEAN: scripts/clean_generated.sh"
  # don't fail the entire run for cleanup issues
  bash scripts/clean_generated.sh || true
fi

# --- optional gates ---
if [[ "$RUN_GATES" -eq 1 ]]; then
  if [[ -x "scripts/quality_gate.sh" ]]; then
    log "GATES: scripts/quality_gate.sh"
    bash scripts/quality_gate.sh
  else
    log "GATES: fallback (compileall + ruff + pytest)"
    need_cmd python
    python -m compileall .
    python -m ruff check .
    if command -v pytest >/dev/null 2>&1; then
      pytest -q
    fi
  fi

  # If VOZ_FEATURE_* vars were passed, run regression (best-effort).
  # You can also export VOZ_RUN_REGRESSION=1 explicitly.
  SHOULD_REGRESS=0
  if [[ "${VOZ_RUN_REGRESSION:-0}" == "1" ]]; then
    SHOULD_REGRESS=1
  fi
  for kv in "${ENV_KVS[@]}"; do
    if [[ "$kv" == VOZ_FEATURE_* ]]; then
      SHOULD_REGRESS=1
      break
    fi
  done
  if [[ "$SHOULD_REGRESS" -eq 1 && -f "scripts/run_regression.py" ]]; then
    log "REGRESSION: python scripts/run_regression.py"
    python scripts/run_regression.py
  fi
else
  log "GATES: skipped (--no-gates)"
fi

# --- stage & commit if needed ---
if [[ -n "$(git status --porcelain)" ]]; then
  log "GIT: staging all changes (git add -A)"
  git add -A

  if git diff --cached --quiet; then
    log "GIT: nothing staged after add -A (unexpected); skipping commit"
  else
    if [[ -z "$COMMIT_MSG" ]]; then
      if [[ -n "$TASK_ID" ]]; then
        COMMIT_MSG="${TASK_ID}: autopush $(date +%Y-%m-%d)"
      else
        COMMIT_MSG="chore: autopush $(date +%Y-%m-%d)"
      fi
    fi
    log "GIT: commit -> $COMMIT_MSG"
    git commit -m "$COMMIT_MSG"
  fi
else
  log "GIT: working tree clean (no commit needed)"
fi

# --- push (set upstream if missing) ---
if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
  die "Remote '$REMOTE' not configured. Add it first (git remote -v)."
fi

UPSTREAM_OK=1
git rev-parse --abbrev-ref --symbolic-full-name "@{u}" >/dev/null 2>&1 || UPSTREAM_OK=0

push_once() {
  if [[ "$UPSTREAM_OK" -eq 0 ]]; then
    log "PUSH: git push -u $REMOTE $BRANCH"
    git push -u "$REMOTE" "$BRANCH"
    UPSTREAM_OK=1
  else
    log "PUSH: git push $REMOTE $BRANCH"
    git push "$REMOTE" "$BRANCH"
  fi
}

if ! push_once; then
  log "PUSH: rejected; attempting fetch + pull --rebase, then push again"
  git fetch "$REMOTE"
  # rebase current branch onto its upstream (or remote branch)
  if ! git pull --rebase "$REMOTE" "$BRANCH"; then
    die "Rebase failed. Resolve conflicts, then rerun scripts/autopush.sh"
  fi
  push_once
fi

log "DONE: branch=$BRANCH remote=$REMOTE"

