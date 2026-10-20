"""Regression coverage for weight-independent food rules and consistent scoring gates."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import fitz
from nutrition_report import NutritionReportService
from nutrition_report.nutrition import NutritionService
from nutrition_report.food_standards import evaluate_food_standards


class ScoringAuditFollowupTest(unittest.TestCase):
    def setUp(self):
        self.service=NutritionReportService(prefer_cloud=False)
        self.user=dict(name='判分回归样例',gender='female',age=23,weight=57.8,
                       activityLevel='2',athleteType='team',trainingPhase='training')
        self.payload=dict(user=self.user,meals=[{'name':'米饭','amount':1400},{'name':'牛肉','amount':500}])

    def test_complete_57kg_intake_keeps_every_defined_food_evaluation(self):
        report=self.service.build_report_data(self.payload)
        rows={r['key']:r for r in report['food_standard_evaluation']['rows']}
        expected={'nuts':'不足','beans_energy':'不足','tubers_energy':'不足',
                  'grains_remainder':'过多','milk':'不足','eggs':'不足',
                  'seafood':'不足','fruit':'不足','vegetables':'不足'}
        for key,value in expected.items():
            self.assertEqual(value,rows[key]['evaluation'],key)
            self.assertIsNotNone(rows[key]['score'],key)
        self.assertNotEqual('-',rows['quality_protein']['evaluation'])

    def test_food_ratios_and_fixed_targets_do_not_disappear_at_weight_boundaries(self):
        db={'谷':dict(category='谷类',energy=100,protein=10,carbohydrate=0,fat=0,calcium=0),
            '豆':dict(category='豆类',energy=100,protein=10,carbohydrate=0,fat=0,calcium=0),
            '薯':dict(category='薯类',energy=100,protein=10,carbohydrate=0,fat=0,calcium=0),
            '坚果':dict(category='坚果',energy=100,protein=10,carbohydrate=0,fat=0,calcium=0)}
        meals=[dict(name=n,amount=q) for n,q in [('谷',800),('豆',50),('薯',150),('坚果',10)]]
        for weight in [None,57.8,59.999,60,70,70.001,80]:
            with self.subTest(weight=weight):
                rows={r['key']:r for r in evaluate_food_standards({'user':{'weight':weight},'meals':meals},db)['rows']}
                for key in ['nuts','beans_energy','tubers_energy','grains_remainder']:
                    self.assertEqual(1,rows[key]['score'],key)
        scaled={r['key']:r for r in evaluate_food_standards({'user':{'weight':80,'foodTargetScale':1.2},'meals':meals},db)['rows']}
        self.assertEqual(0,scaled['nuts']['score'])
        self.assertEqual(1,scaled['beans_energy']['score'])

    def test_energy_ten_percent_is_inclusive_and_invalid_values_are_not_scored(self):
        evaluate=self.service.nutrition_service._eval_energy_against_standard
        for value,want in [(1889.99,'过少'),(1890,'适宜'),(1995,'适宜'),(2100,'适宜'),
                           (2310,'适宜'),(2310.01,'过多'),(float('nan'),'-'),(float('inf'),'-'),(-1,'-')]:
            with self.subTest(value=value): self.assertEqual(want,evaluate(value,2100))
        for standard in [None,0,-1,float('nan'),float('inf')]:
            with self.subTest(standard=standard): self.assertEqual('-',evaluate(2100,standard))

    def test_energy_95_percent_does_not_trigger_deficit_when_carbohydrate_is_sufficient(self):
        db={'主食':dict(category='谷类',energy=1900,carbohydrate=500,protein=100,fat=0,calcium=1000),
            '坚果':dict(category='坚果',energy=0,carbohydrate=0,protein=0,fat=0,calcium=0)}
        service=NutritionService();service.food_db.update(db)
        report=service.build_report_data({'user':self.user,'meals':[{'name':'主食','amount':100}]})
        self.assertEqual('适宜',report['nutrition']['energy']['evaluation'])
        row=next(r for r in report['food_standard_evaluation']['rows'] if r['key']=='grains_remainder')
        self.assertEqual('personal_target',row['evaluation_basis'])
        self.assertEqual('过多',row['evaluation'])
        self.assertFalse(any('应先增加主食' in s for s in report['suggestions']))

    def test_energy_deficit_preserves_independent_milk_and_egg_scores(self):
        data=self.service.build_report_data({'user':{**self.user,'weight':65},'meals':[{'name':'鲜奶','amount':500},{'name':'蛋类','amount':50}]})
        rows={r['key']:r for r in data['food_standard_evaluation']['rows']}
        for key in ['milk','eggs']:
            self.assertEqual('适中',rows[key]['evaluation'])
            self.assertEqual(1,rows[key]['score'])
            self.assertEqual(0,rows[key]['gap'])

    def test_energy_deficit_preserves_independent_protein_reduction_advice(self):
        data=self.service.build_report_data({'user':self.user,'meals':[{'name':'牛肉','amount':1000}]})
        self.assertTrue(any(s.startswith('蛋白质过多') and '减少' in s for s in data['suggestions']))
        self.assertTrue(any(s.startswith('碳水化合物不足') and '增加' in s for s in data['suggestions']))
        self.assertEqual('过多',next(r for r in data['athlete_evaluation']['rows'] if r['key']=='protein')['evaluation'])

    def test_low_protein_advice_uses_requested_heading(self):
        data=self.service.build_report_data({'user':self.user,'meals':[{'name':'米饭','amount':100}]})
        self.assertTrue(any(s.startswith('蛋白质不足：') for s in data['suggestions']))
        self.assertFalse(any(s.startswith('先补足蛋白质：') for s in data['suggestions']))

    def test_manual_values_and_explicit_blanks_remain_authoritative(self):
        data=self.service.build_report_data({**self.payload,'autoEvaluation':False,'manualEvaluations':{
            'categoryEvaluations':{'谷类':''},'energyEvaluation':'人工能量结论',
            'standardEvaluations':{'nuts':'人工坚果结论'},'overallSuggestions':'人工建议原文'}})
        self.assertEqual('',data['category_result']['谷类']['evaluation'])
        self.assertEqual('人工能量结论',data['nutrition']['energy']['evaluation'])
        self.assertEqual(['人工建议原文'],data['suggestions'])
        self.assertEqual('人工坚果结论',next(r for r in data['food_standard_evaluation']['rows'] if r['key']=='nuts')['evaluation'])

    def test_incomplete_nonblank_record_and_zero_denominator_stay_unscored(self):
        data=self.service.build_report_data({**self.payload,'source_foods':[],
            'conversion_warnings':[{'code':'unresolved_period','food':'米饭'}]})
        self.assertEqual('-',data['nutrition']['energy']['evaluation'])
        row=next(r for r in data['food_standard_evaluation']['rows'] if r['key']=='grains_remainder')
        self.assertEqual('-',row['evaluation'])
        direct=evaluate_food_standards({'user':self.user,'meals':[]},self.service.nutrition_service.food_db)
        for row in direct['rows']:
            if row['key'] in ['beans_energy','tubers_energy','seafood','quality_protein']:
                self.assertIsNone(row['score'])

    def test_food_column_shrinks_and_both_other_columns_gain_equally_in_real_pdf(self):
        data=self.service.build_report_data(self.payload)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'audit.pdf'; self.service.pdf_builder.build(data,path)
            with fitz.open(path) as pdf:
                first=pdf[0]
                positions=[]
                header_y=first.search_for('每日摄入量')[0].y0
                for heading in ['种类','每日摄入量','评价']:
                    box=next(b for b in first.search_for(heading) if abs(b.y0-header_y)<1)
                    positions.append((box.x0+box.x1)/2)
                mm=72/25.4
                # Existing 57/72/45 mm -> 39/81/54 mm: each remaining column gains 9 mm.
                self.assertAlmostEqual(60*mm,positions[1]-positions[0],delta=1)
                self.assertAlmostEqual(67.5*mm,positions[2]-positions[1],delta=1)
                all_text=''.join(p.get_text() for p in pdf)
                self.assertNotIn('±10%',all_text)
                self.assertNotIn('90%',all_text)
                for page in pdf:
                    for block in page.get_text('dict')['blocks']:
                        for line in block.get('lines',[]):
                            for span in line['spans']:
                                self.assertGreaterEqual(span['bbox'][0],30)
                                self.assertLessEqual(span['bbox'][2],page.rect.width-30)

    def test_livestock_remainder_uses_complement_of_existing_seafood_minimum(self):
        data=self.service.build_report_data(self.payload)
        row=next(r for r in data['food_standard_evaluation']['rows'] if r['key']=='livestock_remainder')
        meat=data['personal_targets']['food_targets']['meat']
        self.assertEqual('过多',row['evaluation'])
        self.assertAlmostEqual(500,row['actual'])
        self.assertAlmostEqual(meat['max']*.7,row['target_max'])
        self.assertEqual(500,row['display']['actual'])
        self.assertEqual(f"{row['target_min']:.2f}–{row['target_max']:.2f} g/天",row['display']['target'])
        self.assertIsNone(row['score'])  # Complement is not an extra independent scoring item.

    def test_low_energy_label_is_red_and_interpreted_in_both_pdf_styles(self):
        from nutrition_report.builders.pdf_legacy import NutritionPDFBuilder as LegacyPDFBuilder
        data=self.service.build_report_data(self.payload)
        data['nutrition']['energy']['evaluation']='过少'
        for builder in [self.service.pdf_builder,LegacyPDFBuilder()]:
            with self.subTest(builder=type(builder).__module__):
                self.assertIn('总能量过少',builder._interpretation(data))
                with tempfile.TemporaryDirectory() as tmp:
                    path=Path(tmp)/'style.pdf'; builder.build(data,path)
                    with fitz.open(path) as pdf:
                        spans=[s for p in pdf for b in p.get_text('dict')['blocks'] for l in b.get('lines',[]) for s in l['spans'] if s['text'].strip()=='过少']
                        self.assertTrue(spans)
                        self.assertTrue(all(s['color']==0xDC2626 for s in spans))


if __name__=='__main__': unittest.main()
