# OCR 健康报告工作台

当前版本：`4.2.0`
文档更新：2026-08-20

本目录是 Windows 本地工作台，包含 Vue 前端和本地 FastAPI 业务后端。远端 Linux GPU OCR 服务已经独立到 [`../服务器配置`](../服务器配置/README.md)，不再与本项目混放。

## 系统边界

```text
浏览器 / Vue（127.0.0.1:5173）
               │ /local-api
               ▼
本地 FastAPI（127.0.0.1:8000）
               │ 上传 PDF/图片，调用 /parse-file 或 /classic-ocr
               ▼
远端 OCR API（默认服务器端口 6006）
               │
               ▼
PaddleOCR-VL 模型服务（服务器内部端口 8118）
```

- 本地后端负责业务规则、任务状态、人工核对、Excel/PDF 导出和历史数据读取。
- 远端服务器只负责 OCR、OpenCV 图像增强和结构化识别。
- Vue 开发服务器会把 `/local-api` 和 `/local-files` 代理到本地 `8000` 端口。

## 当前功能

| 工作台 | 主要能力 |
| --- | --- |
| 体检报告回写 | 批量识别体检 PDF，回写 Excel 模板，按可配置正常范围标记异常值，支持逐项人工修正 |
| 食物频率调查 | 识别问卷、频率、数量、保健品和勾选项，支持批量核对与 Excel 汇总 |
| 营养评价与报告 | 按核对后的问卷生成营养 PDF/Excel，可修改个人资料、评价和建议 |
| 体成分合并 | 识别 InBody 等报告中的姓名、性别、年龄、身高、体重和去脂体重，并人工确认人员配对 |
| 影像识别 | 提取超声报告中的姓名、性别、年龄、超声所见、诊断和检查时间，核对后导出 Excel |
| 通用识别 | 不套用医疗字段规则，输出 Excel、Markdown 或 JSON；多文件结果可打包为 ZIP |

## 快速启动

环境要求：

- Windows 10/11；
- Python 3.10+；
- Node.js 18+；
- 一个可访问的远端 OCR API。

首次使用先安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

随后双击：

```text
一键启动前后端.bat
```

脚本会在缺少前端依赖时自动执行 `npm install`，依次等待本地后端和前端就绪，然后打开：

```text
http://127.0.0.1:5173
```

结束使用时双击：

```text
一键关闭前后端.bat
```

关闭脚本会终止本项目启动的进程，并确认 `8000`、`5173` 端口已经释放。

## 手动启动

需要观察完整日志时，可在两个 PowerShell 窗口分别运行：

```powershell
npm install
npm run backend
```

```powershell
npm run dev
```

对应命令定义在 `package.json`：

- `npm run backend`：启动本地 FastAPI，端口 `8000`；
- `npm run dev`：启动 Vue/Vite，端口 `5173`；
- `npm run build`：生成生产构建；
- `npm run preview`：在 `3000` 端口预览生产构建。

## 配置远端 OCR 服务

1. 打开任一工作台右上角的“设置”。
2. 填写远端 OCR API 的公网 HTTPS 地址或完整 `/parse-file` 地址。
3. 点击“测试连接”。
4. 选择快速或精确识别模式后保存。

OCR 地址保存在当前浏览器的 `localStorage` 中，各工作台共用。也可以通过构建环境变量 `VITE_OCR_API_URL` 提供默认地址。

注意：SSH 登录地址不是 OCR API 地址。服务器部署方法见 [`../服务器配置/README.md`](../服务器配置/README.md)。

## 数据位置

当前项目中的 `data` 是一个 Windows 目录联接，实际指向：

```text
D:\develop\ocr转换\数据资料\处理数据\data
```

其中主要包含：

- `jobs/`：上传文件、OCR 中间结果、任务状态和导出结果；
- `templates/`：最近使用的体检模板和正常范围配置；
- `audits/`、`visual_audit_*`：识别审核材料。

不要把 `data` 联接改成空目录，否则历史任务会显示 404。原始扫描件和影像资料位于工作区顶层的 `数据资料/原始材料`，不会提交到 Git。

## 项目结构

```text
当前项目/
├─ src/                         # Vue 页面与组件
├─ local_service.py             # 本地 FastAPI、任务调度与业务解析
├─ nutrition_report/            # 营养计算和 PDF/Excel 构建
├─ questionnaire_templates/     # 本地问卷增强脚本使用的参考图
├─ templates/                   # 默认 Excel 模板
├─ scripts/                     # 数据重建和识别增强工具
├─ tests/                       # 自动化回归测试
├─ server_entry.py              # 生产模式单端口入口
├─ vite.config.js               # 开发服务器及本地代理
├─ 一键启动前后端.bat
└─ 一键关闭前后端.bat
```

本目录不再包含 Docker、远端服务器 `app.py`、服务器快照或部署 ZIP。

## 生产模式

先构建前端：

```powershell
npm run build
```

再使用单端口入口：

```powershell
python -m uvicorn server_entry:app --host 127.0.0.1 --port 6008
```

访问 `http://127.0.0.1:6008`，健康检查地址为 `/healthz`。

## 验证

```powershell
python -m unittest discover -s tests -v
npm run build
```

最近一次整理后共运行 85 项测试，全部通过；另有 1 项因缺少历史回归样本而跳过。

## 常见问题

### 前端出现 `ECONNREFUSED 127.0.0.1:8000`

本地 FastAPI 尚未启动或启动失败。重新运行一键关闭脚本，再运行一键启动脚本，并查看“Backend”命令窗口。

### OCR 服务测试失败

先确认填写的是公网 HTTP/HTTPS API 地址，再到服务器运行 `./health_check.sh`。不要填写 SSH 地址或仅供服务器内部访问的 `8118` 地址。

### 历史任务返回 404

检查当前项目的 `data` 是否仍为指向 `数据资料/处理数据/data` 的目录联接。

### 端口被占用

运行 `一键关闭前后端.bat`。脚本会释放本项目使用的 `8000` 和 `5173` 端口。

## 数据与隐私

- 体检、影像和问卷文件包含敏感个人信息，不应上传到代码仓库或无访问控制的共享位置。
- OCR 服务地址、账号、密码和令牌不要写入源码。
- Git 已忽略任务数据、运行日志、构建产物、缓存和本地环境配置。
