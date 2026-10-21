import unittest, tempfile, re
from pathlib import Path
import fitz, openpyxl
from nutrition_report import NutritionReportService
from nutrition_report.builders.presentation import evaluation_rows, evaluation_warnings


class GramDisplayTest(unittest.TestCase):
    def setUp(self):
        self.service=NutritionReportService(prefer_cloud=False)
        self.payload={'user':{'name':'克数验证','age':22,'gender':'female','weight':65,'activityLevel':'3','athleteType':'team','trainingPhase':'training'},
            'meals':[{'name':'米饭','amount':1234.56789},{'name':'豆腐','amount':123.45678},{'name':'土豆','amount':234.56789},
                     {'name':'牛肉','amount':456.78901},{'name':'鲜奶','amount':456.78901},{'name':'蛋类','amount':56.78901}]}

    def test_personal_gram_targets_are_not_projected_from_recorded_denominators(self):
        data=self.service.build_report_data(self.payload)
        rows={r['key']:r for r in evaluation_rows(data)}
        raw={r['key']:r for r in data['food_standard_evaluation']['rows']}
        for key in ['beans_energy','tubers_energy','grains_remainder','seafood','quality_protein']:
            self.assertEqual('%',rows[key]['unit']);self.assertIn('%',rows[key]['target'])
            self.assertEqual(raw[key]['original_rule']['target_min'],rows[key]['target_min'])
        self.assertEqual('g/天',rows['fat']['unit'])
        energy=data['nutrition']['energy']['standard']
        self.assertEqual(f'{energy*.2/9:.2f}–{energy*.3/9:.2f} g/天',rows['fat']['target'])
        less=self.service.build_report_data({**self.payload,'meals':[dict(name='米饭',amount=10)]})
        small={r['key']:r for r in evaluation_rows(less)}
        for key in ('beans_energy','tubers_energy','grains_remainder','seafood','quality_protein','fat'):
            self.assertEqual(rows[key]['target'],small[key]['target'])

    def test_pdf_excel_expose_only_grams_and_at_most_two_decimals(self):
        data=self.service.build_report_data(self.payload)
        with tempfile.TemporaryDirectory() as t:
            pdf=Path(t)/'report.pdf';xlsx=Path(t)/'report.xlsx'
            self.service.pdf_builder.build(data,pdf);self.service.excel_builder.build(data,xlsx)
            with fitz.open(pdf) as doc:
                page=next(p for p in doc if '运动员专项膳食评价' in p.get_text())
                text=page.get_text()
                self.assertIn('%',text)
                self.assertNotRegex(text,r'\d+\.\d{3,}')
            wb=openpyxl.load_workbook(xlsx,data_only=True)
            ws=wb['运动员专项评价']
            text='\n'.join(str(c.value or '') for row in ws for c in row)
            self.assertIn('%',text)
            self.assertNotRegex(text,r'\d+\.\d{3,}')
            wb.close()

if __name__=='__main__':unittest.main()
