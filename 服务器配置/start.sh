#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${OCR_PYTHON_BIN:-/root/miniconda3/bin/python}"
MODEL_BIN="${OCR_MODEL_BIN:-/root/miniconda3/bin/paddlex_genai_server}"
MODEL_PORT="${OCR_MODEL_PORT:-8118}"
API_PORT="${OCR_API_PORT:-6006}"
LOG_DIR="${APP_DIR}/logs"
RUN_DIR="${APP_DIR}/run"
DATA_DIR="${APP_DIR}/data"

mkdir -p "${LOG_DIR}" "${RUN_DIR}" "${DATA_DIR}/uploads" "${DATA_DIR}/outputs"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "找不到 Python：${PYTHON_BIN}"
  echo "可通过 OCR_PYTHON_BIN 指定实际路径。"
  exit 1
fi

if [[ ! -x "${MODEL_BIN}" ]]; then
  echo "找不到 PaddleOCR 模型启动程序：${MODEL_BIN}"
  echo "可通过 OCR_MODEL_BIN 指定实际路径。"
  exit 1
fi

if ! pgrep -f "paddlex_genai_server.*--port ${MODEL_PORT}" >/dev/null 2>&1; then
  echo "正在启动 PaddleOCR 模型，端口 ${MODEL_PORT}..."
  nohup "${MODEL_BIN}" \
    --model_name PaddleOCR-VL-0.9B \
    --backend vllm \
    --port "${MODEL_PORT}" \
    >"${LOG_DIR}/model.log" 2>&1 &
  echo "$!" >"${RUN_DIR}/model.pid"
fi

echo "等待模型启动..."
for _ in $(seq 1 60); do
  if curl -fsS --max-time 3 "http://127.0.0.1:${MODEL_PORT}/v1/models" >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

if ! curl -fsS --max-time 3 "http://127.0.0.1:${MODEL_PORT}/v1/models" >/dev/null 2>&1; then
  echo "模型没有成功启动，请查看 ${LOG_DIR}/model.log"
  exit 1
fi

if ! pgrep -f "uvicorn app:app.*--port ${API_PORT}" >/dev/null 2>&1; then
  echo "正在启动 OCR API，端口 ${API_PORT}..."
  cd "${APP_DIR}"
  nohup env \
    PADDLEOCR_VL_SERVER_URL="http://127.0.0.1:${MODEL_PORT}/v1" \
    OCR_SERVICE_BASE_DIR="${DATA_DIR}" \
    "${PYTHON_BIN}" -m uvicorn app:app --host 0.0.0.0 --port "${API_PORT}" \
    >"${LOG_DIR}/api.log" 2>&1 &
  echo "$!" >"${RUN_DIR}/api.pid"
fi

echo "启动命令已完成。"
echo "OCR 地址：http://服务器IP:${API_PORT}"
echo "API 日志：${LOG_DIR}/api.log"
echo "模型日志：${LOG_DIR}/model.log"
