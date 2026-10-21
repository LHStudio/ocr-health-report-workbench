"""Explicit user-authorized snack proxy; synthetic densities are test-only."""
import copy, unittest
from nutrition_report.adapter import build_payload_from_ocr_person, FOOD_REFERENCE_MAP
from nutrition_report.nutrition import NutritionService
from nutrition_report.release_gate import density_review

class ConfirmedSnackTests(unittest.TestCase):
    def person(self, name='零食'):
        return dict(general={'姓名':'合成零食测试','体重':60,'年龄':21,'性别':'女','运动量':'3','运动类型':'team','训练阶段':'training'},food_rows=[{'食物名称':name,'平均每次食用量':'100g','次数':'2','频率周期(请核对)':'每周'}])
    def test_proxy_preserves_record_and_counts_all_nutrients_once(self):
        person=self.person(); original=copy.deepcopy(person)
        a=build_payload_from_ocr_person(person)
        self.assertEqual([{'name':'薯条','amount':28.5714}],a.payload['meals'])
        self.assertEqual('薯条',a.payload['source_foods'][0]['reference_food'])
        self.assertFalse(a.payload['source_foods'][0]['reference_exact'])
        self.assertTrue(any(w['code']=='proxy_food_reference' for w in a.warnings))
        s=NutritionService();s.food_db['薯条']=dict(category='零食',energy=300,protein=3,carbohydrate=40,fat=14,calcium=10)
        r=s.build_report_data(a.payload)
        self.assertEqual(original,person)
        self.assertAlmostEqual(28.5714*3,r['nutrition']['energy']['value'],places=2)
        for key,value in [('protein',3),('carbohydrate',40),('fat',14)]:
            self.assertAlmostEqual(28.5714*value/100,r['nutrition']['exact_totals'][key])
        self.assertEqual('不建议吃零食',r['category_result']['零食']['evaluation'])
        self.assertEqual(1,len(r['foods']))
    def test_named_cake_keeps_exact_existing_proxy(self):
        self.assertEqual(('蛋糕',False),FOOD_REFERENCE_MAP['糕点'])
        self.assertEqual(('薯条',True),FOOD_REFERENCE_MAP['薯条'])
    def test_missing_fries_is_not_silently_replaced_by_cake(self):
        p=build_payload_from_ocr_person(self.person()).payload
        s=NutritionService();s.food_db.pop('薯条',None)
        r=s.build_report_data(p)
        self.assertEqual('needs_review',r['assessment_status']);self.assertEqual([],r['suggestions'])
        self.assertTrue(r['unmatched_foods']);self.assertFalse(r['foods'])
    def test_fries_review_does_not_invent_composition_rules_for_other_categories(self):
        # Synthetic API fixture: this task does not certify composition of other foods.
        db={'白酒':dict(category='酒类',energy=300,protein=0,carbohydrate=0,fat=0,calcium=0)}
        self.assertEqual([], density_review(db,['白酒']))

    def test_positive_energy_with_all_macros_zero_needs_review_without_rewriting(self):
        db={'薯条':dict(category='零食',energy=1289,protein=0,carbohydrate=0,fat=0,calcium=0)}
        original=copy.deepcopy(db)
        self.assertTrue(density_review(db,['薯条']))
        self.assertEqual(original,db)

if __name__=='__main__':unittest.main()
