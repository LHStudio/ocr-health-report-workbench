import unittest
from nutrition_report.nutrition import NutritionService
from nutrition_report.food_standards import evaluate_food_standards
from nutrition_report.adapter import build_payload_from_ocr_person, FOOD_REFERENCE_MAP


class FoodStandardsTest(unittest.TestCase):
    def setUp(self):
        # Every staple has 100 kcal/100g; meat/eggs/milk protein is 10g/100g.
        groups = {'谷': '谷类', '豆': '豆类', '薯': '薯类', '牛肉': '畜禽肉',
                  '鱼': '水产品', '奶': '奶类', '蛋': '蛋类', '果': '水果',
                  '菜': '蔬菜', '坚果': '坚果', '糕点': '零食', '鸡肉': '畜禽肉'}
        self.db = {name: dict(category=cat, energy=100, protein=10 if cat in
                   {'畜禽肉', '水产品', '奶类', '蛋类'} else 0, fat=0, carbohydrate=0, calcium=0)
                   for name, cat in groups.items()}
        self.service = NutritionService(food_db=self.db)
        self.amounts = {'谷': 800, '豆': 50, '薯': 150, '牛肉': 70, '鱼': 30,
                        '奶': 400, '蛋': 50, '果': 200, '菜': 500, '坚果': 10}

    def report(self, amounts=None, user=None):
        return self.service.build_report_data({'user': {'weight': 65, **(user or {})},
            'meals': [{'name': k, 'amount': v} for k, v in (amounts or self.amounts).items()]})

    def rows(self, **kw):
        # Test the internal mathematical rules independently of the new quantity gate.
        payload = {'user': {'weight':65, **(kw.get('user') or {})}, 'meals':[{'name':k,'amount':v} for k,v in (kw.get('amounts') or self.amounts).items()]}
        return {r['key']:r for r in evaluate_food_standards(payload,self.db,self.service.athlete_config)['rows']}

    def test_all_ten_numeric_rules_at_inclusive_boundaries(self):
        rows = self.rows()
        for key in ('nuts', 'beans_energy', 'tubers_energy', 'milk', 'eggs', 'seafood',
                    'fruit', 'vegetables', 'quality_protein', 'grains_remainder'):
            self.assertEqual(1, rows[key]['score'], key)
        self.assertEqual(5, rows['beans_energy']['actual'])
        self.assertEqual(15, rows['tubers_energy']['actual'])
        self.assertEqual(30, rows['seafood']['actual'])
        self.assertEqual(100,self.report()['food_standard_evaluation']['summary']['attainment_percent'])

    def test_energy_not_weight_and_protein_not_food_mass(self):
        self.db['豆']['energy'] = 200
        self.db['谷']['protein'] = 10
        service = NutritionService(food_db=self.db)
        report = service.build_report_data({'user': {'weight': 65}, 'meals': [
            {'name': k, 'amount': v} for k, v in self.amounts.items()]})
        self.assertIn('food_standard_evaluation', report)
        rows = {r['key']: r for r in report['food_standard_evaluation']['rows']}
        raw=self.rows()
        self.assertAlmostEqual(9.5238,raw['beans_energy']['actual'],places=3)
        self.assertAlmostEqual(40.7407,raw['quality_protein']['actual'],places=3)
        self.assertAlmostEqual(9.5238,rows['beans_energy']['actual'],places=3)
        self.assertAlmostEqual(40.7407,rows['quality_protein']['actual'],places=3)
        self.assertEqual(0,rows['quality_protein']['score'])
        self.assertEqual('不足',rows['quality_protein']['evaluation'])  # Missing personal profile, not invented ratio advice.

    def test_under_over_and_near_boundary_not_rounded_into_pass(self):
        rows = self.rows(amounts={**self.amounts, '坚果': 9.999, '果': 500.001, '菜': 199.999})
        self.assertEqual(1, rows['nuts']['score'])
        self.assertEqual('适中', rows['fruit']['evaluation'])
        self.assertEqual('严重不足', rows['vegetables']['evaluation'])

    def test_ten_percent_tolerance_preserves_food_targets(self):
        before=self.rows()
        for food,key,low,high in [('坚果','nuts',10,None),('奶','milk',400,None),
                                  ('蛋','eggs',50,None),('果','fruit',200,500),
                                  ('菜','vegetables',400,None)]:
            for value,expected in [(low*.9,'适中'),(low*.9-.01,'不足')]+(
                    [(high*1.1,'适中'),(high*1.1+.01,'偏多')] if high else []):
                with self.subTest(food=food,value=value):
                    row=self.rows(amounts={**self.amounts,food:value})[key]
                    self.assertEqual(expected,row['evaluation'])
                    self.assertEqual(1 if expected=='适中' else 0,row['score'])
                    for field in ['target','target_min','target_max']:
                        self.assertEqual(before[key][field],row[field])

    def test_ratio_tolerance_uses_relative_percent_not_percentage_points(self):
        for fish,expected in [(27,'适中'),(26.99,'不足')]:
            row=self.rows(amounts={**self.amounts,'鱼':fish,'牛肉':100-fish})['seafood']
            self.assertEqual(expected,row['evaluation'])
            self.assertEqual(30,row['target_min'])
        for beef,expected in [(77,'适中'),(77.01,'偏多')]:
            row=self.rows(amounts={**self.amounts,'牛肉':beef,'鱼':100-beef})['livestock_remainder']
            self.assertEqual(expected,row['evaluation'])
            self.assertEqual(70,row['target_max'])

    def test_completed_questionnaire_blanks_and_explicit_not_eaten_are_zero(self):
        for food_rows, want in (([], 0), ([{'食物名称': '坚果', '是否不吃': '是'}], 0)):
            payload = build_payload_from_ocr_person({'general': {'体重': 65}, 'food_rows': food_rows}).payload
            r = NutritionService().build_report_data(payload)
            self.assertIn('food_standard_evaluation', r)
            row = next(x for x in r['food_standard_evaluation']['rows'] if x['key'] == 'nuts')
            self.assertEqual(want, row['score'])
            self.assertIsNone(r['food_standard_evaluation']['summary']['attainment_percent'])

    def test_zero_denominators_stay_unscored_and_explicit_scale_is_preserved(self):
        rows = self.rows(amounts={'坚果': 10})
        for key in ('beans_energy', 'tubers_energy', 'seafood', 'quality_protein'):
            self.assertIsNone(rows[key]['score'])
        for weight in ('', 'NaN', 59):
            self.assertEqual(1,self.rows(user={'weight': weight})['nuts']['score'])
        self.assertEqual(1,self.rows(user={'weight': 80})['milk']['score'])
        self.assertEqual('≥ 480 g/天', self.rows(user={'weight': 80, 'foodTargetScale': 1.2})['milk']['target'])
        self.assertEqual(0, self.rows(user={'weight': 80, 'foodTargetScale': 1.2})['milk']['score'])

    def test_snacks_are_advisory_and_poultry_is_in_non_seafood_meat(self):
        rows = self.rows(amounts={**self.amounts, '糕点': 10, '鸡肉': 20})
        self.assertIsNone(rows['snacks']['score'])
        self.assertEqual('不建议吃零食', rows['snacks']['evaluation'])
        self.assertEqual('过多', rows['livestock_remainder']['evaluation'])
        self.assertEqual(75, rows['livestock_remainder']['actual'])
        self.assertIsNone(rows['livestock_remainder']['score'])

    def test_one_egg_is_50g_and_unlisted_foods_are_not_eaten(self):
        payload = build_payload_from_ocr_person({'general': {'体重': 65}, 'food_rows': [
            {'食物名称': '蛋类', '平均每次食用量': '1个', '次数': '1', '频率周期(请核对)': '每天'}]}).payload
        self.assertEqual(50, payload['meals'][0]['amount'])
        r = NutritionService().build_report_data(payload)
        self.assertIn('food_standard_evaluation', r)
        rows = {x['key']: x for x in r['food_standard_evaluation']['rows']}
        self.assertEqual(1, rows['eggs']['score'])
        self.assertEqual(1,rows['quality_protein']['score'])
        self.assertEqual('适中',rows['quality_protein']['evaluation'])
        payload['user'].update(athleteType='team', trainingPhase='training', age=20)
        report = NutritionService().build_report_data(payload)
        self.assertTrue(all('记录不完整' not in row['machine_evaluation'] for row in
                            report['athlete_evaluation']['rows'] if row['key'] != 'vegetables'))

    def test_manual_override_preserves_machine_score(self):
        payload = {'user': {'weight': 65}, 'meals': [{'name': '坚果', 'amount': 10}],
            'autoEvaluation': False, 'manualEvaluations': {'standardEvaluations': {'nuts': '已复核'}}}
        report = self.service.build_report_data(payload)
        self.assertIn('food_standard_evaluation', report)
        row = next(x for x in report['food_standard_evaluation']['rows'] if x['key'] == 'nuts')
        self.assertEqual('已复核', row['evaluation'])
        self.assertEqual('适中', row['machine_evaluation'])
        self.assertEqual(1, row['score'])

    def test_partial_manual_override_does_not_erase_machine_suggestions(self):
        report = self.service.build_report_data({'user': {'weight':65,'gender':'female','age':23,'activityLevel':'2'},
            'meals': [{'name': '坚果', 'amount': 5}], 'autoEvaluation': False,
            'manualEvaluations': {'standardEvaluations': {'nuts': '人工复核'}}})
        self.assertTrue(report['suggestions']); self.assertEqual('人工复核', next(r['evaluation'] for r in report['food_standard_evaluation']['rows'] if r['key']=='nuts'))

    def test_negative_and_nonfinite_ocr_quantity_not_silently_positive(self):
        for field, value in [('平均每次食用量', '-10g'), ('次数', '-1'), ('次数', 'NaN'), ('平均每次食用量', 'Infinity')]:
            row = {'食物名称': '坚果', '平均每次食用量': '10g', '次数': '1', '频率周期(请核对)': '每天', field: value}
            adapted = build_payload_from_ocr_person({'general': {'体重': 65}, 'food_rows': [row]})
            self.assertEqual([], adapted.payload['meals'])

    def test_quality_protein_exactly_50_and_seafood_below_30(self):
        self.db['谷']['protein'] = 6.875  # 800g grain gives 55g; animal sources also give 55g
        service = NutritionService(food_db=self.db)
        report = service.build_report_data({'user': {'weight': 65}, 'meals': [
            {'name': k, 'amount': v} for k, v in self.amounts.items()]})
        row = next(r for r in report['food_standard_evaluation']['rows'] if r['key'] == 'quality_protein')
        self.assertEqual(50,row['actual'])  # Outward value is grams of quality protein, not percent.
        self.assertEqual(1,row['score'])  # Personal profile is missing; original mathematical ratio retained below.
        self.assertEqual(1,self.rows()['quality_protein']['score'])
        self.assertEqual(0, self.rows(amounts={**self.amounts, '鱼': 29.999})['seafood']['score'])

    def test_vegetables_400_minimum_and_higher_project_rule(self):
        self.assertEqual(1, self.rows(amounts={**self.amounts, '菜': 399.99})['vegetables']['score'])
        self.assertEqual(1, self.rows(amounts={**self.amounts, '菜': 360})['vegetables']['score'])
        self.assertEqual(0, self.rows(amounts={**self.amounts, '菜': 359.99})['vegetables']['score'])
        self.assertEqual(1, self.rows(amounts={**self.amounts, '菜': 400})['vegetables']['score'])
        self.assertEqual('≥ 400 g/天', self.rows()['vegetables']['target'])
        self.service.athlete_config['types']['strength']['vegetables_g_min'] = 600
        rows = self.rows(user={'athleteType': 'strength'})
        self.assertEqual('≥ 600 g/天', rows['vegetables']['target'])
        self.assertEqual(0, rows['vegetables']['score'])
        self.assertEqual(1, self.rows(user={'projectType': '举重'}, amounts={**self.amounts, '菜': 600})['vegetables']['score'])

    def test_milk_powder_cheese_protein_equivalence_without_double_counting(self):
        service = NutritionService()
        report = service.build_report_data({'user': {'weight': 65}, 'meals': [
            {'name': '鲜奶', 'amount': 100}, {'name': '奶粉', 'amount': 30}, {'name': '奶酪', 'amount': 10}]})
        # 100 + 30*(22.4/3) + 10*(25.7/3) = 409.6667 g milk equivalent
        row = next(r for r in report['food_standard_evaluation']['rows'] if r['key'] == 'milk')
        self.assertAlmostEqual(409.6667, row['actual'], places=3)
        self.assertEqual(1, row['score'])
        self.assertIn('3 g/100g', row['note'])
        self.assertAlmostEqual(12.29, report['nutrition']['protein'], places=2)
        self.assertEqual(140, report['category_result']['奶类']['value'])

    def test_milk_equivalence_uses_current_reference_and_handles_missing_protein(self):
        db = {'鲜奶': dict(category='奶类', energy=50, protein=4, carbohydrate=0, fat=0, calcium=0),
              '奶粉': dict(category='奶类', energy=400, protein=20, carbohydrate=0, fat=0, calcium=0)}
        payload = {'user': {'weight': 65}, 'meals': [{'name': '奶粉', 'amount': 80}]}
        service = NutritionService(food_db=db)
        row = next(r for r in service.build_report_data(payload)['food_standard_evaluation']['rows'] if r['key'] == 'milk')
        self.assertEqual(400, row['actual'])
        db['鲜奶']['protein'] = 0
        row = next(r for r in service.build_report_data(payload)['food_standard_evaluation']['rows'] if r['key'] == 'milk')
        self.assertIsNone(row['score'])
