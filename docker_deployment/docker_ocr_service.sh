#!/usr/bin/env bash
# Docker OCR API 统一管理脚本。模型服务由 PADDLEOCR_VL_SERVER_URL 指向的实例负责。
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_URL="${OCR_API_HEALTH_URL:-http://127.0.0.1:6006/}"

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    docker-compose "$@"
  fi
}

wait_for_api() {
  for ((attempt = 1; attempt <= 30; attempt++)); do
    if curl -fsS --max-time 5 "${API_URL}" >/dev/null 2>&1; then
      echo "[就绪] OCR API 已可用：${API_URL}"
      curl -fsS --max-time 5 "${API_URL}"
      printf '\n'
      return 0
    fi
    echo "[等待] OCR API 尚未就绪，已等待 $((attempt * 2))s / 60s…"
    sleep 2
  done
  echo "[失败] OCR API 未在 60 秒内启动；请执行 logs 查看原因。" >&2
  return 1
}

usage() {
  cat <<'EOF'
用法：bash docker_ocr_service.sh <命令>

命令：
  start    构建并后台启动 OCR API，然后检查 6006 健康状态
  status   显示容器状态和 API 健康状态
  restart  重建并重启 OCR API
  logs     查看最近 120 行 API 日志
  stop     停止并删除 OCR API 容器（不会删除 runtime 数据）
EOF
}

cd "${ROOT_DIR}"
case "${1:-start}" in
  start)
    echo "[开始] 构建并启动 Docker OCR API…"
    compose up -d --build
    wait_for_api
    ;;
  status)
    compose ps
    if curl -fsS --max-time 5 "${API_URL}"; then printf '\n'; else echo "[未就绪] ${API_URL}"; fi
    ;;
  restart)
    echo "[开始] 重建并重启 Docker OCR API…"
    compose up -d --build --force-recreate
    wait_for_api
    ;;
  logs) compose logs --tail=120 ocr-api ;;
  stop) compose down ;;
  -h|--help|help) usage ;;
  *) echo "[失败] 不支持的命令：${1}" >&2; usage >&2; exit 2 ;;
esac
