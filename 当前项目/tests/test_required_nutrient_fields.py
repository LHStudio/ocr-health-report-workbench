"""Unknown nutrient parameters must not be silently treated as zero intake."""
import copy
import unittest

from nutrition_report.adapter import build_payload_from_ocr_person
from nutrition_report.nutrition import NutritionService


class RequiredNutrientFieldsTest(unittest.TestCase):
    def setUp(self):
        self.service = NutritionService()
        self.user = dict(gender='female', age=22, weight=65, activityLevel='2',
                         athleteType='team', trainingPhase='training')
        self.payload = dict(user=self.user, meals=[dict(name='米饭', amount=100)])

    def test_each_missing_required_nutrient_blocks_full_assessment(self):
        for nutrient in ('energy', 'protein', 'carbohydrate', 'fat', 'calcium'):
            with self.subTest(nutrient=nutrient):
                db = copy.deepcopy(self.service.food_db)
                del db['米饭'][nutrient]
                report = NutritionService(food_db=db).build_report_data(self.payload)
                standard = report['food_standard_evaluation']
                self.assertFalse(standard['nutrient_record_complete'])
                self.assertEqual('needs_review', report['assessment_status'])
                self.assertEqual('-', report['nutrition']['energy']['evaluation'])
                self.assertTrue(all(r['evaluation'] == '-' for r in
                                    report['athlete_evaluation']['rows']
                                    if r['key'] in {'protein', 'carbohydrate', 'fat', 'calcium'}))
                self.assertIn({'food': '米饭', 'nutrient': nutrient},
                              standard['missing_nutrient_parameters'])
                self.assertTrue(any('米饭' in note and nutrient in note
                                    for note in standard['warnings']))

    def test_invalid_parameters_are_not_valid_zeros(self):
        for value in (None, '', '未知', -1, float('nan'), float('inf')):
            with self.subTest(value=value):
                db = copy.deepcopy(self.service.food_db)
                db['米饭']['carbohydrate'] = value
                result = NutritionService(food_db=db).build_report_data(self.payload)
                self.assertEqual('needs_review', result['assessment_status'])
                self.assertFalse(result['food_standard_evaluation']['nutrient_record_complete'])

    def test_explicit_finite_zero_parameters_remain_valid(self):
        db = copy.deepcopy(self.service.food_db)
        db['零营养测试饮料'] = dict(category='饮料', energy=0, protein=0,
                              carbohydrate=0, fat=0, calcium=0)
        report = NutritionService(food_db=db).build_report_data(
            dict(user=self.user, meals=[dict(name='零营养测试饮料', amount=100)]))
        self.assertTrue(report['food_standard_evaluation']['nutrient_record_complete'])
        self.assertEqual([], report['food_standard_evaluation']['missing_nutrient_parameters'])
        self.assertEqual('ready', report['assessment_status'])

    def test_missing_parameters_of_unconsumed_food_do_not_block_intake(self):
        db = copy.deepcopy(self.service.food_db)
        db['牛肉']['fat'] = None
        report = NutritionService(food_db=db).build_report_data(self.payload)
        self.assertTrue(report['food_standard_evaluation']['nutrient_record_complete'])
        self.assertEqual('ready', report['assessment_status'])

    def test_skipped_invalid_or_unknown_rows_do_not_add_missing_parameters(self):
        person = dict(general={'性别': '女', '年龄': '22', '体重': '65',
                               '运动类型': 'team', '运动量': '2', '训练阶段': 'training'},
                      food_rows=[{'食物名称': '米饭', '平均每次食用量': '100g',
                                  '次数': '1', '频率周期(请核对)': '每天'},
                                 {'食物名称': '虾', '平均每次食用量': '4只g',
                                  '次数': '1', '频率周期(请核对)': '每天'},
                                 {'食物名称': '未知食物', '平均每次食用量': '100g',
                                  '次数': '1', '频率周期(请核对)': '每天'}])
        db = copy.deepcopy(self.service.food_db)
        db['海白虾']['carbohydrate'] = None
        payload = build_payload_from_ocr_person(person).payload
        report = NutritionService(food_db=db).build_report_data(payload)
        self.assertTrue(report['food_standard_evaluation']['nutrient_record_complete'])
        self.assertEqual([], report['food_standard_evaluation']['missing_nutrient_parameters'])
        self.assertEqual('ready', report['assessment_status'])
        self.assertTrue(report['conversion_warnings'])


if __name__ == '__main__':
    unittest.main()
