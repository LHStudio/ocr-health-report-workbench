from pathlib import Path
import unittest,tempfile,json
import fitz,openpyxl
from nutrition_report import NutritionReportService
try:
 from tests.test_nutrition_logic_followup import LogicTest
except ModuleNotFoundError:
 from test_nutrition_logic_followup import LogicTest
class RC6Test(unittest.TestCase):
 def test_version_and_words(self):
  root=Path(__file__).resolve().parents[1]
  self.assertEqual('7.3.2-RC7',json.loads((root/'package.json').read_text(encoding='utf8'))['version'])
  ui=(root/'src/App.vue').read_text(encoding='utf8')
  self.assertIn('`V${appMetadata.version}`',ui);self.assertIn('Build2026.10.15',ui);self.assertIn('<br',ui)
  text='\n'.join(LogicTest().report()['suggestions'])
  self.assertNotIn('折算参考目标',text);self.assertNotIn('用于等能量替换估算',text)
 def test_pdf_layout_and_target_color(self):
  report=LogicTest().report();service=NutritionReportService(prefer_cloud=False)
  with tempfile.TemporaryDirectory() as tmp:
   pdf=Path(tmp)/'sample.pdf';xlsx=Path(tmp)/'sample.xlsx'
   service.pdf_builder.build(report,pdf);service.excel_builder.build(report,xlsx)
   with fitz.open(pdf) as doc:
    self.assertTrue(all(t in doc[0].get_text() for t in ('豆类','坚果','奶类')))
    page=next(p for p in doc if '能量及钙摄入量评估报告' in p.get_text())
    lines=[l for b in page.get_text('dict')['blocks'] for l in b.get('lines',[])]
    labels={ ''.join(s['text'] for s in l['spans']).strip():l['bbox'] for l in lines}
    body=[l['bbox'] for l in lines if any('配餐复验未通过' in s['text'] for s in l['spans'])]
    note=next(s['bbox'] for l in lines for s in l['spans'] if s['text'].strip()=='说明')
    self.assertLess(labels['能量及钙摄入量评估报告'][1],80);self.assertLess(labels['项目'][1],120)
    # Content-sized explanation/note replaces the former full-page filler.
    self.assertTrue(body);self.assertLess(max(b[3] for b in body),note[1]);self.assertLess(note[1],600)
    interpretation_bottom=max(l['bbox'][3] for l in lines if min(b[1] for b in body)<=l['bbox'][1]<note[1])
    self.assertLess(note[1]-interpretation_bottom,30)
    athlete=next(p for p in doc if '运动员专项膳食评价' in p.get_text())
    advice=[s for b in athlete.get_text('dict')['blocks'] for l in b.get('lines',[]) for s in l['spans'] if s['text'].strip()=='不建议吃零食']
    self.assertTrue(any(s['color']==0 for s in advice),advice)
   wb=openpyxl.load_workbook(xlsx);ws=wb['运动员专项评价']
   cells=[c for row in ws for c in row if c.column==4 and c.value=='不建议吃零食'];self.assertTrue(cells)
   self.assertTrue(all(c.font.color and c.font.color.type=='rgb' and c.font.color.rgb[-6:]=='000000' for c in cells));wb.close()
