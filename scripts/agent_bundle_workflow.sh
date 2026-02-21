#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/agent_bundle_workflow.sh execute <bundle_id>
  bash scripts/agent_bundle_workflow.sh files <bundle_id>

Example:
  bash scripts/agent_bundle_workflow.sh execute B001
  bash scripts/agent_bundle_workflow.sh execute B004
  bash scripts/agent_bundle_workflow.sh execute B008
USAGE
}

die() {
  echo "ERROR: $*" >&2
  exit 2
}

bundle_norm() {
  echo "${1}" | tr '[:lower:]' '[:upper:]' | tr -cd 'A-Z0-9_-'
}

files_for_bundle() {
  local bundle="$1"
  case "${bundle}" in
    B001)
      echo ".agents/tasks/BUNDLE-B001-AGENT-A.md"
      echo ".agents/tasks/BUNDLE-B001-AGENT-B.md"
      echo ".agents/tasks/BUNDLE-B001-AGENT-C.md"
      ;;
    B002)
      echo ".agents/tasks/BUNDLE-B002-AGENT-A.md"
      echo ".agents/tasks/BUNDLE-B002-AGENT-B.md"
      echo ".agents/tasks/BUNDLE-B002-AGENT-C.md"
      ;;
    B003)
      echo ".agents/tasks/BUNDLE-B003-AGENT-A.md"
      echo ".agents/tasks/BUNDLE-B003-AGENT-B.md"
      echo ".agents/tasks/BUNDLE-B003-AGENT-C.md"
      ;;
    B004)
      echo ".agents/tasks/BUNDLE-B004-AGENT-A.md"
      echo ".agents/tasks/BUNDLE-B004-AGENT-B.md"
      echo ".agents/tasks/BUNDLE-B004-AGENT-C.md"
      ;;
    B005)
      echo ".agents/tasks/BUNDLE-B005-AGENT-A.md"
      echo ".agents/tasks/BUNDLE-B005-AGENT-B.md"
      echo ".agents/tasks/BUNDLE-B005-AGENT-C.md"
      ;;
    B006)
      echo ".agents/tasks/BUNDLE-B006-AGENT-A.md"
      echo ".agents/tasks/BUNDLE-B006-AGENT-B.md"
      echo ".agents/tasks/BUNDLE-B006-AGENT-C.md"
      ;;
    B007)
      echo ".agents/tasks/BUNDLE-B007-AGENT-A.md"
      echo ".agents/tasks/BUNDLE-B007-AGENT-B.md"
      echo ".agents/tasks/BUNDLE-B007-AGENT-C.md"
      ;;
    B008)
      echo ".agents/tasks/BUNDLE-B008-AGENT-A.md"
      echo ".agents/tasks/BUNDLE-B008-AGENT-B.md"
      echo ".agents/tasks/BUNDLE-B008-AGENT-C.md"
      ;;
    *)
      die "Unknown bundle '${bundle}'."
      ;;
  esac
}

cmd="${1:-}"
bundle_raw="${2:-}"

if [[ -z "${cmd}" || "${cmd}" == "-h" || "${cmd}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ -z "${bundle_raw}" ]]; then
  die "Missing <bundle_id>."
fi
bundle="$(bundle_norm "${bundle_raw}")"

case "${cmd}" in
  files)
    files_for_bundle "${bundle}"
    ;;
  execute)
    echo "Execute bundle ${bundle}:"
    echo ""
    file_a=""
    file_b=""
    file_c=""
    i=0
    while IFS= read -r f; do
      if [[ ! -f "${f}" ]]; then
        die "Missing instruction file: ${f}"
      fi
      i=$((i + 1))
      case "${i}" in
        1) file_a="${f}" ;;
        2) file_b="${f}" ;;
        3) file_c="${f}" ;;
      esac
    done < <(files_for_bundle "${bundle}")
    echo "Agent A -> ${file_a}"
    echo "Agent B -> ${file_b}"
    echo "Agent C -> ${file_c}"
    echo ""
    echo "Instruction to each agent:"
    echo "  Read your assigned file and execute exactly that scope."
    ;;
  *)
    usage
    exit 2
    ;;
esac
