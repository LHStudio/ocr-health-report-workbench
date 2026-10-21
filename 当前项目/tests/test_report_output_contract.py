import sys,json,copy,unittest
from pathlib import Path
from nutrition_report.gram_display import attach_gram_display
from nutrition_report.builders.presentation import evaluation_rows,evaluation_warnings
from nutrition_report.report_checks import _row_advice
from nutrition_report.builders.pdf import NutritionPDFBuilder
class DisplayContract(unittest.TestCase):
 def test_ratio_rows_show_recorded_grams_and_converted_targets_without_changing_rules(self):
  db={'米饭':{'category':'谷类','energy':100},'豆腐':{'category':'豆类','energy':200},'土豆':{'category':'薯类','energy':100},'牛肉':{'category':'畜禽肉','energy':150},'海白虾':{'category':'水产品','energy':80}}
  meals={'米饭':500,'豆腐':100,'土豆':200,'牛肉':300,'海白虾':100}
  specs=[('beans_energy','豆类占主食能量',22.2222,5,None),('tubers_energy','薯类占主食能量',22.2222,15,None),('grains_remainder','谷类占主食能量',55.5556,None,80),('seafood','水产品占肉类重量',25,30,None),('livestock_remainder','畜禽肉',75,None,70),('quality_protein','肉蛋奶优质蛋白占比',55,50,None)]
  rows=[dict(key=k,label=l,actual=a,unit='%',target='ratio %',target_min=lo,target_max=hi,gap=0,note='',evaluation='适中',score=1) for k,l,a,lo,hi in specs]
  r={'athlete_evaluation':{'rows':[]},'food_standard_evaluation':{'rows':rows}};before=copy.deepcopy(r)
  attach_gram_display(r,db,meals);shown={x['key']:x for x in evaluation_rows(r)}
  for k,label,actual,target in [('beans_energy','豆类',100,'≥ 22.50 g/天'),('tubers_energy','薯类',200,'≥ 135.00 g/天'),('grains_remainder','谷类',500,'≤ 720.00 g/天'),('seafood','水产品',100,'≥ 120.00 g/天'),('livestock_remainder','畜禽肉',300,'≤ 280.00 g/天')]:
   with self.subTest(key=k):self.assertEqual((label,actual,'g/天',target),(shown[k]['label'],shown[k]['actual'],shown[k]['unit'],shown[k]['target']))
  self.assertEqual('%',shown['quality_protein']['unit'])
  for old,new in zip(before['food_standard_evaluation']['rows'],r['food_standard_evaluation']['rows']):self.assertEqual(old,{k:v for k,v in new.items() if k!='display'})
 def test_minimum_rule_copy_removed_not_rephrased(self):
  r=dict(key='eggs',label='蛋类',actual=300,unit='g/天',target='≥ 50 g/天',target_min=50,target_max=None,evaluation='适中')
  self.assertEqual('蛋类适中：目前 300 g/天，参考目标 ≥ 50 g/天。',_row_advice(r))
 def test_interpretation_has_energy_conclusion_not_algorithm(self):
  r={'nutrition':{'energy':{'evaluation':'适宜'}},'energy_guidance':'old generated text'}
  self.assertEqual('总能量适宜。',NutritionPDFBuilder._interpretation(r))
 def test_check_reminders_not_repeated_in_evaluation_table(self):
  r={'report_checks':{'checks':[{'code':'extreme_intake','message':'数据核查提醒'}],'warnings':['数据核查提醒']}}
  self.assertEqual([],evaluation_warnings(r))
 def test_calcium_display_grams_does_not_change_raw_milligrams(self):
  row=dict(key='calcium',label='钙',actual=1200,unit='mg/天',target='≥ 1000 mg/天',target_min=1000,target_max=None,gap=0)
  r={'athlete_evaluation':{'rows':[row]},'food_standard_evaluation':{'rows':[]}}
  attach_gram_display(r,{},{});self.assertEqual(1200,row['actual']);self.assertEqual('mg/天',row['unit'])
  self.assertEqual((1.2,'g/天','≥ 1.00 g/天'),tuple(row['display'][k] for k in ('actual','unit','target')))
 def test_unknown_denominator_does_not_invent_a_gram_target(self):
  row=dict(key='seafood',label='水产品占肉类重量',actual=None,unit='%',target='≥ 30 %',target_min=30,target_max=None,gap=None)
  r={'athlete_evaluation':{'rows':[]},'food_standard_evaluation':{'rows':[row]}}
  attach_gram_display(r,{},{});self.assertIsNone(row['display']['actual']);self.assertIsNone(row['display']['gap']);self.assertEqual('—',row['display']['target'])
 def test_zero_recorded_food_uses_existing_api_density_for_display(self):
  row=dict(key='beans_energy',label='豆类占主食能量',actual=0,unit='%',target='≥ 5 %',target_min=5,target_max=None,gap=-5)
  r={'athlete_evaluation':{'rows':[]},'food_standard_evaluation':{'rows':[row]}}
  db={'米饭':{'category':'谷类','energy':100},'豆腐':{'category':'豆类','energy':200}}
  attach_gram_display(r,db,{'米饭':500});self.assertEqual(0,row['display']['actual']);self.assertEqual('≥ 12.50 g/天',row['display']['target']);self.assertEqual(-12.5,row['display']['gap'])
if __name__=='__main__':unittest.main(verbosity=2)
