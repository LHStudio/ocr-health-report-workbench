# OCR 健康报告工作台

一个面向体检报告、食物频率调查和体成分报告的本地工作台。项目把 PDF 发送到可配置的 OCR 服务，在本机完成结构化解析、人工核对和报告导出；业务数据、原始文件与运行日志均不会提交到代码仓库。

## 能力

- 体检报告：识别常用检验项目，回写到既有 Excel 模板，并提示超出正常范围的结果。
- 食物频率调查：解析食物、频率、保健品和勾选项，生成可人工复核的汇总表。
- 营养评价：按已核对的食物数据生成营养 PDF 或 Excel，支持修改人员资料、评价和建议。
- 体成分合并：可选上传 InBody 等体成分报告；系统识别“去脂体重 / 瘦体重 / Fat Free Mass”，按姓名唯一匹配到食物问卷人员，并在营养报告的个人信息中展示。
- 数据来源可追溯：营养值查询优先使用配置的营养库，连接异常时回退到内置数据库，并在导出报告中标注来源。

## 架构

```text
Vue 浏览器界面
        │
        ▼
本地 FastAPI（8000） ──► 可配置的 OCR API（/parse-file）
        │                         │
        ├── 体检模板回写           └── PDF 版面与文字识别
        ├── 食物频率解析
        ├── 体成分去脂体重提取与姓名合并
        └── 营养 PDF / Excel 导出
```

## 快速开始

环境要求：Python 3.10+、Node.js 18+，以及一个可访问的 OCR API。OCR API 需要提供 `POST /parse-file`，接收 PDF 文件并返回 OCR 的 Markdown、JSON 与 Excel 数据。

```powershell
python -m pip install -r requirements.txt
npm install
```

在两个终端分别启动本地服务和界面：

```powershell
npm run backend
```

```powershell
npm run dev
```

打开终端输出的本地地址。在“云端 OCR 服务”填写 OCR API 的公网地址；SSH 地址不是 OCR API 地址。

## 使用体成分去脂体重

1. 在“食物频率调查”上传问卷文件。
2. 在“体成分报告（可选）”选择 InBody 等报告文件或其文件夹。
3. 开始识别。系统从体成分表格提取去脂体重，并只在姓名能唯一匹配时写入对应人员。
4. 打开“营养评价与报告”。去脂体重会显示在个人信息中，也可人工修订后导出 PDF 或 Excel。

未匹配或结果不完整的体成分文件不会被错误写入其他人员，界面会提示补充对应人员资料。

## 项目结构

```text
src/                    Vue 前端
local_service.py        本地 FastAPI、OCR 调度与解析规则
nutrition_report/       营养计算、PDF 与 Excel 构建器
templates/              通用导出模板
questionnaire_templates/问卷识别参考图
tests/                  自动化回归测试
```

## 验证

```powershell
python -m unittest discover -s tests -v
npm run build
```

## 数据与隐私

- 原始 PDF、导出结果、任务状态、日志和本地服务器备份均在 `.gitignore` 中排除。
- 请使用自己的部署地址和本地环境变量保存运行配置，不要把账号、密码、令牌或受访者资料写入仓库。
- 示例模板只包含通用表头和识别参考图，不包含真实受访者信息。
