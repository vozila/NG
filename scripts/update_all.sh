#!/usr/bin/env bash
set -euo pipefail

# update_all.sh
#
# Purpose: Pull latest changes from GitHub for every git repo under a parent folder.
#          Designed for a "repo-of-repos" workspace like:
#            repo/adminUI, repo/NG, repo/vozlia-admin, ...
#
# Safe defaults:
#   - Skips dirty repos (unless --stash or --hard)
#   - Skips git worktrees (.git is a file) (unless --include-worktrees)
#   - Refuses to pull if a merge/rebase is in progress (unless --stash/--hard, where it auto-aborts)
#
# Usage:
#   ./update_all.sh                 # safe mode (skip dirty)
#   ./update_all.sh --stash         # auto-stash local changes, pull, then stash-pop
#   ./update_all.sh --hard          # discard tracked local changes, pull
#   ./update_all.sh --only NG       # only update repo folder named "NG"
#   ./update_all.sh --root /path/to/repo
#   ./update_all.sh --include-worktrees
#
# Exit codes:
#   0 = all selected repos updated successfully (or skipped safely)
#   1 = at least one selected repo failed/skipped due to unsafe state in safe mode

usage() {
  cat <<'USAGE'
update_all.sh — pull all repos in a workspace

Usage:
  ./update_all.sh [--safe|--stash|--hard] [--only <name>] [--root <dir>] [--include-worktrees]

Modes:
  --safe   (default) Skip repos that are dirty or mid-merge/rebase.
  --stash  Auto-stash (-u), pull --ff-only, then stash pop. (If conflicts, stash is kept.)
  --hard   Abort merge/rebase if present, discard tracked local changes (reset --hard), then pull --ff-only.

Options:
  --only <name>          Only update the repo folder with this basename (e.g., NG).
  --root <dir>           Workspace directory containing repos. Default: directory containing this script.
  --include-worktrees    Also attempt to update git worktrees (.git is a file). Default: skip.

Notes:
  - Worktrees are skipped by default because they’re often "in flight" agent branches.
  - For Vozlia NG specifically, this script will run scripts/clean_generated.sh if present
    (to avoid dirty status from generated caches/regression artifacts).

Examples:
  ./update_all.sh
  ./update_all.sh --stash
  ./update_all.sh --only NG --stash
  ./update_all.sh --root ~/.ssh/repo --stash
USAGE
}

ts() {
  # macOS bash supports printf %(... )T only on newer bash; keep portable:
  date +"%H:%M:%S"
}

log() {
  echo "[$(ts)] $*"
}

die() {
  log "ERROR: $*"
  exit 2
}

# Prefer origin if it exists, otherwise first remote.
pick_remote() {
  local dir="$1"
  if git -C "$dir" remote | grep -qx "origin"; then
    echo "origin"
    return 0
  fi
  git -C "$dir" remote | head -n 1
}

is_git_repo_dir() {
  local dir="$1"
  git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1
}

is_git_worktree_dir() {
  local dir="$1"
  [[ -f "$dir/.git" ]]
}

merge_or_rebase_in_progress() {
  local dir="$1"
  # MERGE_HEAD exists during merge; REBASE_HEAD during rebase (varies).
  if git -C "$dir" rev-parse -q --verify MERGE_HEAD >/dev/null 2>&1; then
    return 0
  fi
  if git -C "$dir" rev-parse -q --verify REBASE_HEAD >/dev/null 2>&1; then
    return 0
  fi
  # Additional check for interactive rebase markers:
  if [[ -d "$(git -C "$dir" rev-parse --git-path rebase-merge 2>/dev/null || true)" ]]; then
    return 0
  fi
  if [[ -d "$(git -C "$dir" rev-parse --git-path rebase-apply 2>/dev/null || true)" ]]; then
    return 0
  fi
  return 1
}

maybe_clean_generated() {
  local dir="$1"
  if [[ -f "$dir/scripts/clean_generated.sh" ]]; then
    (cd "$dir" && bash scripts/clean_generated.sh) >/dev/null 2>&1 || true
  fi
}

