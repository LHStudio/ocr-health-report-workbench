# 营养报告独立推送

`scripts/push_nutrition_reports.py` 只读取现有报告 XLSX，将七个工作表映射至平台 `POST /open/nutrition`。不调用报告生成器，不重算营养值，不修改 PDF、Excel、调查缓存或运动员基本资料。未接入自动报告生成流程；需要推送时单独运行。

## PowerShell

```powershell
$env:SURVEY_BASE_URL = 'https://your-platform.example'
$env:SURVEY_OPEN_TOKEN = '<平台开放接口凭证>'
python scripts/push_nutrition_reports.py --input 'D:/private/reports' --audit-dir 'D:/private/push-audit'
# 核查 preflight.json、rejected.json 后发送：
python scripts/push_nutrition_reports.py --input 'D:/private/reports' --audit-dir 'D:/private/push-audit' --commit
```

脚本读取进程环境变量，不会自动加载 `.env`。凭证不能写进代码、命令参数、审计文件或 Git。审计目录及请求体、回执包含个人健康数据，必须保留在本机私有目录，不得提交 Git。

若部署通过 `/api` 反向代理后端，设置 `SURVEY_BASE_URL=https://your-platform.example/api`，实际请求将发送到 `/api/open/nutrition`。不要向前端静态站点路径反复重试；应先确认部署的 API 前缀。

## 数据和匹配

- 从指定目录递归读取 XLSX；不要选择混有原始问卷或历史重复报告的目录。
- 表头按实际平台展示契约使用无空格键名，例如 `摄入量(g)`、`能量(kcal)`、`摄入原重(g)`；源表带空格时也能识别。PDF 文档提取文本可能在单位前插入空格，不能把该排版空格带入输出键名。数值、推荐区间、评价、建议、报告生成日期原样传递。
- 日期转换为同一天的 `yyyy-MM-dd`，不使用今天或报告生成时间替换调查日期。四位年份、点号、斜线、中文年月日支持；两位年份、无法识别的日期拒绝并记录。原工作簿不修改。
- 缺失值保持空值。公式、未知表头、重复字段、超过500行的明细拒绝，不能静默丢失。
- 无法转换的报告写入 `rejected.json`，其余合格报告仍可推送，整体退出码为2，不冒充全部完成。
- 平台按精确姓名匹配。没有匹配或同名缺少出生日期时，保留业务失败回执，不猜姓名、不新建运动员。
- 可通过 `--birthdays D:/private/birthdays.json` 提供已确认出生日期。JSON 键为工作簿绝对路径，值为 `yyyy-MM-dd`。禁止按年龄推算出生日期。补充映射改变批次，应使用新审计目录且仅选择需补推的报告。
- 同一运动员、同一天再次推送可能覆盖平台已有营养报告；脚本不能撤销远端写入。源码回滚不等于撤销数据推送。

## 断点和错误

- 每次请求前保存 `sending` 状态；确认 HTTP200、业务 `code=0`、姓名和日期以及报告ID后才记成功。
- 相同目标、相同输入和同一审计目录重新运行会跳过成功记录。
- `--retry-failed` 只重试明确业务失败；超时、重定向、非JSON、未知HTTP或不匹配回执均视为不确定，不自动重发。先在平台核对是否已写入，再由操作人员处理，不删除检查点绕过保护。
- 凭证错误立即停止余下发送；重定向不跟随，避免凭证或健康数据发往其他站点。
- `push.lock` 阻止同一审计目录并行发送。异常终止后先核对进程和平台状态，再人工清除残留锁。不应同时从多个审计目录发送同一批次。
- `summary.json` 给出 success / failed / uncertain / pending / rejected；`checkpoint.json` 保存每项接口回执和文件哈希；`payloads/` 保存实际请求体。
- 退出码：0表示全部成功或全部预检通过；2表示部分失败、不确定、未发送或拒绝；1表示配置/批次校验错误。

测试：`python tests/test_nutrition_push.py`（合成数据，无真实网络请求）。依赖沿用已有 requests、openpyxl，无前后端构建变动。

## 端到端验收与 PDF

`code=0` 只证明接口接受请求，不保证页面列绑定正确。部署验收应登录平台回读对应分析报告，将 `metrics.foods`、`metrics.categories` 与发送内容逐字段比较，并检查页面实际显示数值。字段映射修复后，用独立审计目录更新已确认的同人同日报告；原回执保留，核对返回 `created=false` 且报告ID不变。

当前文档仅提供 JSON 营养数据接口，没有 PDF 文件上传端点、文件字段或附件URL约定。本脚本不上传 PDF，也不生成或修改 PDF。若需在平台下载原始 PDF，须先获得平台提供的附件上传及报告关联接口。
