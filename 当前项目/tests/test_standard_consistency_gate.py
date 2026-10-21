"""Regression cases for the user's six-stage, fail-closed report contract."""
import copy
import unittest

from nutrition_report.nutrition import NutritionService
from nutrition_report.food_standards import evaluate_food_standards
from nutrition_report.builders.presentation import evaluation_rows, evaluation_warnings, report_alerts
from nutrition_report.report_checks import check_report_consistency
from nutrition_report.release_gate import apply_release_gate, density_review


class StandardConsistencyGateTests(unittest.TestCase):
    def setUp(self):
        self.service = NutritionService()
        self.service.standards_policy={'status':'pending','pending':[{'key':'energy_scope','message':'合成待确认能量'},{'key':'fat_basis','message':'合成待确认脂肪'}]}
        self.payload = {'user': {'name': '标准一致性测试', 'gender': 'female',
            'age': 21, 'weight': 75.6, 'projectType': '篮球', 'athleteType': 'team',
            'trainingPhase': 'training', 'bmrMin': 1502, 'bmrMax': 1753},
            'meals': [{'name': '米饭', 'amount': 1400}, {'name': '豆腐', 'amount': 100},
                      {'name': '牛肉', 'amount': 200}, {'name': '海白虾', 'amount': 50}]}

    def test_six_original_ratio_rules_are_visible_and_not_replaced_by_grams(self):
        expected = {r['key']: r for r in evaluate_food_standards(
            self.payload, self.service.food_db, self.service.athlete_config)['rows']}
        report = self.service.build_report_data(self.payload)
        shown = {r['key']: r for r in evaluation_rows(report)}
        for key in ('grains_remainder', 'beans_energy', 'tubers_energy',
                    'livestock_remainder', 'seafood', 'quality_protein'):
            with self.subTest(key=key):
                self.assertEqual(expected[key]['unit'], shown[key]['unit'])
                self.assertAlmostEqual(expected[key]['actual'], shown[key]['actual'], places=2)
                self.assertNotIn('配餐', shown[key]['target'])
                self.assertEqual(expected[key]['target_min'], shown[key]['target_min'])
                self.assertEqual(expected[key]['target_max'], shown[key]['target_max'])

    def test_unconfirmed_standard_blocks_advice_and_exposes_decisions(self):
        original = copy.deepcopy(self.payload)
        report = self.service.build_report_data(self.payload)
        self.assertEqual('blocked', report['recommendation_status'])
        self.assertEqual('needs_review', report['report_status'])
        self.assertEqual([], report['suggestions'])
        self.assertEqual('review', report['report_checks']['status'])
        self.assertTrue(report.get('standards_review', {}).get('pending'))
        self.assertTrue(report_alerts(report))
        self.assertEqual(original, self.payload)

    def test_bmr_and_fat_cannot_keep_competing_final_grades_pending_review(self):
        report = self.service.build_report_data(self.payload)
        self.assertEqual('待确认', report['nutrition']['energy']['evaluation'])
        fat = next(r for r in evaluation_rows(report) if r['key'] == 'fat')
        self.assertEqual('待确认', fat['evaluation'])
        self.assertIn('待确认', fat['target'])
        self.assertNotIn('核验通过', report['joint_plan_summary'])

    def test_review_is_visible_even_when_all_explanatory_warnings_are_filtered(self):
        report = {'report_status': 'needs_review', 'recommendation_status': 'blocked',
                  'report_checks': {'status': 'review', 'warnings': ['篮球训练计划估算：测试']}}
        self.assertTrue(report_alerts(report))
        self.assertIn('未通过', '；'.join(report_alerts(report)))

    def test_blocked_evaluation_table_has_compact_notice_with_details_on_final_page(self):
        report = self.service.build_report_data(self.payload)
        self.assertEqual(1, len(evaluation_warnings(report)))
        self.assertIn('最后一页', evaluation_warnings(report)[0])
        self.assertGreater(len(report_alerts(report)), 1)

    def test_blocked_report_cannot_leak_advice_through_warnings_or_snack_row(self):
        report = self.service.build_report_data(self.payload)
        outward = '；'.join(report_alerts(report)) + '；'.join(
            str(r.get('evaluation','')) for r in evaluation_rows(report))
        for phrase in ('应补足', '应增加', '应减少'):
            self.assertNotIn(phrase, outward)
        self.assertEqual('不建议吃零食', report['category_result']['零食']['evaluation'])

    def test_eer_conflict_uses_same_upper_acceptance_boundary(self):
        # Minimum 2462 exceeds 2450 but NOT the existing accepted upper 2695.
        report = {'autoEvaluation': True, 'assessment_status': 'ready', 'foods': [],
            'nutrition': {'energy': {'value': 2527, 'standard': 2450,
                                    'reference_type': 'eer', 'evaluation': '适宜'}},
            'athlete_evaluation': {'rows': [dict(key=k, actual=v, target_min=v,
                target_max=v, evaluation='适中', machine_evaluation='适中')
                for k, v in [('protein', 87), ('carbohydrate', 406), ('fat', 490/9)]]},
            'food_standard_evaluation': {'rows': []}, 'suggestions': []}
        checks = check_report_consistency(report)
        self.assertNotIn('macro_energy_conflict', [r['code'] for r in checks['checks']])

    def test_report_and_solver_use_one_compatibility_number(self):
        self.payload['user'].update(athleteType='strength',
                                    bmrMin=900, bmrMax=1000,projectType='篮球',trainingPlan={'weeklyMinutes':0})
        report = self.service.build_report_data(self.payload)
        stage = next(x for x in report['personal_targets']['stages'] if x['stage']=='requirements_energy')
        check = next(x for x in report['report_checks']['checks'] if x['code']=='macro_energy_conflict')
        self.assertAlmostEqual(stage['macro_energy_min'], check['macro_minimum_kcal'])
        self.assertAlmostEqual(stage['energy_max'], check['energy_reference_upper'])

    def test_known_density_conflicts_block_instead_of_being_called_verified(self):
        self.service.food_db=copy.deepcopy(self.service.food_db)
        self.service.food_db['豆腐']['fat']=None
        report=self.service.build_report_data(self.payload)
        self.assertNotEqual('validated',report['personal_targets']['status'])
        self.assertIn('豆腐','；'.join(report['recommendation_issues']))
        self.assertEqual([],report['suggestions'])

    def test_small_macro_energy_difference_is_not_automatically_a_data_error(self):
        # Rounded energy 0 and protein 0.1 are not enough to assert bad data.
        db = {'合成舍入记录': dict(energy=0, protein=.1, carbohydrate=0, fat=0, calcium=0)}
        self.assertEqual([], density_review(db, db))

    def test_manual_suggestions_cannot_bypass_pending_standards(self):
        self.payload.update(autoEvaluation=False, manualEvaluations={
            'overallSuggestions': '按原人工记录增加主食', 'interpretation': '原人工解释'})
        report = self.service.build_report_data(self.payload)
        self.assertEqual([], report['suggestions'])
        self.assertEqual(['按原人工记录增加主食'], report['withheld_manual_suggestions'])
        self.assertNotIn('interpretation', report)

    def test_only_explicitly_confirmed_policy_can_open_release_gate(self):
        report = {'user': {}, 'autoEvaluation': True, 'assessment_status': 'ready',
            'assessment_issues': [], 'recommendation_issues': [], 'foods': [],
            'nutrition': {'energy': {}}, 'athlete_evaluation': {'rows': []},
            'food_standard_evaluation': {'rows': []},
            'personal_targets': {'status': 'validated', 'validation': {'passed': True}},
            'report_checks': {'checks': [], 'warnings': []}, 'suggestions': ['合成已验证建议']}
        pending = copy.deepcopy(report)
        apply_release_gate(pending, {'pending': []}, {})
        self.assertEqual('blocked', pending['recommendation_status'])
        self.assertEqual([], pending['suggestions'])
        approved = copy.deepcopy(report)
        apply_release_gate(approved, {'status': 'confirmed', 'pending': []}, {})
        self.assertEqual('validated', approved['recommendation_status'])
        self.assertEqual(['合成已验证建议'], approved['suggestions'])

    def test_blocking_check_overrides_numerical_plan_and_policy_approval(self):
        report = {'user': {}, 'autoEvaluation': True, 'assessment_status': 'ready',
            'assessment_issues': [], 'recommendation_issues': [], 'foods': [],
            'nutrition': {'energy': {}}, 'athlete_evaluation': {'rows': []},
            'food_standard_evaluation': {'rows': []},
            'personal_targets': {'status': 'validated', 'validation': {'passed': True}},
            'report_checks': {'checks': [{'code': 'test_conflict', 'severity': 'blocking',
                                         'message': '合成未解决冲突'}], 'warnings': []},
            'suggestions': ['不得输出']}
        apply_release_gate(report, {'status': 'confirmed', 'pending': []}, {})
        self.assertEqual('blocked', report['recommendation_status'])
        self.assertEqual([], report['suggestions'])


if __name__ == '__main__':
    unittest.main()
