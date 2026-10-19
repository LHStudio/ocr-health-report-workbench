"""Only grains/beans/tubers inherit the total-energy direction."""
from copy import deepcopy
import unittest

from nutrition_report.nutrition import NutritionService
from nutrition_report.builders.presentation import evaluation_rows
from nutrition_report.builders.pdf import NutritionPDFBuilder
from nutrition_report.builders.pdf_legacy import NutritionPDFBuilder as LegacyPDFBuilder

STAPLES = {'grains_remainder', 'beans_energy', 'tubers_energy'}


class StapleScopeTest(unittest.TestCase):
    def report(self, energy=2100, **overrides):
        # Vary only the staple energy density, not food quantities or other nutrients.
        items = [('米饭', '谷类', 100), ('坚果', '坚果', 30), ('鲜奶', '奶类', 400),
                 ('鸡蛋', '蛋类', 60), ('鱼', '水产品', 100), ('牛肉', '畜禽肉', 100),
                 ('蔬菜', '蔬菜', 500), ('水果', '水果', 100)]
        db = {n: dict(category=c, energy=0, protein=5, carbohydrate=10, fat=2, calcium=20)
              for n, c, _ in items}
        db['米饭']['energy'] = energy
        payload = dict(user=dict(gender='female', age=23, weight=54.6, activityLevel='2',
                                 athleteType='team', trainingPhase='training'),
                       meals=[dict(name=n, amount=a) for n, _, a in items])
        payload.update(overrides)
        original = deepcopy(payload)
        result = NutritionService(food_db=db).build_report_data(payload)
        self.assertEqual(original, payload)
        return result

    def test_only_staples_change_when_crossing_energy_band(self):
        adequate = {r['key']: r for r in self.report()['food_standard_evaluation']['rows']}
        for energy, label in [(1800, '过少'), (2500, '过多')]:
            report = self.report(energy)
            for row in report['food_standard_evaluation']['rows']:
                with self.subTest(energy=energy, key=row['key']):
                    if row['key'] in STAPLES:
                        self.assertEqual(label, row['evaluation'])
                        self.assertIsNone(row['score'])
                        self.assertIsNone(row['gap'])
                    else:
                        self.assertEqual(adequate[row['key']], row)
            for category in ['奶类', '蛋类', '畜禽肉', '水产品', '坚果', '蔬菜', '水果']:
                self.assertEqual(self.report()['category_result'][category], report['category_result'][category])

    def test_nonstaple_targets_scores_and_advice_survive_excess_and_deficit(self):
        for energy in [1800, 2500]:
            report = self.report(energy)
            rows = {r['key']: r for r in evaluation_rows(report)}
            self.assertEqual('不足', rows['fruit']['evaluation'])
            self.assertEqual(0, rows['fruit']['score'])
            self.assertIn('g/天', rows['fruit']['target'])
            self.assertEqual('适中', rows['milk']['evaluation'])
            self.assertEqual(1, rows['milk']['score'])
            self.assertTrue(any('水果不足' in s for s in report['suggestions']))
            self.assertGreater(report['food_standard_evaluation']['summary']['evaluated'], 0)
            for builder in [NutritionPDFBuilder, LegacyPDFBuilder]:
                text = builder._interpretation(report)
                self.assertIn('主食', text)
                self.assertIn('其他食物', text)
                self.assertNotIn('暂不评价食物结构', text)

    def test_unknown_energy_does_not_hide_known_nonstaples(self):
        r = self.report(user=dict(gender='male', age=23, weight=54.6, athleteType='team', trainingPhase='training'))
        rows = {r['key']: r for r in r['food_standard_evaluation']['rows']}
        for key in STAPLES:
            self.assertEqual('-', rows[key]['evaluation'])
        self.assertEqual('适中', rows['milk']['evaluation'])
        self.assertEqual('不足', rows['fruit']['evaluation'])

    def test_all_three_staples_use_inclusive_energy_boundaries(self):
        for energy in [1890, 2100, 2310]:
            r = self.report(energy)
            for row in r['food_standard_evaluation']['rows']:
                if row['key'] in STAPLES:
                    self.assertEqual('ratio', row['evaluation_basis'])

    def test_manual_staple_and_nonstaple_values_and_blanks_survive(self):
        for energy in [1800, 2500]:
            r = self.report(energy, autoEvaluation=False, manualEvaluations=dict(
                standardEvaluations=dict(grains_remainder='', milk='人工奶量', fruit=''),
                overallSuggestions='人工建议', interpretation='人工解读'))
            rows = {r['key']: r for r in evaluation_rows(r)}
            self.assertEqual('', rows['grains_remainder']['evaluation'])
            self.assertEqual('人工奶量', rows['milk']['evaluation'])
            self.assertEqual('', rows['fruit']['evaluation'])
            self.assertEqual(['人工建议'], r['suggestions'])
            self.assertEqual('人工解读', NutritionPDFBuilder._interpretation(r))

    def test_unresolved_staple_does_not_erase_known_meat_projection(self):
        from nutrition_report import NutritionReportService
        from tests.test_nutrition_report import sample_person
        service = NutritionReportService(prefer_cloud=False)
        payload = service.adapt_ocr_person(sample_person()).payload
        r = service.build_report_data(payload)
        self.assertTrue(r['food_standard_evaluation']['nutrient_record_complete'])
        row = next(x for x in r['food_standard_evaluation']['rows'] if x['key'] == 'seafood')
        self.assertEqual('占比偏低', row['evaluation'])
        self.assertEqual(0, row['display']['actual'])
        self.assertIn('g/天', row['display']['target'])
        self.assertIsNotNone(row['display']['gap'])


if __name__ == '__main__':
    unittest.main()
