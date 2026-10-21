from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import fitz
import openpyxl
from nutrition_report import NutritionReportService
from nutrition_report.builders.pdf import NutritionPDFBuilder
from nutrition_report.builders.pdf_legacy import NutritionPDFBuilder as LegacyPDFBuilder


class PersonalReportChecksTest(unittest.TestCase):
    def setUp(self):
        self.service = NutritionReportService(prefer_cloud=False)
        self.payload = dict(user=dict(name='核查样例', gender='female', age=22,
            height=168, weight=65, activityLevel='2', athleteType='team', trainingPhase='training'),
            meals=[dict(name='米饭', amount=100), dict(name='牛肉', amount=20)])

    def test_original_seventeen_items_and_one_line_energy_for_all_energy_bands(self):
        from nutrition_report.report_checks import energy_summary
        for amount in [100,1400,10000]:
            data=self.service.build_report_data({**self.payload,'meals':[dict(name='米饭',amount=amount)]})
            self.assertTrue(data['suggestions']);self.assertEqual(17, len(data['suggestion_items']))
            self.assertEqual('available',data['recommendation_status'])
            state=data['nutrition']['energy']['evaluation']
            self.assertEqual({'适宜':'总能量适宜。','过多':'总能量过多。','过少':'总能量过少。'}[state],energy_summary(data))
            self.assertNotIn('应先控制主食总量',data['energy_guidance'])

    def test_extreme_intake_is_flagged_without_mutating_intake(self):
        payload = {**self.payload, 'meals':[dict(name='牛肉',amount=5000)]}
        original = deepcopy(payload)
        data = self.service.build_report_data(payload)
        self.assertEqual(original, payload)
        self.assertEqual(5000, data['foods'][0]['amount'])
        self.assertIn('extreme_intake', {x['code'] for x in data['report_checks']['checks']})
        warning = '\n'.join(data['report_checks']['warnings'])
        self.assertIn('核查', warning)
        self.assertNotIn('肯定是录入错误', warning)
        self.assertTrue(data['suggestions'])

    def test_manual_conflict_is_visible_and_manual_values_untouched(self):
        payload = {**self.payload, 'autoEvaluation':False, 'manualEvaluations':{
            'overallSuggestions':'应减少主食总量', 'interpretation':'人工解读保持',
            'proteinEvaluation':'过多'}}
        data = self.service.build_report_data(payload)
        self.assertEqual(['应减少主食总量'], data['suggestions'])
        self.assertEqual('人工解读保持', data['interpretation'])
        protein = next(r for r in data['athlete_evaluation']['rows'] if r['key']=='protein')
        self.assertEqual('过多', protein['evaluation'])
        self.assertIn('manual_conflict', {x['code'] for x in data['report_checks']['checks']})
        self.assertIn('人工', '\n'.join(data['report_checks']['warnings']))

    def test_alerts_visible_in_modern_legacy_pdf_and_excel_without_optional_quality_page(self):
        data = self.service.build_report_data({**self.payload,'meals':[dict(name='牛肉',amount=5000)]})
        with tempfile.TemporaryDirectory() as tmp:
            for style in ['modern','legacy']:
                path = Path(tmp)/f'{style}.pdf'
                self.service.pdf_builder.build({**data,'report_style':style},path)
                with fitz.open(path) as doc:
                    text=''.join(page.get_text() for page in doc)
                self.assertIn('自动核查提醒',text)
                self.assertIn('核查',text)
            path=Path(tmp)/'report.xlsx'
            self.service.excel_builder.build(data,path)
            wb=openpyxl.load_workbook(path, data_only=True)
            text=''.join(str(c.value or '') for ws in wb for row in ws for c in row)
            self.assertIn('核查',text)
            wb.close()

    def test_core_check_corrects_machine_contradiction_but_not_data(self):
        from nutrition_report.report_checks import check_report_consistency
        data=self.service.build_report_data(self.payload)
        data['suggestions']=['应减少主食总量']
        foods=deepcopy(data['foods'])
        check_report_consistency(data)
        self.assertNotIn('应减少主食总量',''.join(data['suggestions']))
        self.assertEqual(foods,data['foods'])
        self.assertTrue(data['report_checks']['corrections'])

    def test_zero_meat_target_and_nonfinite_values_have_explicit_review(self):
        from nutrition_report.report_checks import check_report_consistency
        data=self.service.build_report_data(self.payload)
        self.assertNotIn('meat',{r['key'] for r in data['food_standard_evaluation']['rows']})
        data['nutrition']['protein']=float('nan')
        check_report_consistency(data)
        codes={x['code'] for x in data['report_checks']['checks']}
        self.assertNotIn('zero_meat_target',codes)
        self.assertIn('invalid_numeric',codes)

    def test_bmr_is_preserved_and_incompatible_macro_energy_is_visible(self):
        payload={**self.payload,'user':{**self.payload['user'],'bmrMin':1200,'bmrMax':1400}}
        data=self.service.build_report_data(payload);e=data['nutrition']['energy']
        self.assertEqual([1200,1400],e['resting_bounds']);self.assertEqual('eer',e['reference_type'])
        self.assertEqual(2100,e['standard'])
        codes={x['code'] for x in data['report_checks']['checks']}
        self.assertNotIn('bmr_reference_scope',codes);self.assertIn('macro_energy_conflict',codes)

    def test_personal_target_machine_label_is_checked_against_numbers(self):
        from nutrition_report.report_checks import check_report_consistency
        data=self.service.build_report_data(self.payload)
        row=next(r for r in data['food_standard_evaluation']['rows'] if r['key']=='grains_remainder')
        row.update(actual=100,target_min=200,target_max=300,evaluation='过多',
            machine_evaluation='过多',evaluation_basis='personal_target')
        check_report_consistency(data)
        self.assertEqual('不足',row['evaluation'])
        self.assertIn('machine_evaluation_corrected',{x['code'] for x in data['report_checks']['checks']})

    def test_low_total_carb_with_excess_grain_uses_reallocation_not_reduction(self):
        data=self.service.build_report_data({**self.payload,'meals':[dict(name='米饭',amount=1400),dict(name='牛肉',amount=500)]})
        grain=next(r for r in data['food_standard_evaluation']['rows'] if r['key']=='grains_remainder')
        self.assertEqual('过多',grain['evaluation'])
        self.assertTrue(data['suggestions']);self.assertEqual('available',data['recommendation_status'])
        self.assertIn('staple_mix_reallocation',{x['code'] for x in data['report_checks']['checks']})

    def test_negative_manual_direction_does_not_trigger_false_conflict(self):
        data=self.service.build_report_data({**self.payload,'autoEvaluation':False,
            'manualEvaluations':{'overallSuggestions':'不应减少主食总量，应增加不足的豆类'}})
        self.assertNotIn('staples',{x['key'] for x in data['report_checks']['checks'] if x['code']=='manual_conflict'})

    def test_manual_energy_conflict_is_retained_and_warned(self):
        data=self.service.build_report_data({**self.payload,'autoEvaluation':False,
            'manualEvaluations':{'energyEvaluation':'适宜'}})
        self.assertEqual('适宜',data['nutrition']['energy']['evaluation'])
        self.assertTrue(data['suggestions'])
        self.assertIn('energy',{x['key'] for x in data['report_checks']['checks'] if x['code']=='manual_conflict'})

    def test_macro_machine_label_is_checked_and_float_epsilon_is_not_misclassified(self):
        from nutrition_report.report_checks import check_report_consistency
        data=self.service.build_report_data(self.payload)
        carb=next(r for r in data['athlete_evaluation']['rows'] if r['key']=='carbohydrate')
        carb.update(evaluation='过多',machine_evaluation='过多')
        grain=next(r for r in data['food_standard_evaluation']['rows'] if r['key']=='grains_remainder')
        grain.update(actual=200+1e-10,target_min=200,target_max=200,evaluation='适中',machine_evaluation='适中')
        check_report_consistency(data)
        self.assertEqual('不足',carb['evaluation'])
        self.assertEqual('适中',grain['evaluation'])

    def test_macro_comparison_uses_unrounded_totals_at_personal_boundary(self):
        service=self.service.nutrition_service
        service.food_db['精度样例']=dict(category='谷类',energy=2100,protein=97.5015,
            carbohydrate=455.007,fat=50,calcium=1000)
        data=service.build_report_data({**self.payload,'user':{**self.payload['user'],'weight':65.001},
            'meals':[dict(name='精度样例',amount=100)]})
        carb=next(r for r in data['athlete_evaluation']['rows'] if r['key']=='carbohydrate')
        self.assertEqual('适中',carb['evaluation'])
        self.assertAlmostEqual(455.007,carb['actual'],places=8)
        self.assertEqual(455.01,data['nutrition']['carbohydrate'])  # Legacy numeric-display contract retained.


if __name__ == '__main__': unittest.main()
