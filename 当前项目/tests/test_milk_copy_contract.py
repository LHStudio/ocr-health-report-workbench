import unittest,copy,tempfile,json
from pathlib import Path
import fitz,openpyxl
from nutrition_report.nutrition import NutritionService
from nutrition_report.builders.pdf import NutritionPDFBuilder
from nutrition_report.builders.excel import NutritionExcelBuilder
from nutrition_report.builders.presentation import evaluation_rows
class MilkCopyContract(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.report=NutritionService().build_report_data({'user':{'name':'文案回归','weight':65,'age':22,'gender':'female','athleteType':'team','trainingPhase':'training'},'meals':[{'name':'鲜奶','amount':500.4},{'name':'蛋类','amount':50}]})
 def test_labels_and_advice_change_only_visible_milk_name(self):
  rows={r['key']:r for r in evaluation_rows(self.report)}
  self.assertEqual('奶类',rows['milk']['label']);self.assertEqual('肉蛋奶\n优质蛋白占比',rows['quality_protein']['label'])
  self.assertNotIn('milk',[i['key'] for i in self.report['suggestion_items']])
  self.assertNotIn('奶类适中',''.join(self.report['suggestions']))
 def test_pdf_removes_extra_milk_line_and_breaks_label_after_milk(self):
  before=copy.deepcopy(self.report)
  with tempfile.TemporaryDirectory() as t:
   for style in ['modern','legacy']:
    p=Path(t)/(style+'.pdf');NutritionPDFBuilder().build(dict(self.report,report_style=style),p)
    with fitz.open(p) as d:
     self.assertNotIn('鲜奶等价量',''.join(d[0].get_text().split()));self.assertIn('体成分结果',d[0].get_text());self.assertIn('500.4',''.join(page.get_text() for page in d))
     page=next(x for x in d if '运动员专项膳食评价' in x.get_text());lines=[''.join(s['text'] for s in l['spans']) for b in page.get_text('dict')['blocks'] for l in b.get('lines',[])]
     self.assertIn('肉蛋奶',lines);self.assertIn('优质蛋白占比',lines)
  self.assertEqual(before,self.report)
 def test_excel_table_uses_same_display_label_and_explicit_line_break(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'report.xlsx';NutritionExcelBuilder().build(self.report,p);wb=openpyxl.load_workbook(p)
   labels=[r[0].value for r in wb['运动员专项评价']]
   self.assertIn('奶类',labels);self.assertIn('肉蛋奶\n优质蛋白占比',labels);wb.close()
if __name__=='__main__':unittest.main(verbosity=2)
