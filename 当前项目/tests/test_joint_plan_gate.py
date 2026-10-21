import copy, unittest
from nutrition_report.nutrition import NutritionService

class JointPlanGateTests(unittest.TestCase):
 def setUp(self):
  self.service=NutritionService()
  self.payload={'user':{'name':'联合验证','gender':'female','age':21,'weight':60,'projectType':'篮球','athleteType':'team','trainingPhase':'training','bmrMin':1500,'bmrMax':1800},'meals':[{'name':'米饭','amount':278},{'name':'牛肉','amount':160},{'name':'鲜奶','amount':393}]}
 def test_all_constraints_pass_before_suggestions(self):
  d=self.service.build_report_data(self.payload);p=d['personal_targets']
  self.assertEqual('validated',p.get('status'))
  self.assertTrue(p['validation']['passed'])
  self.assertTrue(all(c['passed'] for c in p['validation']['checks']))
  self.assertGreaterEqual(p['planned_nutrients']['fat'],p['macro_targets']['fat']['min']-1e-6)
  self.assertGreaterEqual(p['planned_nutrients']['calcium'],1000-1e-6)
  self.assertEqual(17,len(d['suggestion_items']))
  for row in d['food_standard_evaluation']['rows']:
   if row['key'] in p['food_targets'] and row['key']!='quality_protein':
    self.assertEqual(p['food_targets'][row['key']]['planning'],row['joint_plan_amount'])
 def test_macro_energy_conflict_retains_failed_targets_but_not_output_veto(self):
  p=copy.deepcopy(self.payload);p['user'].update(projectType='篮球',athleteType='strength',bmrMin=900,bmrMax=1000,trainingPlan={'weeklyMinutes':0})
  d=self.service.build_report_data(p)
  self.assertEqual('blocked',d['personal_targets'].get('status'))
  self.assertEqual({},d['personal_targets']['food_targets'])
  self.assertTrue(d['suggestions'])
  self.assertEqual('ready',d['report_status'])
  self.assertEqual('ready',d['assessment_status'])
  self.assertEqual('requirements_energy_incompatible',d['personal_targets']['failure_code'])
 def test_bad_default_data_blocks_instead_of_fallback(self):
  self.service.food_db['米饭']['fat']=None
  d=self.service.build_report_data(self.payload)
  self.assertEqual('blocked',d['personal_targets'].get('status'))
  self.assertTrue(d['suggestions'])
 def test_targets_independent_of_actual_foods_and_no_oil(self):
  a=self.service.build_report_data(self.payload);p=copy.deepcopy(self.payload);p['meals']=[{'name':'米饭','amount':2000}];b=self.service.build_report_data(p)
  self.assertEqual(a['personal_targets'],b['personal_targets'])
  names={x['food'] for x in a['personal_targets']['contributions']}
  self.assertFalse(any('油' in x for x in names))
 def test_rounding_is_revalidated_and_portions_reconcile(self):
  d=self.service.build_report_data(self.payload);p=d['personal_targets']
  self.assertTrue(p['validation']['rounded_passed'])
  for nutrient in ['energy','protein','carbohydrate','fat','calcium']:
   self.assertAlmostEqual(sum(x[nutrient] for x in p['contributions']),p['planned_nutrients'][nutrient],places=7)
 def test_failed_plan_does_not_erase_manual_advice(self):
  p=copy.deepcopy(self.payload);p['user'].update(projectType='篮球',athleteType='strength',bmrMin=900,bmrMax=1000,trainingPlan={'weeklyMinutes':0})
  p.update(autoEvaluation=False,manualEvaluations={'overallSuggestions':'增加主食到2000克'})
  d=self.service.build_report_data(p)
  self.assertTrue(d['suggestions'])
  self.assertEqual(['增加主食到2000克'],d['suggestions'])
 def test_original_food_minimum_does_not_become_solver_point(self):
  p=copy.deepcopy(self.payload);p['meals']=[{'name':'蛋类','amount':100}]
  d=self.service.build_report_data(p);r=next(x for x in d['food_standard_evaluation']['rows'] if x['key']=='eggs')
  self.assertEqual(50,r['target_min']);self.assertIsNone(r['target_max']);self.assertEqual('适中',r['evaluation'])
  self.assertEqual(r['joint_plan_amount'],d['personal_targets']['food_targets']['eggs']['planning']);self.assertIsNone(r['target_max'])
 def test_manual_final_conclusion_matches_generated_advice(self):
  p=copy.deepcopy(self.payload);p['meals'].append({'name':'蛋类','amount':100});p.update(autoEvaluation=False,manualEvaluations={'standardEvaluations':{'eggs':'适中'}})
  d=self.service.build_report_data(p);text=next(x['text'] for x in d['suggestion_items'] if x['key']=='eggs')
  self.assertIn('适中',text);self.assertNotIn('评价不足',text)
 def test_eer_uses_existing_acceptance_band_not_exact_point(self):
  p=copy.deepcopy(self.payload);p['user'].pop('bmrMin');p['user'].pop('bmrMax');p['user'].update(weight=50,activityLevel='3')
  d=self.service.build_report_data(p);e=d['nutrition']['energy'];plan=d['personal_targets']
  self.assertEqual('validated',plan['status']);self.assertAlmostEqual(e['standard']*.9,plan['energy_reference']['min']);self.assertAlmostEqual(e['standard']*1.1,plan['energy_reference']['max'])
 def test_quality_protein_evaluation_remains_original_share_rule(self):
  p=copy.deepcopy(self.payload);p['meals']=[{'name':'米饭','amount':2700},{'name':'牛肉','amount':200},{'name':'鲜奶','amount':400},{'name':'蛋类','amount':100}]
  d=self.service.build_report_data(p);r=next(x for x in d['food_standard_evaluation']['rows'] if x['key']=='quality_protein')
  self.assertLess(r['actual'],50);self.assertEqual('不足',r['evaluation'])
if __name__=='__main__': unittest.main()
