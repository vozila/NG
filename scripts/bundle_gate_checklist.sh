#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/bundle_gate_checklist.sh <bundle_id>

Examples:
  bash scripts/bundle_gate_checklist.sh B001
  bash scripts/bundle_gate_checklist.sh B003
USAGE
}

bundle="$(echo "${1:-}" | tr '[:lower:]' '[:upper:]')"
if [[ -z "${bundle}" || "${bundle}" == "-H" || "${bundle}" == "--HELP" ]]; then
  usage
  exit 0
fi

echo "Bundle ${bundle} proof-gate checklist"
echo "Reference: ops/BUNDLE_PROOF_GATES.md"
echo
echo "Baseline checks:"
echo "  python3 -m compileall ."
echo "  ruff check ."
echo "  .venv/bin/python -m pytest -q"
echo

case "${bundle}" in
  B001|BUNDLE1)
    cat <<'EOF'
Bundle 1 API checks:
  curl -sS -X POST "$BASE_URL/admin/access-codes/resolve" \
    -H "Authorization: Bearer $VOZ_ADMIN_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"code":"<OWNER_CODE>"}'

  curl -sS -X POST "$BASE_URL/admin/access-codes/resolve" \
    -H "Authorization: Bearer $VOZ_ADMIN_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"code":"<CUSTOMER_CODE>"}'

  curl -sS "$BASE_URL/owner/events?tenant_id=<TENANT_ID>&limit=50" \
    -H "Authorization: Bearer $VOZ_OWNER_API_KEY"
EOF
    ;;
  B002|BUNDLE2)
    cat <<'EOF'
Bundle 2 checks:
  - verify business profile/template APIs
  - verify OCR ingest schema path
  - manual customer call: hours/pricing grounding
  - confirm flow_a.knowledge_context in owner events
EOF
    ;;
  B003|BUNDLE3)
    cat <<'EOF'
Bundle 3 checks:
  - reconcile/extract path emits postcall artifacts
  - idempotent notification markers (SMS/email) per rid
  - owner inbox actions reflected in insights summary
EOF
    ;;
  B004|BUNDLE4)
    cat <<'EOF'
Bundle 4 checks:
  - goal creation + wizard approval
  - scheduler tick executes due playbook
  - execution logs + notifications emitted
EOF
    ;;
  *)
    echo "Unknown bundle '${bundle}'."
    echo "Supported: B001, B002, B003, B004"
    exit 2
    ;;
esac
