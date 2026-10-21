from copy import deepcopy
from pathlib import Path
import tempfile, unittest
import fitz, openpyxl
from nutrition_report import NutritionReportService


class NutritionTableLayoutTest(unittest.TestCase):
    def test_red_advice_and_no_orphan_percent_or_closing_parenthesis(self):
        service=NutritionReportService(prefer_cloud=False)
        report=service.build_report_data({'user':{'age':25,'weight':65,'gender':'female','activityLevel':'2','athleteType':'strength','trainingPhase':'training'},'meals':[{'name':'米饭','amount':200},{'name':'鲜奶','amount':450}]})
        before=deepcopy(report)
        with tempfile.TemporaryDirectory() as tmp:
            pdf=Path(tmp)/'report.pdf';xlsx=Path(tmp)/'report.xlsx'
            service.pdf_builder.build(report,pdf);service.excel_builder.build(report,xlsx)
            with fitz.open(pdf) as doc:
                spans=[s for p in doc for b in p.get_text('dict')['blocks'] for l in b.get('lines',[]) for s in l['spans']]
                advice=[s for s in spans if s['text'].strip()=='不建议吃零食']
                self.assertTrue(advice)
                self.assertTrue(any(s['color']==0 for s in advice),[(s['text'],s['color']) for s in advice])
                for page in doc:
                    if '运动员专项膳食评价' not in page.get_text():continue
                    lines=[''.join(s['text'] for s in l['spans']).strip() for b in page.get_text('dict')['blocks'] for l in b.get('lines',[])]
                    self.assertFalse([s for s in lines if s.startswith(('%','）',')'))],lines)
                    self.assertFalse([s for s in lines if s.endswith(('（','('))],lines)
            wb=openpyxl.load_workbook(xlsx); ws=wb['运动员专项评价']
            for w in wb:
                for row in w:
                    for c in row:
                        if c.value=='不建议吃零食':self.assertEqual('000000' if w.title=='运动员专项评价' and c.column==4 else 'DC2626',c.font.color.rgb[-6:])
            self.assertLess(ws.column_dimensions['F'].width,30)
            self.assertGreater(ws.column_dimensions['A'].width,30)
            self.assertGreater(ws.column_dimensions['D'].width,30)
            self.assertGreater(ws.column_dimensions['E'].width,30)
            wb.close()
        self.assertEqual(before,report)

    def test_preview_has_column_sizing(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/'src/components/NutritionWorkspace.vue').read_text(encoding='utf8')
        css=(root/'src/style.css').read_text(encoding='utf8')
        self.assertIn('athlete-evaluation-table',ui)
        self.assertIn('<colgroup>',ui)
        self.assertIn('.athlete-evaluation-table',css)


if __name__=='__main__':unittest.main()
