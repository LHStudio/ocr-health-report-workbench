#!/usr/bin/env bash
# OCR 服务统一管理脚本：启动、状态、API 重启和日志查看。
set -Eeuo pipefail

ROOT_DIR="${OCR_ROOT_DIR:-/root}"
PYTHON_BIN="${OCR_PYTHON_BIN:-/root/miniconda3/bin/python}"
MODEL_BIN="${OCR_MODEL_BIN:-/root/miniconda3/bin/paddlex_genai_server}"
MODEL_PORT="${OCR_MODEL_PORT:-8118}"
API_PORT="${OCR_API_PORT:-6006}"
MODEL_URL="http://127.0.0.1:${MODEL_PORT}/v1/models"
MODEL_VLLM_URL="http://127.0.0.1:${MODEL_PORT}/v1"
API_URL="http://127.0.0.1:${API_PORT}/"
LOG_DIR="${OCR_LOG_DIR:-${ROOT_DIR}/ocr_logs}"
MODEL_LOG="${LOG_DIR}/model_${MODEL_PORT}.log"
API_LOG="${LOG_DIR}/api_${API_PORT}.log"

on_error() {
  local exit_code=$?
  echo "[失败] 脚本在第 ${BASH_LINENO[0]} 行退出（状态码 ${exit_code}）。" >&2
  echo "[提示] 查看日志：${MODEL_LOG} 和 ${API_LOG}" >&2
  exit "${exit_code}"
}
trap on_error ERR

ensure_log_dir() {
  mkdir -p "${LOG_DIR}"
}

model_ready() {
  curl -fsS --max-time 5 "${MODEL_URL}" >/dev/null 2>&1
}

api_ready() {
  curl -fsS --max-time 5 "${API_URL}" >/dev/null 2>&1
}

wait_until_ready() {
  local label=$1
  local url=$2
  local attempts=$3
  local interval=$4
  local elapsed=0

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl -fsS --max-time 5 "${url}" >/dev/null 2>&1; then
      echo "[就绪] ${label} 已可用。"
      return 0
    fi
    elapsed=$((attempt * interval))
    echo "[等待] ${label} 尚未就绪，已等待 ${elapsed}s / $((attempts * interval))s；继续检查…"
    sleep "${interval}"
  done

  echo "[失败] ${label} 在 $((attempts * interval)) 秒内未启动。" >&2
  return 1
}

start_model() {
  if model_ready; then
    echo "[就绪] OCR 模型服务已在 ${MODEL_PORT} 端口运行。"
    return 0
  fi
  if [[ ! -x "${MODEL_BIN}" ]]; then
    echo "[失败] 未找到模型启动程序：${MODEL_BIN}" >&2
    return 1
  fi

  ensure_log_dir
  echo "[启动] 正在启动 PaddleOCR-VL 模型服务（端口 ${MODEL_PORT}）…"
  nohup "${MODEL_BIN}" --model_name PaddleOCR-VL-0.9B --backend vllm --port "${MODEL_PORT}" >"${MODEL_LOG}" 2>&1 &
  echo "[进程] 模型服务已提交后台，PID=$!；日志：${MODEL_LOG}"
  wait_until_ready "OCR 模型服务" "${MODEL_URL}" 48 5
}

start_api() {
  if api_ready; then
    echo "[就绪] OCR API 已在 ${API_PORT} 端口运行。"
    return 0
  fi
  if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "[失败] 未找到 Python：${PYTHON_BIN}" >&2
    return 1
  fi
  if ! model_ready; then
    echo "[失败] 模型服务未就绪，取消启动 OCR API。" >&2
    return 1
  fi

  ensure_log_dir
  echo "[启动] 正在启动 OCR FastAPI（端口 ${API_PORT}）…"
  (
    cd "${ROOT_DIR}"
    nohup env PADDLEOCR_VL_SERVER_URL="${MODEL_VLLM_URL}" "${PYTHON_BIN}" -m uvicorn app:app --host 0.0.0.0 --port "${API_PORT}" >"${API_LOG}" 2>&1 &
    echo "$!" >"${LOG_DIR}/api_${API_PORT}.pid"
  )
  echo "[进程] OCR API 已提交后台；日志：${API_LOG}"
  wait_until_ready "OCR FastAPI" "${API_URL}" 30 2
}

stop_api() {
  local pids
  pids="$(pgrep -f "uvicorn app:app.*--port ${API_PORT}" || true)"
  if [[ -z "${pids}" ]]; then
    echo "[提示] 未发现 ${API_PORT} 端口的 OCR API 进程。"
    return 0
  fi

  echo "[停止] 正在停止 OCR API：${pids}"
  kill ${pids}
  for ((attempt = 1; attempt <= 15; attempt++)); do
    if ! pgrep -f "uvicorn app:app.*--port ${API_PORT}" >/dev/null; then
      echo "[完成] OCR API 已停止。"
      return 0
    fi
    echo "[等待] API 正在退出… ${attempt}s / 15s"
    sleep 1
  done
  echo "[失败] OCR API 未能在 15 秒内停止；未强制结束，请检查进程和日志。" >&2
  return 1
}

show_status() {
  echo "[检查] 模型服务：${MODEL_URL}"
  if model_ready; then
    echo "[就绪] 模型服务正常。"
  else
    echo "[未就绪] 模型服务不可访问。"
  fi
  echo "[检查] OCR API：${API_URL}"
  if api_ready; then
    echo "[就绪] OCR API 正常。"
    curl -fsS --max-time 5 "${API_URL}"
    printf '\n'
  else
    echo "[未就绪] OCR API 不可访问。"
  fi
  echo "[进程]"
  ps -eo pid,ppid,etime,args | grep -E '[u]vicorn app:app|[p]addlex_genai_server.*--port' || true
}

show_logs() {
  ensure_log_dir
  echo "===== 模型日志（最近 80 行）====="
  tail -n 80 "${MODEL_LOG}" 2>/dev/null || echo "（暂未生成模型日志）"
  echo "===== OCR API 日志（最近 80 行）====="
  tail -n 80 "${API_LOG}" 2>/dev/null || echo "（暂未生成 API 日志）"
}

usage() {
  cat <<'EOF'
用法：bash /root/start_ocr_stack.sh <命令>

命令：
  start        启动模型和 OCR API；已运行的服务不会重复启动
  status       显示模型/API 健康状态和相关进程
  restart-api  仅重启 OCR API，模型服务保持运行
  stop-api     仅停止 OCR API
  logs         显示模型与 API 的最近 80 行日志
EOF
}

case "${1:-start}" in
  start)
    echo "[开始] OCR 服务统一启动。"
    start_model
    start_api
    echo "[完成] OCR 服务已启动。"
    show_status
    ;;
  status) show_status ;;
  restart-api)
    echo "[开始] 仅重启 OCR API，模型服务不会重启。"
    stop_api
    start_model
    start_api
    echo "[完成] OCR API 已重启。"
    show_status
    ;;
  stop-api) stop_api ;;
  logs) show_logs ;;
  -h|--help|help) usage ;;
  *)
    echo "[失败] 不支持的命令：${1}" >&2
    usage >&2
    exit 2
    ;;
esac
