import tempfile
import unittest
from pathlib import Path
import fitz
from nutrition_report import NutritionReportService
from nutrition_report.builders.presentation import evaluation_rows


class QuantityFirstTest(unittest.TestCase):
    def setUp(self):
        self.service=NutritionReportService(prefer_cloud=False)
        self.user=dict(name='验证样例',gender='female',age=22,weight=65,activityLevel='2',athleteType='team',trainingPhase='training')
        self.payload=dict(user=self.user,date='2020-01-01',meals=[dict(name='米饭',amount=100),dict(name='牛肉',amount=20),dict(name='鲜奶',amount=100),dict(name='蛋类',amount=20)])

    def rows(self,data):
        return {r['key']:r for r in evaluation_rows(data)}

    def test_deficit_precedes_ratios_in_all_presentations(self):
        data=self.service.build_report_data(self.payload); rows=self.rows(data)
        for k in ['beans_energy','tubers_energy','grains_remainder','quality_protein','seafood']:
            self.assertEqual('不足',rows[k]['evaluation'],k)
            self.assertIsNone(rows[k]['score'])
        for cat in ['谷类','豆类','薯类','奶类','蛋类','畜禽肉','水产品']:
            self.assertEqual('不足',data['category_result'][cat]['evaluation'],cat)
        suggestions='\n'.join(data['suggestions'])
        self.assertIn('增加主食',suggestions)
        self.assertIn('先补足蛋白质',suggestions)
        self.assertNotIn('占比偏高',suggestions)
        self.assertNotIn('适当减少',suggestions)
        self.assertNotIn('占比偏高',self.service.pdf_builder._interpretation(data))
        self.assertTrue(data['suggestions'][11].startswith('肉类（含水产品）'))

    def test_meat_target_subtracts_protein_not_food_weight(self):
        data=self.service.build_report_data(self.payload); row=self.rows(data)['meat']
        db=self.service.nutrition_service.food_db
        excluded=sum(db[f['name']]['protein']*f['amount']/100 for f in self.payload['meals'] if db[f['name']]['category'] in {'谷类','奶类','蛋类'})
        want=(65*1.5-excluded)/(db['牛肉']['protein']/100)
        self.assertAlmostEqual(want,row['target_grams'],places=4)
        self.assertEqual(20,row['actual'])
        self.assertAlmostEqual(want-20,row['shortfall_grams'],places=4)
        self.assertIn('谷类',row['note'])
        self.assertTrue(any('肉类' in s and '目前' in s and '参考目标' in s and '尚差' in s for s in data['suggestions']))

    def test_complete_adequate_intake_then_evaluates_structure(self):
        # Rice provides enough carbohydrate/energy; beef supplies enough protein, no seafood.
        data=self.service.build_report_data({**self.payload,'meals':[dict(name='米饭',amount=2000),dict(name='牛肉',amount=500)]})
        rows=self.rows(data)
        self.assertEqual('能量占比偏高',rows['grains_remainder']['evaluation'])
        self.assertEqual('能量占比偏低',rows['beans_energy']['evaluation'])
        self.assertEqual('占比偏低',rows['seafood']['evaluation'])
        self.assertNotEqual('不足',rows['quality_protein']['evaluation'])

    def test_incomplete_records_do_not_invent_deficits_or_meat_targets(self):
        data=self.service.build_report_data({**self.payload,'source_foods':[], 'conversion_warnings':[{'code':'unresolved_period','food':'米饭'}]})
        rows=self.rows(data)
        self.assertEqual('-',rows['grains_remainder']['evaluation'])
        self.assertEqual('-',rows['meat']['evaluation'])
        self.assertIsNone(rows['meat']['target_grams'])

    def test_quality_page_default_off_and_explicit_opt_in_and_generation_date(self):
        for enabled in [False,True]:
            data=self.service.build_report_data({**self.payload,'include_quality_page':enabled})
            with tempfile.TemporaryDirectory() as temp:
                p=Path(temp)/'sample.pdf'; self.service.pdf_builder.build(data,p)
                with fitz.open(p) as doc:
                    text='\n'.join(page.get_text() for page in doc)
                    self.assertEqual(enabled,'OCR 换算与数据质量说明' in text)
                    pages=[page for page in doc if '运动员专项膳食评价' in page.get_text()]
                    self.assertTrue(pages)
                    last=pages[-1]
                    matches=last.search_for('报告生成日期')
                    self.assertTrue(matches)
                    self.assertGreater(matches[0].x0,last.rect.width/2)
                    self.assertGreater(matches[0].y0,last.rect.height*0.8)
                    self.assertIn(data['generated_date'],last.get_text())
                    self.assertNotEqual('2020-01-01',data['generated_date'])
        data=self.service.build_report_data(self.payload)
        self.assertIs(data['include_quality_page'],False)

    def test_manual_final_values_are_preserved(self):
        data=self.service.build_report_data({**self.payload,'autoEvaluation':False,'manualEvaluations':{
            'categoryEvaluations':{'谷类':'人工结论'},'standardEvaluations':{'grains_remainder':'人工结构','meat':'人工肉类'},'overallSuggestions':'人工建议'}})
        self.assertEqual('人工结构',data['category_result']['谷类']['evaluation'])
        self.assertEqual('人工结构',self.rows(data)['grains_remainder']['evaluation'])
        self.assertEqual('人工肉类',self.rows(data)['meat']['evaluation'])
        self.assertEqual(['人工建议'],data['suggestions'])

if __name__=='__main__': unittest.main()
