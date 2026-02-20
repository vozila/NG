#!/usr/bin/env bash
set -euo pipefail
umask 077

# Capture Render logs into rotating files under ops/logs.
# This script supports two modes:
# 1) Polling mode (recommended for Render CLI v1.1.x):
#      RENDER_RESOURCE_ID='srv-xxxx' ./scripts/capture_render_logs.sh
# 2) Generic stream command mode:
#      RENDER_LOG_CMD='some command that prints logs continuously' ./scripts/capture_render_logs.sh
#
# Optional:
#   LOG_PREFIX=vozlia-ng INTERVAL_S=2 ./scripts/capture_render_logs.sh
#   ROTATE_SECONDS=300 ROTATE_BYTES=10485760 MAX_FILES=40 ./scripts/capture_render_logs.sh
#   FETCH_LIMIT=500 LOOKBACK_SECONDS=120 ./scripts/capture_render_logs.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${ROOT_DIR}/ops/logs"
mkdir -p "${OUT_DIR}"

LOG_PREFIX="${LOG_PREFIX:-vozlia-ng}"
INTERVAL_S="${INTERVAL_S:-2}"
ROTATE_SECONDS="${ROTATE_SECONDS:-300}"
ROTATE_BYTES="${ROTATE_BYTES:-10485760}"
MAX_FILES="${MAX_FILES:-40}"
FETCH_LIMIT="${FETCH_LIMIT:-500}"
LOOKBACK_SECONDS="${LOOKBACK_SECONDS:-120}"
RENDER_RESOURCE_ID="${RENDER_RESOURCE_ID:-}"
START_ISO="${START_ISO:-}"
RENDER_LOG_CMD="${RENDER_LOG_CMD:-}"

if [[ -z "${RENDER_LOG_CMD}" && -z "${RENDER_RESOURCE_ID}" ]]; then
  cat <<'EOF'
Missing source configuration.
Provide one of:
  RENDER_RESOURCE_ID='srv-xxxx' ./scripts/capture_render_logs.sh
  RENDER_LOG_CMD='some command that prints logs continuously' ./scripts/capture_render_logs.sh
EOF
  exit 2
fi

echo "capture_render_logs: writing logs to ${OUT_DIR}"
echo "capture_render_logs: rotate_seconds=${ROTATE_SECONDS} rotate_bytes=${ROTATE_BYTES} max_files=${MAX_FILES}"
if [[ -n "${RENDER_RESOURCE_ID}" ]]; then
  echo "capture_render_logs: mode=render_poll resource_id=${RENDER_RESOURCE_ID} interval_s=${INTERVAL_S} fetch_limit=${FETCH_LIMIT}"
else
  echo "capture_render_logs: mode=stream command=<redacted>"
fi

shopt -s nullglob

current_file=""
current_started=0
current_bytes=0
file_seq=0

new_log_file() {
  local ts
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  file_seq=$((file_seq + 1))
  current_file="${OUT_DIR}/${LOG_PREFIX}-${ts}-${file_seq}.log"
  current_started="$(date +%s)"
  current_bytes=0
  : >"${current_file}"
  echo "capture_render_logs: start ${current_file}"
}

prune_old_files() {
  local files
  files=( "${OUT_DIR}/${LOG_PREFIX}-"*.log )
  local count="${#files[@]}"
  if (( count <= MAX_FILES )); then
    return
  fi
  mapfile -t files < <(ls -1t "${OUT_DIR}/${LOG_PREFIX}-"*.log)
  local i
  for ((i = MAX_FILES; i < ${#files[@]}; i++)); do
    rm -f "${files[$i]}"
    echo "capture_render_logs: pruned ${files[$i]}"
  done
}

should_rotate() {
  local now age
  now="$(date +%s)"
  age=$((now - current_started))
  if (( current_bytes >= ROTATE_BYTES )); then
    return 0
  fi
  if (( age >= ROTATE_SECONDS )); then
    return 0
  fi
  return 1
}

iso_now() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

iso_ago() {
  local seconds="$1"
  if date -u -v-"${seconds}"S +"%Y-%m-%dT%H:%M:%SZ" >/dev/null 2>&1; then
    date -u -v-"${seconds}"S +"%Y-%m-%dT%H:%M:%SZ"
    return
  fi
  if date -u -d "1970-01-01" +"%Y-%m-%dT%H:%M:%SZ" >/dev/null 2>&1; then
    date -u -d "-${seconds} seconds" +"%Y-%m-%dT%H:%M:%SZ"
    return
  fi
  iso_now
}

append_line() {
  local line="$1"
  if should_rotate; then
    echo "capture_render_logs: rotate file=${current_file} bytes=${current_bytes}"
    prune_old_files
    new_log_file
  fi
  line="$(sanitize_line "${line}")"
  printf '%s\n' "${line}"
  printf '%s\n' "${line}" >> "${current_file}"
  current_bytes=$((current_bytes + ${#line} + 1))
}

sanitize_line() {
  local line="$1"
  if [[ -n "${RENDER_RESOURCE_ID}" ]]; then
    line="${line//${RENDER_RESOURCE_ID}/<render_resource_id>}"
  fi
  line="$(printf '%s' "${line}" | sed -E \
    -e 's/(Bearer )[A-Za-z0-9._~+\/=-]+/\1<redacted>/g' \
    -e 's/([?&](token|api[_-]?key|key|secret)=)[^& ]+/\1<redacted>/Ig')"
  printf '%s\n' "${line}"
}

new_log_file

while true; do
  if [[ -n "${RENDER_RESOURCE_ID}" ]]; then
    if [[ -z "${START_ISO}" ]]; then
      START_ISO="$(iso_ago "${LOOKBACK_SECONDS}")"
    fi
    END_ISO="$(iso_now)"
    query_out=""
    if query_out="$(render logs -o text -r "${RENDER_RESOURCE_ID}" --start "${START_ISO}" --end "${END_ISO}" --direction forward --limit "${FETCH_LIMIT}" 2>&1)"; then
      while IFS= read -r line; do
        [[ -z "${line}" ]] && continue
        append_line "${line}"
      done <<< "${query_out}"
      START_ISO="${END_ISO}"
    else
      append_line "capture_render_logs: render query failed; retrying without advancing cursor start=${START_ISO} end=${END_ISO}"
      while IFS= read -r line; do
        [[ -z "${line}" ]] && continue
        append_line "${line}"
      done <<< "${query_out}"
    fi
    prune_old_files
    sleep "${INTERVAL_S}"
    continue
  fi

  # Generic stream mode.
  # shellcheck disable=SC2086
  while IFS= read -r line; do
    append_line "${line}"
  done < <(bash -lc "${RENDER_LOG_CMD}" 2>&1) || true

  echo "capture_render_logs: source ended; retry in ${INTERVAL_S}s"
  prune_old_files
  sleep "${INTERVAL_S}"
done
