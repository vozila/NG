#!/usr/bin/env bash
set -euo pipefail

# VOZLIA FILE PURPOSE
# Purpose: Deterministic helper for the standard Codex agent workflow (worktree -> gates -> commit/push -> merge).
# Hot path: no.
# Reads/Writes: git worktrees/branches; runs local quality gates (compileall/ruff/pytest/regression).
# Feature flags: none (but passes VOZ_FEATURE_* env vars through to regression).
# Failure mode: exits non-zero on any failure; never performs a merge unless the working tree is clean.
# Last touched: 2026-02-17 (initial version).

usage() {
  cat <<'USAGE'
Usage:
  # 1) From your main NG checkout:
  bash scripts/agent_task_workflow.sh start <task_id>

  # 2) In the created worktree, run Codex manually, then:
  bash scripts/agent_task_workflow.sh gates [ENV=VALUE ...]
  bash scripts/agent_task_workflow.sh commitpush <task_id> "<commit message>"

  # 3) Back in your main NG checkout:
  bash scripts/agent_task_workflow.sh merge <task_id> "<merge message>"

  # Optional cleanup (run from main NG checkout, not inside the worktree):
  bash scripts/agent_task_workflow.sh cleanup <task_id>

Notes:
  - task_id examples: task-0123, TASK-0123, shared-line-routing
  - Branch name: agent/<task_id>
  - Worktree path default: <repo-parent>/NG-agent-<task_id>
  - gates: defaults to VOZ_FEATURE_ADMIN_QUALITY=1 VOZ_FEATURE_SAMPLE=1 if you do not pass any ENV=VALUE args.

Examples:
  bash scripts/agent_task_workflow.sh start task-0123
  cd ../NG-agent-task-0123
  codex
  bash scripts/agent_task_workflow.sh gates VOZ_FEATURE_ADMIN_QUALITY=1 VOZ_FEATURE_SHARED_LINE_ACCESS=1
  bash scripts/agent_task_workflow.sh commitpush task-0123 "TASK-0123: implement shared line access"
  cd ../NG
  bash scripts/agent_task_workflow.sh merge task-0123 "TASK-0123: shared line access"

USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 2
}

repo_root() {
  git rev-parse --show-toplevel 2>/dev/null || true
}

ensure_clean_tree() {
  if [ -n "$(git status --porcelain)" ]; then
    echo "ERROR: working tree not clean. Consider:" >&2
    echo "  bash scripts/clean_generated.sh" >&2
    git status --short >&2
    exit 3
  fi
}

task_id_norm() {
  # Keep it simple: allow slugs, but normalize spaces.
  echo "${1}" | tr ' ' '-' | tr -cd 'A-Za-z0-9._-'
}

