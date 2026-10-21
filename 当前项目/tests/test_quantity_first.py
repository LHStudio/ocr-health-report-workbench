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

    def test_personal_quantities_replace_energy_gate_in_all_presentations(self):
        data=self.service.build_report_data(self.payload);rows=self.rows(data)
        for k,status in [('beans_energy','不足'),('tubers_energy','不足'),('grains_remainder','过多')]:
            self.assertEqual(status,rows[k]['evaluation']);self.assertEqual('ratio',rows[k]['evaluation_basis'])
            self.assertEqual('%',rows[k]['unit'])
        self.assertEqual('过多',rows['livestock_remainder']['evaluation'])
        self.assertEqual('不足',rows['seafood']['evaluation'])
        self.assertEqual([],data['suggestions']);self.assertEqual('blocked',data['recommendation_status'])
        self.assertNotIn('meat',rows)

    def test_split_meat_targets_do_not_depend_on_recorded_grain_or_milk(self):
        data=self.service.build_report_data(self.payload)
        changed=self.service.build_report_data({**self.payload,'meals':[dict(name='米饭',amount=5000),dict(name='鲜奶',amount=3000)]})
        self.assertNotIn('meat',self.rows(data))
        for key in ('livestock_remainder','seafood'):
            row=self.rows(data)[key]
            self.assertEqual((None,70) if key=='livestock_remainder' else (30,None), (row['target_min'],row['target_max']))
            self.assertEqual(row['target'],self.rows(changed)[key]['target'])
            self.assertEqual('%',row['unit'])

    def test_every_energy_state_compares_fixed_personal_food_targets(self):
        # Rice provides enough carbohydrate/energy; beef supplies enough protein, no seafood.
        data=self.service.build_report_data({**self.payload,'meals':[dict(name='米饭',amount=1400),dict(name='牛肉',amount=500)]})
        rows=self.rows(data)
        self.assertEqual('过多',rows['grains_remainder']['evaluation'])
        self.assertEqual('不足',rows['beans_energy']['evaluation'])
        self.assertEqual('不足',rows['seafood']['evaluation'])
        self.assertNotEqual('不足',rows['quality_protein']['evaluation'])

    def test_incomplete_records_keep_requirements_but_do_not_invent_intake(self):
        data=self.service.build_report_data({**self.payload,'source_foods':[], 'conversion_warnings':[{'code':'unresolved_period','food':'米饭'}]})
        rows=self.rows(data)
        self.assertEqual('-',rows['grains_remainder']['evaluation'])
        self.assertEqual('-',rows['livestock_remainder']['evaluation'])
        self.assertIsNone(rows['livestock_remainder']['actual'])
        self.assertEqual(70,rows['livestock_remainder']['target_max'])

    def test_quality_page_default_off_and_explicit_opt_in_and_generation_date(self):
        for enabled in [False,True]:
            data=self.service.build_report_data({**self.payload,'include_quality_page':enabled})
            with tempfile.TemporaryDirectory() as temp:
                p=Path(temp)/'sample.pdf'; self.service.pdf_builder.build(data,p)
                with fitz.open(p) as doc:
                    text='\n'.join(page.get_text() for page in doc)
                    self.assertEqual(enabled,'OCR 换算与数据质量说明' in text)
                    pages=[page for page in doc if '整体评估及建议' in page.get_text()]
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
            'categoryEvaluations':{'谷类':'人工结论'},'standardEvaluations':{'grains_remainder':'人工结构','livestock_remainder':'人工畜禽肉'},'overallSuggestions':'人工建议'}})
        self.assertEqual('人工结构',data['category_result']['谷类']['evaluation'])
        self.assertEqual('人工结构',self.rows(data)['grains_remainder']['evaluation'])
        self.assertEqual('人工畜禽肉',self.rows(data)['livestock_remainder']['evaluation'])
        self.assertEqual(['人工建议'],data['withheld_manual_suggestions'])

if __name__=='__main__': unittest.main()
