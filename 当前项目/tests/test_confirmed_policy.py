"""2026-10-21 user-confirmed energy, fat-only-overall and snack contract."""
import copy
import unittest

from nutrition_report.nutrition import NutritionService
from nutrition_report.builders.presentation import evaluation_rows
from nutrition_report.release_gate import density_review


class ConfirmedPolicyTests(unittest.TestCase):
    def setUp(self):
        self.service = NutritionService()
        self.payload = dict(user=dict(name='合成测试', gender='female', age=21,
            weight=60, projectType='篮球', athleteType='team', trainingPhase='training',
            activityLevel='3', bmrMin=1500, bmrMax=1800),
            meals=[dict(name='米饭', amount=300), dict(name='牛肉', amount=200)])

    def test_bare_bmr_falls_back_to_eer(self):
        self.payload['user']['projectType'] = '体操'
        e = self.service.build_report_data(self.payload)['nutrition']['energy']
        self.assertEqual('eer', e['reference_type'])
        self.assertEqual(self.service._lookup_energy_eer(self.payload['user']), e['standard'])
        self.assertEqual([1500, 1800], e['resting_bounds'])

    def test_combined_reference_and_fat_grams_have_one_source(self):
        d = self.service.build_report_data(self.payload)
        e = d['nutrition']['energy']
        f = next(r for r in d['athlete_evaluation']['rows'] if r['key']=='fat')
        self.assertEqual('bmr_plus_net', e['reference_type'])
        self.assertAlmostEqual(e['standard_min']*.2/9, f['target_min'])
        self.assertAlmostEqual(e['standard_max']*.3/9, f['target_max'])
        self.assertIn(f['evaluation'], ('适中','不足','过多'))
        self.assertNotIn('fat_basis', [x['key'] for x in d['standards_review']['pending']])
        self.assertNotIn('training_energy_estimate', d['publication_gate']['blocking_codes'])

    def test_fat_does_not_regrade_categories(self):
        before = self.service.build_report_data(self.payload)
        db = copy.deepcopy(self.service.food_db)
        db['米饭']['fat'] = 100
        after = NutritionService(food_db=db).build_report_data(self.payload)
        a = {r['key']:r for r in before['food_standard_evaluation']['rows']}
        for r in after['food_standard_evaluation']['rows']:
            for field in ('actual','target_min','target_max','evaluation','score'):
                self.assertEqual(a[r['key']][field], r[field], (r['key'],field))
        fat = lambda d: next(r['evaluation'] for r in d['athlete_evaluation']['rows'] if r['key']=='fat')
        self.assertNotEqual(fat(before), fat(after))

    def test_labels_and_unconditional_snack_rule(self):
        d = self.service.build_report_data(self.payload)
        shown = {r['key']: r for r in evaluation_rows(d)}
        for key in ('grains_remainder','beans_energy','tubers_energy'):
            self.assertIn(shown[key]['evaluation'], ('适中','不足','过多'))
        for cat in ('谷类','豆类','薯类'):
            self.assertIn(d['category_result'][cat]['evaluation'], ('适中','不足','过多'))
        self.assertEqual('不建议吃零食', shown['snacks']['evaluation'])
        self.assertEqual('不建议吃零食', d['category_result']['零食']['evaluation'])

    def test_user_owned_api_records_are_untouched_not_a_hardcoded_hold(self):
        original = copy.deepcopy(self.service.food_db)
        self.assertEqual([], density_review(self.service.food_db, ['豆腐','苹果汁']))
        self.service.build_report_data(self.payload)
        self.assertEqual(original, self.service.food_db)
        db = copy.deepcopy(original); db['豆腐']['fat'] = None
        self.assertTrue(density_review(db, ['豆腐']))

    def test_manual_text_is_output_verbatim_and_snack_is_fixed(self):
        self.payload.update(autoEvaluation=False, manualEvaluations=dict(
            overallSuggestions='增加主食', interpretation='原人工说明',
            standardEvaluations={'snacks':'建议吃零食'}))
        self.payload['user']['weight'] = 1000
        d = self.service.build_report_data(self.payload)
        self.assertTrue(d['suggestions'])
        self.assertEqual(['增加主食'], d['suggestions'])
        self.assertEqual('原人工说明', d['interpretation'])
        self.assertEqual('不建议吃零食', d['category_result']['零食']['evaluation'])

    def test_no_second_fat_percentage_constraint_or_fat_driven_allocation(self):
        d = self.service.build_report_data(self.payload)
        spec = d['personal_targets'].get('constraint_spec', [])
        self.assertTrue(spec)
        self.assertFalse(any('fat' in c['name'] for c in spec))
        self.assertFalse(any(c['name']=='macro_energy' for c in spec))
        self.assertTrue(any(c['name']=='fat' for c in d['personal_targets']['validation']['checks']))


if __name__=='__main__': unittest.main()
