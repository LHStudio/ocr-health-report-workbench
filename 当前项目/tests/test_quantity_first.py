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
        data=self.service.build_report_data(self.payload); rows=self.rows(data)
        for k in ['beans_energy','tubers_energy','grains_remainder']:
            self.assertEqual('不足',rows[k]['evaluation'],k)
            self.assertEqual(0, rows[k]['score'])
            self.assertEqual('personal_target', rows[k]['evaluation_basis'])
        for cat in ['谷类','豆类','薯类']:
            self.assertEqual('不足',data['category_result'][cat]['evaluation'],cat)
        suggestions='\n'.join(data['suggestions'])
        self.assertNotIn('先增加主食',suggestions)
        self.assertIn('蛋白质不足：',suggestions)
        self.assertEqual('不足', rows['livestock_remainder']['evaluation'])
        self.assertEqual('不足', rows['seafood']['evaluation'])
        self.assertNotIn('谷类能量占比偏高',suggestions)
        self.assertEqual('总能量过少。',data['suggestions'][0])
        self.assertNotIn('占比偏高',self.service.pdf_builder._interpretation(data))
        self.assertEqual(1,sum(s.startswith('肉类（含水产品）') for s in data['suggestions']))
        self.assertEqual(14, len(data['suggestions']))

    def test_meat_target_subtracts_planned_protein_not_recorded_food(self):
        data=self.service.build_report_data(self.payload); row=self.rows(data)['meat']
        plan=data['food_standard_evaluation']['personal_targets']
        want=plan['food_targets']['meat']['planning']
        self.assertAlmostEqual(want,row['target_grams'],places=4)
        self.assertEqual(20,row['actual'])
        self.assertAlmostEqual(row['target_min']-20,row['shortfall_grams'],places=4)
        self.assertEqual('',row['note'])
        self.assertIn('不扣除实际',next(r for r in data['food_standard_evaluation']['rows'] if r['key']=='meat')['note'])
        changed=self.service.build_report_data({**self.payload,'meals':[dict(name='米饭',amount=5000),dict(name='鲜奶',amount=3000)]})
        self.assertEqual(want,self.rows(changed)['meat']['target_grams'])
        self.assertGreater(want,0)

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
        self.assertEqual('-',rows['meat']['evaluation'])
        self.assertIsNone(rows['meat']['actual'])
        self.assertGreater(rows['meat']['target_grams'],0)

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
            'categoryEvaluations':{'谷类':'人工结论'},'standardEvaluations':{'grains_remainder':'人工结构','meat':'人工肉类'},'overallSuggestions':'人工建议'}})
        self.assertEqual('人工结构',data['category_result']['谷类']['evaluation'])
        self.assertEqual('人工结构',self.rows(data)['grains_remainder']['evaluation'])
        self.assertEqual('人工肉类',self.rows(data)['meat']['evaluation'])
        self.assertEqual(['人工建议'],data['suggestions'])

if __name__=='__main__': unittest.main()