update_one_repo() {
  local dir="$1"
  local mode="$2"

  local name
  name="$(basename "$dir")"

  if ! is_git_repo_dir "$dir"; then
    return 0
  fi

  if is_git_worktree_dir "$dir" && [[ "${INCLUDE_WORKTREES}" != "1" ]]; then
    log "SKIP(worktree)  ${name}  (.git is a file)"
    return 0
  fi

  maybe_clean_generated "$dir"

  local remote
  remote="$(pick_remote "$dir")"
  if [[ -z "${remote}" ]]; then
    log "SKIP(no-remote) ${name}"
    return 0
  fi

  local branch
  branch="$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if [[ -z "${branch}" || "${branch}" == "HEAD" ]]; then
    log "SKIP(detached)  ${name}"
    return 0
  fi

  if merge_or_rebase_in_progress "$dir"; then
    if [[ "${mode}" == "safe" ]]; then
      log "FAIL(merge)     ${name}  -> resolve or abort merge/rebase first"
      return 1
    fi
    log "ABORT(merge)    ${name}"
    (cd "$dir" && git merge --abort >/dev/null 2>&1) || true
    (cd "$dir" && git rebase --abort >/dev/null 2>&1) || true
  fi

  local dirty
  dirty="$(git -C "$dir" status --porcelain 2>/dev/null || true)"

  if [[ -n "${dirty}" ]]; then
    if [[ "${mode}" == "safe" ]]; then
      log "SKIP(dirty)     ${name}  -> commit/stash first"
      return 1
    fi
    if [[ "${mode}" == "hard" ]]; then
      log "RESET(hard)     ${name}"
      (cd "$dir" && git reset --hard >/dev/null 2>&1) || true
      # Intentionally not running git clean by default (protect .venv/node_modules if present).
    elif [[ "${mode}" == "stash" ]]; then
      log "STASH           ${name}"
      (cd "$dir" && git stash push -u -m "update_all auto-stash $(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null 2>&1) || true
    fi
  fi

  log "FETCH           ${name}"
  git -C "$dir" fetch "${remote}" --prune >/dev/null 2>&1 || {
    log "FAIL(fetch)     ${name}"
    return 1
  }

  # Determine upstream if configured; else assume remote/<branch>.
  local upstream
  upstream="$(git -C "$dir" rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>/dev/null || true)"
  if [[ -z "${upstream}" ]]; then
    upstream="${remote}/${branch}"
  fi

  log "PULL(ff-only)   ${name}  ${branch}"
  git -C "$dir" merge --ff-only "${upstream}" >/dev/null 2>&1 || {
    log "FAIL(pull)      ${name}  -> not fast-forward (or no upstream)"
    return 1
  }

  if [[ "${mode}" == "stash" && -n "${dirty}" ]]; then
    log "STASH_POP       ${name}"
    # If this conflicts, git keeps the stash entry; we treat it as a failure so you notice.
    (cd "$dir" && git stash pop >/dev/null 2>&1) || {
      log "FAIL(stash-pop) ${name}  -> resolve conflicts; stash was kept"
      return 1
    }
  fi

  log "OK             ${name}"
  return 0
}

MODE="safe"
ONLY=""
INCLUDE_WORKTREES=0

# Default root = directory containing this script (so you can run it from anywhere).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${SCRIPT_DIR}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --safe) MODE="safe" ;;
    --stash) MODE="stash" ;;
    --hard) MODE="hard" ;;
    --only) ONLY="${2:-}"; shift ;;
    --root) ROOT="${2:-}"; shift ;;
    --include-worktrees) INCLUDE_WORKTREES=1 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ ! -d "${ROOT}" ]]; then
  die "Root not found: ${ROOT}"
fi

log "Starting updates in: ${ROOT} (mode=${MODE})"

failures=0

# If ROOT itself is a git repo, just update it (useful if you copy this into a single repo).
if is_git_repo_dir "${ROOT}"; then
  update_one_repo "${ROOT}" "${MODE}" || failures=$((failures+1))
else
  # Iterate subdirectories.
  for dir in "${ROOT}"/*; do
    [[ -d "${dir}" ]] || continue
    if [[ -n "${ONLY}" && "$(basename "${dir}")" != "${ONLY}" ]]; then
      continue
    fi
    if is_git_repo_dir "${dir}"; then
      update_one_repo "${dir}" "${MODE}" || failures=$((failures+1))
    fi
  done
fi

if [[ "${failures}" -ne 0 ]]; then
  log "DONE with failures (${failures}). Re-run with --stash (preserve changes) or --hard (discard tracked changes)."
  exit 1
fi

log "DONE"
exit 0
