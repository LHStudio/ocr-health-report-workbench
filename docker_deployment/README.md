# Docker OCR API 部署包

此目录用于部署到**另一台 Docker 服务器**。它不使用本机服务器的 `/root/start_ocr_stack.sh`，而是通过 `docker_ocr_service.sh` 管理 Docker API 容器。

## 压缩包内文件

| 文件 | 用途 |
| --- | --- |
| `app.py` | 当前增强版 OCR API，保留姓名增强、问卷勾选识别、`/classic-ocr`、耗时统计等功能；同时支持 Docker 环境变量。 |
| `references/app_docker_original_20260723.py` | 对方给出的 Docker 原始版，原样留档，不会被部署脚本使用。 |
| `Dockerfile` | OCR API 容器构建定义。 |
| `docker-compose.yml` | 对外暴露 6006、挂载 `runtime/`、传入模型地址。 |
| `.env.example` | Docker 模型地址和运行目录示例。 |
| `docker_ocr_service.sh` | `start/status/restart/logs/stop` 一键管理与启动进度反馈。 |
| `questionnaire_templates/food_frequency_blank_reference.png` | 增强版食物频率问卷勾选/姓名识别所需模板。 |
| `references/PaddleOCR-VL.yaml` | 原服务器模型配置留档；仅在目标模型服务明确要求时使用。 |

模型权重没有放入压缩包。目标服务器必须已有可用的 PaddleOCR-VL / vLLM 模型服务，且容器内能访问它的 `8118/v1` 接口。

## 部署步骤

1. 将整个目录解压到 Docker 服务器，例如 `/opt/ocr-docker`。
2. 在目录中复制环境变量文件：

   ```bash
   cp .env.example .env
   ```

3. 编辑 `.env`，填写目标机模型服务地址。

   - 对方原始 Docker 配置使用：`http://172.18.0.2:8118/v1`
   - 若模型跑在宿主机且支持 Docker host gateway，可用：`http://host.docker.internal:8118/v1`
   - 若模型是同一 Compose 网络内的独立容器，可用：`http://模型服务名:8118/v1`

4. 先在 API 容器可访问的网络中验证模型接口：

   ```bash
   curl http://实际模型地址:8118/v1/models
   ```

5. 启动 API：

   ```bash
   chmod +x docker_ocr_service.sh
   bash docker_ocr_service.sh start
   ```

6. 查看状态、日志或重启：

   ```bash
   bash docker_ocr_service.sh status
   bash docker_ocr_service.sh logs
   bash docker_ocr_service.sh restart
   ```

## 接口调用

API 为 `POST /parse-file`，请求格式是 `multipart/form-data`。

- `file`：必填，PDF/PNG/JPG/JPEG/BMP/WEBP。
- `processing_mode`：可选，`fast` 或 `accurate`，默认 `accurate`。
- `document_kind`：可选，`auto`、`medical`、`nutrition`，默认 `auto`。
- `page_index`：可选，默认 `1`。
- `include_assets`：可选，默认 `true`。

只传 `file` 的调用方式仍然可用。

## 重要限制

- `172.18.0.2` 只适用于对方原 Docker 网络；不要直接用于当前裸机服务器。
- `PADDLE_PACKAGE` 必须与目标 Docker 的 CUDA、驱动和 GPU 环境相匹配。若目标机已有专用 PaddleOCR 镜像，应以该镜像为基础调整 `Dockerfile`。
- `runtime/` 保存上传和输出；空间有限时可在停止任务后清空其中的 `uploads/` 和 `outputs/`。
