# 营养报告后端迁移说明

## 2026-09-08：机器初稿替换为运动员V2.0规则

当前自动评价不再调用旧的固定食物分类区间、固定能量/钙阈值或女性EER评价。
旧配置与私有辅助方法仅保留兼容参考，不参与当前报告及预览。
实际摄入量计算和人工复核流程保留；PDF新增专项页，Excel新增“运动员专项评价”表。

- 参数文件：`config/athlete_intervention_v2.json`，来源为用户提供的《运动员膳食干预参数V2.0》。
- `user.athleteType`：`strength`、`team`、`endurance`；未选择时只按配置中的项目名称精确匹配。
- `user.trainingPhase`：`training`时才应用规则；未填写时仅识别明确的“正常训练/训练期”等当前状态。赛期、其他或未知阶段不评价。
- 体重须为有效正数（kg），缺失不计算蛋白质/碳水目标；年龄缺失不计算钙目标。
- 成年分界暂按18岁实现，是待业务确认的实现假设，原文未写明；已在报告中明确提示。
- 约5/7 g/kg的碳水为参考点，不划定合格区间；有氧蛋白质只比较下限；钙和蔬菜不判断过量。
- 脂肪供能比分母与原三大营养素图一致：蛋白质×4+碳水×4+脂肪×9，分母为0时不评价。
- 文档未给出总能量及其他食物类别标准，显示未提供标准，不沿用旧结论。
- `athlete_evaluation.rows`保留参考目标、差值、机器初稿与人工最终评价。建议为审核初稿，不是临床处方。
- 手动评价支持新增`proteinEvaluation`、`carbohydrateEvaluation`、`fatEvaluation`；空字符串表示不计算/清除评价。

验证：`python -m unittest discover -s tests -p "test_athlete*.py" -v`及原营养报告测试。
以下迁移说明中的旧评价方式仅描述历史实现。

本目录从只读源项目 `D:\project\python\营养\vue-project\vue-project` 迁移而来。源项目未修改；没有复制其 `node_modules/`、`dist/`、`.venv/`、`output/`、压缩包、IDE 配置或 Vue 源码。

## 迁移内容

- `nutrition.py`：原 `services/nutrition_service.py` 的营养计算、分类评价、女性 EER 和手动评价逻辑；资源路径改为包内绝对路径，并显式返回未匹配食物。
- `builders/pdf.py`：原 PDF 构建逻辑；三大营养素供能占比使用 PDF 原生矢量饼图，修复硬编码工作目录、固定临时文件名及并发覆盖问题，支持环境变量 `NUTRITION_REPORT_FONT` 指定中文字体，并在 PDF 中展示人员、日期和 OCR 换算告警。
- `builders/excel.py`：原五张营养分析工作表，并新增 `OCR换算说明` 工作表。
- `config/`、`data/food_db.json`：报告计算配置和食物营养数据；当前紧凑 PDF 不嵌入食物照片，营养素占比图以矢量方式绘制。
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
