"""Diagnostics remain truthful; user-requested report output is never vetoed."""
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

    def test_six_internal_ratio_rules_unchanged_with_gram_display(self):
        expected = {r['key']: r for r in evaluate_food_standards(
            self.payload, self.service.food_db, self.service.athlete_config)['rows']}
        report = self.service.build_report_data(self.payload)
        shown = {r['key']: r for r in evaluation_rows(report)}
        for key in ('grains_remainder', 'beans_energy', 'tubers_energy',
                    'livestock_remainder', 'seafood', 'quality_protein'):
            with self.subTest(key=key):
                raw=next(r for r in report['food_standard_evaluation']['rows'] if r['key']==key)
                self.assertEqual(expected[key]['unit'],raw['unit'])
                self.assertEqual(expected[key]['actual'],raw['actual'])
                self.assertEqual(expected[key]['score'],raw['score'])
                self.assertEqual('%' if key=='quality_protein' else 'g/天',shown[key]['unit'])
                self.assertNotIn('配餐', shown[key]['target'])
                self.assertEqual(expected[key]['target_min'], shown[key]['target_min'])
                self.assertEqual(expected[key]['target_max'], shown[key]['target_max'])

    def test_unconfirmed_standard_is_a_diagnostic_not_an_output_veto(self):
        original = copy.deepcopy(self.payload)
        report = self.service.build_report_data(self.payload)
        self.assertEqual('available',report['recommendation_status'])
        self.assertEqual('ready',report['report_status'])
        self.assertTrue(report['suggestions'])
        self.assertEqual('not_enforced', report['publication_gate']['status'])
        self.assertTrue(report.get('standards_review', {}).get('pending'))
        self.assertEqual([],report_alerts(report))
        self.assertTrue(report['report_checks']['checks'])
        self.assertEqual(original, self.payload)

    def test_pending_policy_does_not_regrade_energy_or_fat(self):
        report = self.service.build_report_data(self.payload)
        expected_service = NutritionService()
        expected = expected_service.build_report_data(copy.deepcopy(self.payload))
        self.assertEqual(expected['nutrition'], report['nutrition'])
        self.assertEqual(expected['athlete_evaluation']['rows'], report['athlete_evaluation']['rows'])
        self.assertNotIn('joint_plan_summary', report)

    def test_filtered_diagnostics_do_not_invent_blocking_copy(self):
        report = {'report_status': 'needs_review', 'recommendation_status': 'blocked',
                  'report_checks': {'status': 'review', 'warnings': ['篮球训练计划估算：测试']}}
        self.assertEqual([], report_alerts(report))

    def test_original_evaluation_table_has_no_added_veto_notice(self):
        report = self.service.build_report_data(self.payload)
        text = '\n'.join(evaluation_warnings(report) + report_alerts(report))
        self.assertNotIn('最终校验未通过', text)
        self.assertNotIn('不输出', text)
        self.assertEqual(17, len(report['suggestions']))

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
        self.assertTrue(report['suggestions'])

    def test_small_macro_energy_difference_is_not_automatically_a_data_error(self):
        # Rounded energy 0 and protein 0.1 are not enough to assert bad data.
        db = {'合成舍入记录': dict(energy=0, protein=.1, carbohydrate=0, fat=0, calcium=0)}
        self.assertEqual([], density_review(db, db))

    def test_pending_standards_preserve_manual_suggestions(self):
        self.payload.update(autoEvaluation=False, manualEvaluations={
            'overallSuggestions': '按原人工记录增加主食', 'interpretation': '原人工解释'})
        report = self.service.build_report_data(self.payload)
        self.assertTrue(report['suggestions'])
        self.assertEqual(['按原人工记录增加主食'], report['suggestions'])
        self.assertEqual('原人工解释', report['interpretation'])

    def test_policy_confirmation_does_not_gate_report_output(self):
        report = {'user': {}, 'autoEvaluation': True, 'assessment_status': 'ready',
            'assessment_issues': [], 'recommendation_issues': [], 'foods': [],
            'nutrition': {'energy': {}}, 'athlete_evaluation': {'rows': []},
            'food_standard_evaluation': {'rows': []},
            'personal_targets': {'status': 'validated', 'validation': {'passed': True}},
            'report_checks': {'checks': [], 'warnings': []}, 'suggestions': ['合成已验证建议']}
        pending = copy.deepcopy(report)
        apply_release_gate(pending, {'pending': []}, {})
        self.assertEqual('available',pending['recommendation_status'])
        self.assertTrue(pending['suggestions'])
        approved = copy.deepcopy(report)
        apply_release_gate(approved, {'status': 'confirmed', 'pending': []}, {})
        self.assertEqual('available', approved['recommendation_status'])
        self.assertEqual(['合成已验证建议'], approved['suggestions'])

    def test_diagnostic_does_not_erase_output_or_numerical_result(self):
        report = {'user': {}, 'autoEvaluation': True, 'assessment_status': 'ready',
            'assessment_issues': [], 'recommendation_issues': [], 'foods': [],
            'nutrition': {'energy': {}}, 'athlete_evaluation': {'rows': []},
            'food_standard_evaluation': {'rows': []},
            'personal_targets': {'status': 'validated', 'validation': {'passed': True}},
            'report_checks': {'checks': [{'code': 'test_conflict', 'severity': 'blocking',
                                         'message': '合成未解决冲突'}], 'warnings': []},
            'suggestions': ['不得输出']}
        apply_release_gate(report, {'status': 'confirmed', 'pending': []}, {})
        self.assertEqual('available',report['recommendation_status'])
        self.assertTrue(report['suggestions'])


if __name__ == '__main__':
    unittest.main()
