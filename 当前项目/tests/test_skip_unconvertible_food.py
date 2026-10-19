import copy
import unittest
from nutrition_report.adapter import build_payload_from_ocr_person
from nutrition_report.nutrition import NutritionService


class SkipUnconvertibleFoodTest(unittest.TestCase):
    def setUp(self):
        self.service = NutritionService()
        self.person = {'general': {'性别': '女', '年龄': 25, '体重': 65, '项目种类': '女足', '运动量': '2', '训练阶段': 'training'},
                       'food_rows': [{'食物名称': '米饭', '平均每次食用量': '100g', '次数': '1', '频率周期(请核对)': '每天'},
                                     {'食物名称': '鲜奶', '平均每次食用量': '250ml', '次数': '2', '频率周期(请核对)': '每天'}]}
        self.payload = build_payload_from_ocr_person(self.person).payload
        self.clean = self.service.build_report_data(self.payload)

    def assert_same_valid_intake(self, report):
        self.assertTrue(report['food_standard_evaluation']['nutrient_record_complete'])
        self.assertEqual(self.clean['nutrition'], report['nutrition'])
        self.assertEqual(self.clean['food_standard_evaluation']['rows'], report['food_standard_evaluation']['rows'])
        self.assertNotIn('待核对', report['energy_guidance'])

    def test_ocr_invalid_units_and_unknown_food_preserve_valid_totals_and_source(self):
        for name, quantity in [('果汁饮料', '电解质'), ('米饭', '2碗'), ('虾', '4只g'), ('未知食物', '100g')]:
            with self.subTest(name=name, quantity=quantity):
                person = copy.deepcopy(self.person)
                person['food_rows'].append({'食物名称': name, '平均每次食用量': quantity, '次数': '1', '频率周期(请核对)': '每天'})
                before = copy.deepcopy(person)
                payload = build_payload_from_ocr_person(person).payload
                report = self.service.build_report_data(payload)
                self.assertEqual(before, person)
                self.assertTrue(any(w.get('food') == name for w in report['conversion_warnings']))
                self.assertEqual(2, len(report['foods']))
                self.assert_same_valid_intake(report)

    def test_direct_unknown_food_is_skipped_and_traced(self):
        payload = copy.deepcopy(self.payload)
        payload['meals'].append({'name': '未知食物', 'amount': 100})
        report = self.service.build_report_data(payload)
        self.assert_same_valid_intake(report)
        self.assertEqual('未知食物', report['unmatched_foods'][0]['name'])

    def test_manual_energy_evaluation_preserved(self):
        payload = copy.deepcopy(self.payload)
        payload.update(autoEvaluation=False, manualEvaluations={'energyEvaluation': '人工保留'})
        self.assertEqual('人工保留', self.service.build_report_data(payload)['nutrition']['energy']['evaluation'])

    def test_missing_nutrient_parameters_still_block(self):
        db = copy.deepcopy(self.service.food_db)
        del db['鲜奶']['protein']
        report = NutritionService(food_db=db).build_report_data(self.payload)
        self.assertFalse(report['food_standard_evaluation']['nutrient_record_complete'])


if __name__ == '__main__':
    unittest.main()
