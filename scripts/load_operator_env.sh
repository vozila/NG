#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
  SCRIPT_PATH="${BASH_SOURCE[0]}"
elif [[ -n "${ZSH_VERSION:-}" ]]; then
  SCRIPT_PATH="${(%):-%N}"
else
  SCRIPT_PATH="$0"
fi

ROOT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/ops/env/operator.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}" >&2
  echo "Create it from template:" >&2
  echo "  cp ops/env/operator.env.example ops/env/operator.env" >&2
  return 2 2>/dev/null || exit 2
fi

set -a
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +a

required=(BASE_URL TENANT_ID VOZ_OWNER_API_KEY VOZ_ADMIN_API_KEY)
missing=()
for k in "${required[@]}"; do
  eval "val=\${$k:-}"
  if [[ -z "${val}" ]]; then
    missing+=("${k}")
  fi
done

if (( ${#missing[@]} > 0 )); then
  echo "Loaded ${ENV_FILE}, but missing required vars: ${missing[*]}" >&2
  return 3 2>/dev/null || exit 3
fi

echo "Loaded operator env from ${ENV_FILE}"
echo "BASE_URL=${BASE_URL}"
echo "TENANT_ID=${TENANT_ID}"
