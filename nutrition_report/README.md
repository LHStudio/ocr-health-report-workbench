# 营养报告后端迁移说明

本目录从只读源项目 `D:\project\python\营养\vue-project\vue-project` 迁移而来。源项目未修改；没有复制其 `node_modules/`、`dist/`、`.venv/`、`output/`、压缩包、IDE 配置或 Vue 源码。

## 迁移内容

- `nutrition.py`：原 `services/nutrition_service.py` 的营养计算、分类评价、女性 EER 和手动评价逻辑；资源路径改为包内绝对路径，并显式返回未匹配食物。
- `builders/pdf.py`：原 PDF 构建逻辑；修复硬编码工作目录、固定临时文件名及并发覆盖问题，支持环境变量 `NUTRITION_REPORT_FONT` 指定中文字体，并在 PDF 中展示人员、日期和 OCR 换算告警。
- `builders/excel.py`：原五张营养分析工作表，并新增 `OCR换算说明` 工作表。
- `config/`、`data/food_db.json`、`assets/images/`：报告计算配置、食物营养数据和保留的历史图片资源；当前紧凑 PDF 不再嵌入图片。
- `adapter.py`：新增 OCR 食物频率问卷到原报告 `user + meals` 模型的自动适配。
- `service.py`：不依赖 Flask/FastAPI 的纯 Python 门面，可由当前 `local_service.py` 直接导入。

## 原项目输入模型

原报告服务接收：

```json
{
  "user": {
    "name": "张三",
    "age": 22,
    "height": 168,
    "weight": 55,
    "gender": "female",
    "activityLevel": "2"
  },
  "date": "2026-07-21",
  "meals": [
    {"name": "米饭", "amount": 300}
  ],
  "autoEvaluation": true
}
```

`meals[].amount` 是日摄入克数。原后端把同名食物合并后，以 `food_db.json` 的每 100g 数据计算能量、蛋白质、脂肪、碳水化合物和钙；再按 `nutrition_template.json` 评价食物类别与钙，女性且年龄/PAL 完整时按 `female_energy_eer.json` 评价能量。

## OCR 数据自动换算

当前 OCR 的单人结构来自 `local_service.py`：

```python
person = {
    "id": "ocr/1",
    "general": {"姓名": "张三", "调查日期": "2026-07-01"},
    "food_rows": [{
        "食物名称": "米饭",
        "平均每次食用量": "100g",
        "次数": "2",
        "频率周期(请核对)": "每天",
        "是否不吃": ""
    }]
}
```

适配器按下式折算日均克数：

- 每天：`每次克数 × 次数`
- 每周：`每次克数 × 次数 ÷ 7`
- 每月：`每次克数 × 次数 ÷ 30`
- 每年：`每次克数 × 次数 ÷ 365`
- 不吃：0，不进入营养计算

只可靠换算克、千克；毫升按 `1 ml≈1 g` 估算并产生告警。份、个、勺等没有重量依据的单位不猜测，不进入营养值。区间用中点估算并告警。原食物数据库没有覆盖全部 38 个固定问卷项目，`FOOD_REFERENCE_MAP` 对缺项使用明确的同类代表食物，并在导出的 PDF/Excel 留下 `proxy_food_reference` 告警，不能把该估算当作精确食物成分分析。

## 纯 Python 调用

```python
from pathlib import Path
from nutrition_report import generate_pdf_from_ocr_person

result = generate_pdf_from_ocr_person(
    person,
    Path("data/jobs/<job_id>/output/张三_营养健康评估报告.pdf"),
    user_overrides={
        "age": 22,
        "gender": "female",
        "height": 168,
        "weight": 55,
        "activityLevel": "2"
    }
)

print(result["warnings"])
```

Excel 分析报告使用 `generate_excel_from_ocr_person(...)`；原格式 JSON 可用 `NutritionReportService.generate_pdf_from_json(...)` 和 `generate_excel_from_json(...)`。

## 依赖与字体

营养报告构建依赖 `reportlab` 和 `openpyxl`。Windows 默认查找 `C:\Windows\Fonts\simhei.ttf` / `msyh.ttf`；其他系统建议通过 `NUTRITION_REPORT_FONT` 指向可用的中文 TTF/TTC 字体。无字体文件时 PDF 正文回退到 ReportLab 的 `STSong-Light`。

## 测试

```powershell
python -m unittest discover -s tests -p "test_nutrition_report.py" -v
```

测试覆盖日/周/月/年换算、区间与不可换算单位告警、代表食物追溯、原 JSON 兼容、PDF 生成和 Excel 工作表结构。
