# Linux GPU OCR 服务器

接口版本：`1.5-body-composition`
文档更新：2026-08-20

本目录是独立的远端 OCR 部署包，为本地“医疗 OCR 健康报告工作台”提供文字、版面、表格和 OpenCV 问卷识别能力。它不包含 Vue 页面，也不负责本地人工核对和报告导出流程。

## 服务架构

```text
本地工作台 / 其他客户端
          │ HTTPS 映射到 6006
          ▼
FastAPI app.py（0.0.0.0:6006）
          ├─ PaddleOCR-VL 文档 OCR ──► 127.0.0.1:8118/v1
          ├─ PP-OCRv5 经典图片 OCR
          └─ OpenCV 对齐、裁剪、墨迹差分与勾选识别
```

- `6006`：OCR FastAPI；可通过算力平台或反向代理映射为 HTTPS 地址。
- `8118`：PaddleOCR-VL/vLLM 模型服务，只应在服务器内部访问。

## 当前能力

- PDF 和常见图片的 PaddleOCR-VL 版面识别；
- Markdown、JSON、Excel 和图像证据的结构化响应；
- `fast`、`accurate` 两种处理模式；
- 体检、营养问卷和体成分文档分类；
- OpenCV 问卷透视对齐、墨迹差分和食物频率勾选识别；
- OpenCV 日照选项识别；
- 问卷姓名、体成分表头的增强 OCR；
- PP-OCRv5 小图片/手写裁剪识别。

## API

### `GET /`

健康检查，正常返回 `status: ok`、接口版本和 `/parse-file` 参数说明。

### `POST /parse-file`

请求类型：`multipart/form-data`。

| 字段 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `file` | 是 | — | PDF 或受支持的图片文件 |
| `processing_mode` | 否 | `accurate` | `fast` 或 `accurate` |
| `document_kind` | 否 | `auto` | `auto`、`medical`、`nutrition`、`body_composition` |
| `page_index` | 否 | `1` | 当前文件在人员文档中的页序号，从 1 开始 |
| `include_assets` | 否 | `true` | 是否返回调试/识别图片资源 |

兼容旧客户端只提交 `file` 的调用方式。

### `POST /classic-ocr`

接收单张图片，使用 CPU 上的 PP-OCRv5 返回文本、置信度和文本框。该接口不接受 PDF。

## 文件说明

```text
服务器配置/
├─ app.py                         # 当前 FastAPI OCR 服务
├─ requirements.txt               # API 额外 Python 依赖
├─ start.sh                       # 启动 8118 模型和 6006 API
├─ stop.sh                        # 根据 PID 停止 API 和模型
├─ health_check.sh                # 检查端口、接口和进程
├─ PaddleOCR-VL.yaml              # 模型管线配置参考
└─ questionnaire_templates/
   ├─ food_frequency_blank_reference.png
   ├─ food_frequency_sunlight_blank_reference.png
   └─ food_frequency_sunlight_real_scan_reference.png
```

三张问卷参考图是 OpenCV 对齐和勾选识别的运行依赖，不能删除、改名或单独遗漏。日照识别默认沿用历史模板；只有历史模板对齐置信度低于 `0.45`，并且实物扫描模板至少高出 `0.05` 时，才自动切换到实物扫描模板。`PaddleOCR-VL.yaml` 不由 `start.sh` 直接读取，只有在服务器 PaddleX 管线配置需要同步时才应用，覆盖前应确认 PaddleX 版本匹配。

### 实物扫描模板验证

- 新增的三页空白实物报告统一按服务器 PDF `2.0×` 渲染尺寸处理，即 `1190×1684`；
- 第一页新扫描在 39 组历史问卷上的平均对齐置信度为 `0.7509`，低于原模板的 `0.7864`，因此第一页不替换；
- 第三页新扫描校准到历史坐标系后，平均对齐置信度由 `0.7041` 提升到 `0.7594`；
- 为保证历史结果不变化，第三页新模板仅作为低置信度兜底，不直接覆盖已经验证稳定的旧模板；
- 服务器强制实物模板测试的对齐置信度为 `0.941`，空白页固定选项零误报；接口响应通过 `template_variant` 标明实际使用的模板。

