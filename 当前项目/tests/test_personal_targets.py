"""Personal requirements precede, and never depend on, recorded intake."""
import unittest

from nutrition_report.nutrition import NutritionService


class PersonalTargetsTest(unittest.TestCase):
    def setUp(self):
        self.service = NutritionService()
        self.user = dict(gender='female', age=22, height=170, weight=65,
                         activityLevel='2', athleteType='team', trainingPhase='training')

    def report(self, meals, **user):
        return self.service.build_report_data(dict(user={**self.user, **user}, meals=meals))

    @staticmethod
    def rows(report):
        return {r['key']: r for r in report['food_standard_evaluation']['rows']}

    def test_fixed_targets_do_not_follow_actual_intake_or_food_mix(self):
        a = self.report([dict(name='米饭', amount=100), dict(name='牛肉', amount=20)])
        b = self.report([dict(name='小麦面粉', amount=3000), dict(name='鲜奶', amount=4000),
                         dict(name='蛋类', amount=1000), dict(name='牛肉', amount=100)])
        for key in ('beans_energy', 'tubers_energy', 'grains_remainder',
                    'seafood', 'livestock_remainder', 'quality_protein'):
            for field in ('target_min', 'target_max'):
                self.assertEqual(self.rows(a)[key].get(field), self.rows(b)[key].get(field), (key, field))
                if field == 'target_min':
                    self.assertIsNotNone(self.rows(a)[key].get(field), (key, field))
        self.assertGreater(self.rows(b)['livestock_remainder']['target_min'], 0)

    def test_energy_excess_never_forces_staple_reduction_when_carb_is_low(self):
        report = self.report([dict(name='牛肉', amount=2400), dict(name='米饭', amount=100)])
        self.assertEqual('excess', report['food_standard_evaluation']['energy_gate'])
        carb = next(r for r in report['athlete_evaluation']['rows'] if r['key'] == 'carbohydrate')
        self.assertEqual('不足', carb['evaluation'])
        self.assertEqual('不足', self.rows(report)['grains_remainder']['evaluation'])
        self.assertEqual('personal_target', self.rows(report)['grains_remainder']['evaluation_basis'])

    def test_fat_grams_come_from_personal_energy_not_recorded_macro_energy(self):
        for meals in ([], [dict(name='牛肉', amount=3000)]):
            report = self.report(meals)
            row = next(r for r in report['athlete_evaluation']['rows'] if r['key'] == 'fat')
            self.assertEqual('g/天', row['unit'])
            self.assertAlmostEqual(report['nutrition']['energy']['standard'] * .2 / 9, row['target_min'])
            self.assertAlmostEqual(report['nutrition']['energy']['standard'] * .3 / 9, row['target_max'])

    def test_planned_foods_reconcile_personal_carbohydrate_and_protein(self):
        report = self.report([])
        plan = report['food_standard_evaluation']['personal_targets']
        for key in ('protein', 'carbohydrate'):
            value = plan['protein_conversion']['value'] if key == 'protein' else plan['macro_targets'][key]['planning']
            self.assertAlmostEqual(value, plan['planned_nutrients'][key], places=7)
        self.assertGreater(plan['food_targets']['meat']['planning'], 0)
        self.assertTrue(plan['assumptions'])

    def test_bmr_interval_is_used_without_midpoint_or_intake_substitution(self):
        report = self.report([], bmrMin=1800, bmrMax=2300)
        row = next(r for r in report['athlete_evaluation']['rows'] if r['key'] == 'fat')
        self.assertAlmostEqual(1800 * .2 / 9, row['target_min'])
        self.assertAlmostEqual(2300 * .3 / 9, row['target_max'])

    def test_reference_conversion_is_not_a_second_actual_fat_evaluation(self):
        report = self.report([])
        plan = report['food_standard_evaluation']['personal_targets']
        self.assertNotIn('unallocated_fat_g', plan)
        self.assertNotIn('constraints_satisfied', plan)
        self.assertNotIn('脂肪缺口', '\n'.join(plan['plan_warnings']))
        self.assertTrue(plan['protein_conversion']['within_personal_range'])
        self.assertAlmostEqual(65*1.7, plan['macro_targets']['protein']['planning'])

    def test_exact_planning_amount_is_not_rounded_into_a_failed_boundary(self):
        plan = self.report([])['food_standard_evaluation']['personal_targets']
        foods = plan['food_targets']
        meals = []
        for key in ('grains_remainder','beans_energy','tubers_energy','milk','eggs','vegetables','fruit','nuts','seafood','livestock_remainder'):
            meals.append(dict(name=foods[key]['representative'], amount=foods[key]['planning']))
        rows = self.rows(self.report(meals))
        for key in ('grains_remainder','beans_energy','tubers_energy','seafood','livestock_remainder'):
            self.assertEqual('适中', rows[key]['evaluation'], key)

    def test_athlete_actual_is_not_rounded_before_boundary_comparison(self):
        from nutrition_report.athlete import evaluate_athlete
        nutrition = dict(protein=100, carbohydrate=455.007, fat=50,
                         energy=dict(standard=2100), calcium=dict(value=1000))
        athlete, _ = evaluate_athlete({**self.user,'weight':65.001}, nutrition, {}, self.service.athlete_config)
        row = next(r for r in athlete['rows'] if r['key']=='carbohydrate')
        self.assertEqual(455.007, row['actual'])
        self.assertEqual('适中', row['evaluation'])


if __name__ == '__main__':
    unittest.main()
