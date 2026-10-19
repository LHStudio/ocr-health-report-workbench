from pathlib import Path
import unittest,tempfile
import fitz
from nutrition_report import NutritionReportService
try:
 from tests.test_nutrition_logic_followup import LogicTest
except ModuleNotFoundError:
 from test_nutrition_logic_followup import LogicTest
class CleanupTest(unittest.TestCase):
 def test_deleted_words_and_all_foods_first_page(self):
  r=LogicTest().report();service=NutritionReportService(prefer_cloud=False)
  with tempfile.TemporaryDirectory() as t:
   pdf=Path(t)/'report.pdf';service.pdf_builder.build(r,pdf)
   with fitz.open(pdf) as doc:
    text=''.join(''.join(p.get_text().split()) for p in doc)
    for phrase in ('不能据此单独判定碳水不足','营养素克数不等于谷类食物克数','不代表谷类食物','碳水总量不足与主食结构','食物重量g≠','不使用统一百分比','不是食物重量占比','不宜仅减少谷类'):
     self.assertNotIn(phrase,text)
    first=doc[0].get_text()
    for name in ('谷类','薯类','蔬菜','水果','畜禽肉','水产品','蛋类','豆类','坚果','奶类','零食','运动营养食品','饮料','酒类'):self.assertIn(name,first)
    self.assertIn('整体评估及建议',doc[-1].get_text())
    self.assertNotIn('每日摄入量',doc[-1].get_text())
    self.assertIn('每日摄入量',doc[0].get_text())