## 服务器前置条件

- Linux GPU 服务器；
- 可用的 NVIDIA 驱动和显存；
- 已安装 PaddleOCR/PaddleX 与 `paddlex_genai_server`；
- Python 环境能够 `import paddleocr`；
- 系统提供 `bash`、`curl`、`pgrep`、`nohup`；
- 默认 Python：`/root/miniconda3/bin/python`；
- 默认模型程序：`/root/miniconda3/bin/paddlex_genai_server`。

`requirements.txt` 只补充 FastAPI、OpenCV、PDF 和 Excel 相关依赖，不负责安装或替换 GPU/PaddleOCR 环境。

## 部署

将整个“服务器配置”目录上传，例如保存为 `/root/ocr-backend`：

```bash
cd /root/ocr-backend
/root/miniconda3/bin/python -m pip install -r requirements.txt
chmod +x start.sh stop.sh health_check.sh
./start.sh
```

`start.sh` 会：

1. 创建 `logs/`、`run/`、`data/uploads/` 和 `data/outputs/`；
2. 检查并启动 `8118` 模型服务；
3. 等待模型接口可用；
4. 启动 `6006` FastAPI；
5. 把日志和 PID 写入当前部署目录。

启动完成后测试：

```bash
curl http://127.0.0.1:8118/v1/models
curl http://127.0.0.1:6006/
./health_check.sh
```

停止服务：

```bash
./stop.sh
```

## 可配置环境变量

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `OCR_PYTHON_BIN` | `/root/miniconda3/bin/python` | API 使用的 Python |
| `OCR_MODEL_BIN` | `/root/miniconda3/bin/paddlex_genai_server` | 模型服务启动程序 |
| `OCR_MODEL_PORT` | `8118` | 模型服务端口 |
| `OCR_API_PORT` | `6006` | FastAPI 端口 |

示例：

```bash
OCR_PYTHON_BIN=/opt/conda/bin/python OCR_API_PORT=6006 ./start.sh
```

`start.sh` 会自动给 `app.py` 设置：

- `PADDLEOCR_VL_SERVER_URL=http://127.0.0.1:<模型端口>/v1`
- `OCR_SERVICE_BASE_DIR=<部署目录>/data`

## 运行数据与日志

```text
data/uploads/     临时上传文件
data/outputs/     OCR 任务输出
logs/model.log    PaddleOCR-VL 模型日志
logs/api.log      FastAPI 日志
run/model.pid     模型进程 PID
run/api.pid       API 进程 PID
```

这些目录由 `start.sh` 自动创建，不属于部署源文件。升级程序时不要把旧日志和临时输出混入新的部署包。

## 常见问题

### `8118` 无法访问

检查 NVIDIA 环境、`paddlex_genai_server` 路径和 `logs/model.log`。模型首次加载可能需要数分钟。

### `6006` 无法访问

先确认 `8118/v1/models` 正常，再查看 `logs/api.log`。也可手动验证：

```bash
cd /root/ocr-backend
/root/miniconda3/bin/python -m uvicorn app:app --host 0.0.0.0 --port 6006
```

### OpenCV 结果缺失或提示模板不存在

检查 `questionnaire_templates` 三张图片是否与 `app.py` 同级部署，文件名必须保持不变。接口响应中的 `template_variant` 会标明本次使用 `legacy` 还是 `real_scan` 模板。

### 本地工作台能打开，但 OCR 测试失败

确认公网映射指向服务器 `6006`，并从本地电脑直接访问公网健康地址。`8118` 和 SSH 地址不能填写到工作台 OCR 设置中。

## 安全建议

- `app.py` 本身不提供账号鉴权；公网开放时应在平台网关或反向代理层增加 HTTPS、访问控制和请求大小限制。
- 不要把 SSH 密码、平台令牌或真实受检者文件放入本目录。
- 更新服务器前备份现用 `app.py`，替换后运行健康检查，并用一份脱敏 PDF 验证 `/parse-file`。

## 已清理的旧内容

早期 `app.py`、Docker 版本、部署 ZIP、服务器快照、审计记录、缓存和重复启动脚本已删除。当前目录只保留最新 OpenCV 增强实现及其必要部署文件。
