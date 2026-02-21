#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/run_webui.sh [dev|build|lint|test]

Defaults to: dev
USAGE
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${ROOT_DIR}/apps/vozlia-admin"
MODE="${1:-dev}"

if [[ ! -d "${APP_DIR}" ]]; then
  echo "ERROR: missing app directory: ${APP_DIR}" >&2
  exit 2
fi

if [[ ! -f "${APP_DIR}/package.json" ]]; then
  echo "ERROR: missing package.json in ${APP_DIR}" >&2
  exit 2
fi

case "${MODE}" in
  -h|--help|help)
    usage
    exit 0
    ;;
esac

if [[ ! -d "${APP_DIR}/node_modules" ]]; then
  echo "Installing webui dependencies..."
  (cd "${APP_DIR}" && npm install)
fi

case "${MODE}" in
  dev)
    echo "Starting webui dev server at http://localhost:3000 ..."
    echo "Required envs: NEXTAUTH_URL, NEXTAUTH_SECRET, VOZLIA_CONTROL_BASE_URL, VOZLIA_ADMIN_KEY"
    (cd "${APP_DIR}" && npm run dev)
    ;;
  build)
    (cd "${APP_DIR}" && npm run build)
    ;;
  lint)
    (cd "${APP_DIR}" && npm run lint)
    ;;
  test)
    (cd "${APP_DIR}" && npm test)
    ;;
  *)
    echo "ERROR: unknown mode '${MODE}'" >&2
    usage
    exit 2
    ;;
esac
