#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="${APP_DIR}/run"

for service in api model; do
  pid_file="${RUN_DIR}/${service}.pid"
  if [[ -f "${pid_file}" ]]; then
    pid="$(cat "${pid_file}")"
    if kill -0 "${pid}" >/dev/null 2>&1; then
      kill "${pid}"
      echo "已停止 ${service}，PID=${pid}"
    fi
    rm -f "${pid_file}"
  fi
done
