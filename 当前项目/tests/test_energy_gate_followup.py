"""The total-energy band, not a macro point target, selects the food-evaluation branch."""
import unittest
from copy import deepcopy
from nutrition_report.nutrition import NutritionService
from nutrition_report.builders.pdf import NutritionPDFBuilder
from nutrition_report.builders.pdf_legacy import NutritionPDFBuilder as LegacyPDFBuilder


class EnergyGateFollowupTest(unittest.TestCase):
    def report(self, energy=2222.75, **options):
        db={'主食':dict(category='谷类',energy=energy,protein=81.07,carbohydrate=376.43,fat=77.92,calcium=612.32)}
        payload=dict(user=dict(gender='female',age=23,weight=54.6,activityLevel='2',athleteType='team',trainingPhase='training'),meals=[dict(name='主食',amount=100)])
        payload.update(options)
        original=deepcopy(payload)
        result=NutritionService(food_db=db).build_report_data(payload)
        self.assertEqual(original,payload)
        return result

    def test_adequate_energy_ignores_slight_macro_shortfalls_for_structure_gate(self):
        r=self.report(); rows={x['key']:x for x in r['food_standard_evaluation']['rows']}
        self.assertEqual('适宜',r['nutrition']['energy']['evaluation'])
        self.assertEqual('能量占比偏高',rows['grains_remainder']['evaluation'])
        self.assertEqual('ratio',rows['grains_remainder']['evaluation_basis'])
        self.assertNotIn('应先增加主食',''.join(r['suggestions']))
        self.assertNotIn('先补足蛋白质',''.join(r['suggestions']))
        for builder in [NutritionPDFBuilder,LegacyPDFBuilder]:
            self.assertNotIn('补充碳水来源',builder._interpretation(r))
            self.assertIn('保持',builder._interpretation(r))

    def test_outside_band_only_staple_groups_follow_energy_direction(self):
        for energy,status,basis in [(1889.99,'过少','energy_deficit'),(2310.01,'过多','energy_excess')]:
            with self.subTest(energy=energy):
                r=self.report(energy)
                for row in r['food_standard_evaluation']['rows']:
                    if row['key'] not in {'beans_energy','tubers_energy','grains_remainder'}: continue
                    self.assertEqual(status,row['evaluation'],row['key'])
                    self.assertEqual(basis,row['evaluation_basis'])
                    self.assertIsNone(row['score'])
                    self.assertIsNone(row['gap'])
                self.assertNotIn('谷类能量占比偏',''.join(r['suggestions']))
                self.assertGreater(r['food_standard_evaluation']['summary']['evaluated'],0)
                if status=='过多':
                    combined=''.join(r['suggestions'])+NutritionPDFBuilder._interpretation(r)
                    for wrong in ['应先增加主食','补充碳水']:
                        self.assertNotIn(wrong,combined)
                    self.assertIn('控制',combined)
                else:
                    self.assertIn('应先增加主食',''.join(r['suggestions']))

    def test_inclusive_band_boundaries_enter_structure_even_below_macro_target(self):
        for energy in [1890,1995,2100,2310]:
            r=self.report(energy)
            self.assertEqual('ratio',next(x for x in r['food_standard_evaluation']['rows'] if x['key']=='grains_remainder')['evaluation_basis'])

    def test_unknown_energy_never_invents_a_food_direction(self):
        r=self.report(user=dict(gender='male',age=23,weight=54.6,athleteType='team',trainingPhase='training'))
        self.assertEqual('-',r['nutrition']['energy']['evaluation'])
        for row in r['food_standard_evaluation']['rows']:
            if row['key'] in {'beans_energy','tubers_energy','grains_remainder'}: self.assertEqual('-',row['evaluation'])

    def test_incomplete_records_and_manual_blanks_remain_authoritative(self):
        r=self.report(conversion_warnings=[dict(code='unresolved_period',food='主食')],source_foods=[])
        self.assertEqual('-',r['category_result']['谷类']['evaluation'])
        r=self.report(2500,autoEvaluation=False,manualEvaluations=dict(standardEvaluations=dict(grains_remainder=''),overallSuggestions='人工建议',interpretation='人工解读'))
        self.assertEqual('',r['category_result']['谷类']['evaluation'])
        self.assertEqual(['人工建议'],r['suggestions'])
        self.assertEqual('人工解读',NutritionPDFBuilder._interpretation(r))

    def test_food_targets_do_not_present_ratio_reduction_during_total_deficit(self):
        for energy in [1800,2500]:
            r=self.report(energy)
            for row in r['food_standard_evaluation']['rows']:
                if row['key'] not in {'beans_energy','tubers_energy','grains_remainder'}: continue
                self.assertNotIn('%',row['display']['target'])
                self.assertIn('总量',row['display']['target'])


if __name__=='__main__': unittest.main()