main() {
  local cmd="${1:-}"
  if [ -z "${cmd}" ] || [ "${cmd}" = "-h" ] || [ "${cmd}" = "--help" ]; then
    usage
    exit 0
  fi

  local root
  root="$(repo_root)"
  if [ -z "${root}" ]; then
    die "Not inside a git repository."
  fi

  # Always operate from repo root for predictable relative paths.
  cd "${root}"

  local task_raw="${2:-}"
  if [ -z "${task_raw}" ]; then
    die "Missing <task_id>."
  fi
  local task
  task="$(task_id_norm "${task_raw}")"
  local branch="agent/${task}"

  local parent_dir
  parent_dir="$(dirname "${root}")"
  local worktree_path="${VOZ_WORKTREE_PATH:-${parent_dir}/NG-agent-${task}}"

  local remote="${VOZ_REMOTE:-origin}"
  local base_ref="${VOZ_BASE_REF:-${remote}/main}"

  case "${cmd}" in
    start)
      ensure_clean_tree
      git fetch "${remote}"

      if [ -e "${worktree_path}" ]; then
        die "Worktree path already exists: ${worktree_path}"
      fi

      # If branch already exists locally, prefer it; otherwise create off base_ref.
      if git show-ref --verify --quiet "refs/heads/${branch}"; then
        echo "Branch already exists locally: ${branch}"
        git worktree add "${worktree_path}" "${branch}"
      else
        git worktree add "${worktree_path}" -b "${branch}" "${base_ref}"
      fi

      echo ""
      echo "Worktree created:"
      echo "  ${worktree_path}"
      echo ""
      echo "Next:"
      echo "  cd "${worktree_path}""
      echo "  codex"
      echo ""
      echo "Then run gates + push:"
      echo "  bash scripts/agent_task_workflow.sh gates VOZ_FEATURE_ADMIN_QUALITY=1 VOZ_FEATURE_<YOUR_FEATURE>=1"
      echo "  bash scripts/agent_task_workflow.sh commitpush ${task} "TASK-${task}: <summary>""
      ;;

    gates)
      # Run standard gates in the *current* worktree.
      shift 2
      local envs=("$@")
      if [ "${#envs[@]}" -eq 0 ]; then
        envs=("VOZ_FEATURE_ADMIN_QUALITY=1" "VOZ_FEATURE_SAMPLE=1")
      fi

      echo "== compileall"
      python -m compileall .
      echo "== ruff"
      python -m ruff check .
      echo "== pytest"
      pytest -q
      echo "== feature_registry_check"
      python scripts/feature_registry_check.py
      echo "== run_regression (env: ${envs[*]})"
      env "${envs[@]}" python scripts/run_regression.py
      ;;

    commitpush)
      # Intended to run inside the worktree/branch checkout.
      local msg="${3:-}"
      if [ -z "${msg}" ]; then
        die "Missing <commit message>."
      fi

      local cur_branch
      cur_branch="$(git rev-parse --abbrev-ref HEAD)"
      if [ "${cur_branch}" != "${branch}" ]; then
        die "You are on branch '${cur_branch}', expected '${branch}'."
      fi

      # Keep commits clean (no caches, no rolling regression file).
      bash scripts/clean_generated.sh

      if [ -z "$(git status --porcelain)" ]; then
        echo "No changes to commit."
        exit 0
      fi

      git add -A
      git commit -m "${msg}"
      git push -u "${remote}" "${branch}"
      echo ""
      echo "Pushed:"
      echo "  ${branch}"
      echo ""
      echo "Next (in your main NG checkout):"
      echo "  bash scripts/agent_task_workflow.sh merge ${task} "${msg}""
      ;;

    merge)
      # Intended to run in main NG checkout.
      ensure_clean_tree
      local msg="${3:-}"
      if [ -z "${msg}" ]; then
        die "Missing <merge message>."
      fi
      git fetch "${remote}"
      # Prefer local branch if present, else merge remote branch.
      if git show-ref --verify --quiet "refs/heads/${branch}"; then
        bash scripts/merge_with_gates.sh "${branch}" "${msg}"
      else
        bash scripts/merge_with_gates.sh "${remote}/${branch}" "${msg}"
      fi
      
      # By default, remove gate artifacts generated by merge_with_gates (keeps repo clean for next task).
      # Set VOZ_KEEP_GATES_ARTIFACTS=1 to retain the logs/artifacts.
      if [ "${VOZ_KEEP_GATES_ARTIFACTS:-0}" != "1" ]; then
        rm -f ops/QUALITY_REPORTS/gates_*.log ops/QUALITY_REPORTS/gates_*.summary.json ops/QUALITY_REPORTS/regression_*.json 2>/dev/null || true
      fi

echo ""
      echo "Merge complete. If you want to delete the worktree:"
      echo "  bash scripts/agent_task_workflow.sh cleanup ${task}"
      ;;

    cleanup)
      # Remove the worktree folder. Must not be called from inside the worktree itself.
      ensure_clean_tree
      if [ "${root}" = "${worktree_path}" ]; then
        die "Refusing to cleanup from inside the worktree: ${worktree_path}"
      fi
      git worktree remove "${worktree_path}" 2>/dev/null || true
      if [ -d "${worktree_path}" ]; then
        echo "Worktree directory still exists; removing recursively:"
        echo "  rm -rf "${worktree_path}""
        rm -rf "${worktree_path}"
      fi
      echo "Cleanup done: ${worktree_path}"
      ;;

    *)
      usage
      exit 2
      ;;
  esac
}

main "$@"
