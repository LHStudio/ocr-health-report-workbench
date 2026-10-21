"""Energy is descriptive; every food compares intake to its personal target."""
import unittest
from copy import deepcopy
from nutrition_report.nutrition import NutritionService
from nutrition_report.builders.pdf import NutritionPDFBuilder
from nutrition_report.builders.pdf_legacy import NutritionPDFBuilder as LegacyPDFBuilder


class EnergyGateFollowupTest(unittest.TestCase):
    def report(self, energy=2222.75, **options):
        service=NutritionService()
        service.food_db['主食']=dict(category='谷类',energy=energy,protein=81.07,carbohydrate=376.43,fat=77.92,calcium=612.32)
        payload=dict(blank_food_policy='not_eaten',user=dict(gender='female',age=23,weight=54.6,activityLevel='2',athleteType='team',trainingPhase='training'),meals=[dict(name='主食',amount=100)])
        payload.update(options)
        original=deepcopy(payload)
        result=service.build_report_data(payload)
        self.assertEqual(original,payload)
        return result

    def test_adequate_energy_does_not_hide_slight_macro_shortfalls(self):
        r=self.report()
        self.assertEqual('适宜',r['nutrition']['energy']['evaluation'])
        self.assertEqual('不足',next(x for x in r['athlete_evaluation']['rows'] if x['key']=='carbohydrate')['evaluation'])
        self.assertEqual([],r['suggestions'])
        self.assertEqual('blocked',r['recommendation_status'])
        for builder in [NutritionPDFBuilder,LegacyPDFBuilder]:
            self.assertIn('未通过',builder._interpretation(r))

    def test_outside_band_staple_targets_do_not_follow_energy_direction(self):
        baseline=self.report()
        base={x['key']:x for x in baseline['food_standard_evaluation']['rows']}
        for energy in [1889.99,2310.01]:
            r=self.report(energy)
            for row in r['food_standard_evaluation']['rows']:
                if row['key'] not in {'beans_energy','tubers_energy','grains_remainder'}: continue
                self.assertEqual('ratio',row['evaluation_basis'])
                self.assertEqual(base[row['key']]['evaluation'],row['evaluation'])
                self.assertEqual(base[row['key']]['target_min'],row['target_min'])
                self.assertEqual(base[row['key']]['target_max'],row['target_max'])
                self.assertIsNotNone(row['gap'])
            self.assertNotIn('应先控制主食总量',''.join(r['suggestions']))

    def test_inclusive_energy_boundaries_do_not_select_a_food_branch(self):
        for energy in [1890,1995,2100,2310]:
            r=self.report(energy)
            self.assertEqual('适宜',r['nutrition']['energy']['evaluation'])
            self.assertEqual('ratio',next(x for x in r['food_standard_evaluation']['rows'] if x['key']=='grains_remainder')['evaluation_basis'])

    def test_missing_energy_profile_does_not_invent_a_staple_target(self):
        r=self.report(user=dict(gender='male',age=23,weight=54.6,athleteType='team',trainingPhase='training'))
        self.assertEqual('-',r['nutrition']['energy']['evaluation'])
        self.assertNotIn('先控制主食',''.join(r['suggestions']))
        self.assertNotIn('先补足主食',''.join(r['suggestions']))

    def test_skipped_records_do_not_block_valid_intake_and_manual_blanks_survive(self):
        r=self.report(conversion_warnings=[dict(code='unresolved_period',food='主食')],source_foods=[])
        self.assertTrue(r['food_standard_evaluation']['nutrient_record_complete'])
        self.assertEqual(self.report()['category_result'],r['category_result'])
        r=self.report(2500,autoEvaluation=False,manualEvaluations=dict(standardEvaluations=dict(grains_remainder=''),overallSuggestions='人工建议',interpretation='人工解读'))
        self.assertEqual('',r['category_result']['谷类']['evaluation'])
        self.assertEqual(['人工建议'],r['withheld_manual_suggestions'])
        self.assertEqual('人工解读', r['withheld_interpretation']); self.assertEqual([], r['suggestions'])

    def test_food_targets_are_grams_and_not_total_energy_instructions(self):
        for energy in [1800,2500]:
            r=self.report(energy)
            for row in r['food_standard_evaluation']['rows']:
                if row['key'] not in {'beans_energy','tubers_energy','grains_remainder'}: continue
                self.assertIn('%',row['display']['target'])
                self.assertNotIn('总量',row['display']['target'])
                self.assertEqual('%',row['display']['unit'])


if __name__=='__main__': unittest.main()
