import unittest, tempfile, re
from pathlib import Path
import fitz, openpyxl
from nutrition_report import NutritionReportService
from nutrition_report.builders.presentation import evaluation_rows, evaluation_warnings


class GramDisplayTest(unittest.TestCase):
    def setUp(self):
        self.service=NutritionReportService(prefer_cloud=False)
        self.payload={'user':{'name':'克数验证','age':22,'gender':'female','weight':65,'activityLevel':'2','athleteType':'team','trainingPhase':'training'},
            'meals':[{'name':'米饭','amount':1234.56789},{'name':'豆腐','amount':123.45678},{'name':'土豆','amount':234.56789},
                     {'name':'牛肉','amount':456.78901},{'name':'鲜奶','amount':456.78901},{'name':'蛋类','amount':56.78901}]}

    def test_percent_rules_project_to_grams_without_changing_internal_ratios(self):
        data=self.service.build_report_data(self.payload)
        rows={r['key']:r for r in evaluation_rows(data)}
        raw={r['key']:r for r in data['food_standard_evaluation']['rows']}
        for key in ['fat','beans_energy','tubers_energy','grains_remainder','seafood','quality_protein']:
            self.assertEqual('g/天',rows[key]['unit'],key)
            self.assertNotIn('%',rows[key]['target']+rows[key]['note'])
            self.assertNotIn('占比',rows[key]['label'])
        self.assertEqual('%',raw['beans_energy']['unit'])
        self.assertAlmostEqual(123.46,rows['beans_energy']['actual'])
        staple_energy=sum(f['nutrition']['energy'] for f in data['foods'] if f['category'] in {'谷类','豆类','薯类'})
        # Reference grams use the current category's weighted energy density, not weight shares.
        target=staple_energy*.05/(self.service.nutrition_service.food_db['豆腐']['energy']/100)
        self.assertEqual(f'≥ {target:.2f} g/天',rows['beans_energy']['target'])
        self.assertNotIn('%','\n'.join(evaluation_warnings(data)))
        protein=data['nutrition']['protein']
        self.assertEqual(f'≥ {protein*.5:.2f} g/天',rows['quality_protein']['target'])
        macro=protein*4+data['nutrition']['carbohydrate']*4+data['nutrition']['fat']*9
        self.assertEqual(f'{macro*.2/9:.2f}–{macro*.3/9:.2f} g/天',rows['fat']['target'])

    def test_pdf_excel_expose_only_grams_and_at_most_two_decimals(self):
        data=self.service.build_report_data(self.payload)
        with tempfile.TemporaryDirectory() as t:
            pdf=Path(t)/'report.pdf';xlsx=Path(t)/'report.xlsx'
            self.service.pdf_builder.build(data,pdf);self.service.excel_builder.build(data,xlsx)
            with fitz.open(pdf) as doc:
                page=next(p for p in doc if '运动员专项膳食评价' in p.get_text())
                text=page.get_text()
                self.assertNotIn('%',text)
                self.assertNotRegex(text,r'\d+\.\d{3,}')
            wb=openpyxl.load_workbook(xlsx,data_only=True)
            ws=wb['运动员专项评价']
            text='\n'.join(str(c.value or '') for row in ws for c in row)
            self.assertNotIn('%',text)
            self.assertNotRegex(text,r'\d+\.\d{3,}')
            wb.close()

if __name__=='__main__':unittest.main()
