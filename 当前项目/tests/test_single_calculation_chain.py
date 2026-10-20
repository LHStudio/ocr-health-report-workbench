import copy,json,tempfile,unittest
from pathlib import Path
import fitz
from nutrition_report.nutrition import NutritionService
from nutrition_report.builders.pdf import NutritionPDFBuilder
from nutrition_report.builders.excel import NutritionExcelBuilder
from nutrition_report.builders.presentation import evaluation_rows,evaluation_warnings

KEYS=['energy','protein','carbohydrate','fat','calcium','grains_remainder','beans_energy','tubers_energy','milk','eggs','livestock_remainder','seafood','fruit','vegetables','nuts','snacks','quality_protein']
class SingleCalculationChainTests(unittest.TestCase):
 def setUp(self):
  self.s=NutritionService(); self.p={'user':{'name':'链条验证','gender':'female','age':21,'weight':75.6,'projectType':'篮球','athleteType':'team','trainingPhase':'training','bmrMin':1502,'bmrMax':1753},'meals':[{'name':'米饭','amount':278},{'name':'牛肉','amount':160},{'name':'鲜奶','amount':393}]}
 def test_no_fabricated_menu_or_fat_shortfall(self):
  d=self.s.build_report_data(self.p);p=d['personal_targets']
  self.assertNotIn('unallocated_fat_g',p)
  self.assertIn('representatives',p)
  text=json.dumps(d,ensure_ascii=False)
  for phrase in ['示例食谱脂肪','烹调用油','脂肪缺口']:
   self.assertNotIn(phrase,text)
 def test_personal_macros_precede_and_do_not_depend_on_actual_food(self):
  a=self.s.build_report_data(self.p);p=copy.deepcopy(self.p);p['meals']=[{'name':'小麦面粉','amount':2000}];b=self.s.build_report_data(p)
  for k in ['protein','carbohydrate','fat']:
   x=next(x for x in a['athlete_evaluation']['rows'] if x['key']==k);y=next(x for x in b['athlete_evaluation']['rows'] if x['key']==k)
   self.assertEqual((x['target_min'],x['target_max']),(y['target_min'],y['target_max']))
  carb=next(x for x in a['athlete_evaluation']['rows'] if x['key']=='carbohydrate')
  self.assertAlmostEqual(75.6*7,carb['target_min'])
 def test_all_food_advice_is_separate_and_no_combined_meat(self):
  d=self.s.build_report_data(self.p)
  self.assertEqual(KEYS,[x['key'] for x in d['suggestion_items']])
  self.assertNotIn('meat',{x['key'] for x in evaluation_rows(d)})
  text='\n'.join(d['suggestions'])
  for x in ['按蛋白质估计','主食各类别','肉类（含水产品）','其中水产品','其中畜禽肉']:
   self.assertNotIn(x,text)
 def test_api_density_conversion_uses_same_nutrient_for_actual_and_target(self):
  d=self.s.build_report_data(self.p);r={x['key']:x for x in d['food_standard_evaluation']['rows']}
  for k in ['grains_remainder','beans_energy','tubers_energy','livestock_remainder','seafood']:
   row=r[k];rep=row['representative'];n='carbohydrate' if k in ['grains_remainder','beans_energy','tubers_energy'] else 'protein'
   self.assertEqual(n,row['conversion_basis'])
   self.assertAlmostEqual(row['actual']*self.s.food_db[rep][n]/100,row['actual_nutrient_g'])
   self.assertIn(rep,row['label'])
  self.assertEqual(278,r['grains_remainder']['recorded_actual_g'])
 def test_all_reference_food_contributions_add_back_to_personal_needs(self):
  d=self.s.build_report_data(self.p);p=d['personal_targets'];tot={n:0 for n in ['protein','carbohydrate']}
  for k in ['grains_remainder','beans_energy','tubers_energy','milk','eggs','vegetables','fruit','nuts','seafood','livestock_remainder']:
   f=p['food_targets'][k]
   for n in tot:tot[n]+=f['planning']*self.s.food_db[f['representative']][n]/100
  for n in tot:self.assertAlmostEqual(tot[n],p['planned_nutrients'][n],places=7)
  self.assertAlmostEqual(75.6*7,tot['carbohydrate'],places=7)
  self.assertTrue(75.6*1.5<=tot['protein']<=75.6*2)
 def test_conversion_corner_points_never_exceed_personal_macro_bounds(self):
  from nutrition_report.personal_targets import build_personal_targets
  d=self.s.build_report_data(self.p);a=copy.deepcopy(d['athlete_evaluation'])
  next(x for x in a['rows'] if x['key']=='carbohydrate')['target_max']=1058.4
  p=build_personal_targets(a,d['food_standard_evaluation'],self.s.food_db)
  for point in p['conversion_solutions']:
   self.assertLessEqual(point['protein'],75.6*2+1e-8)
   self.assertTrue(529.2-1e-8<=point['carbohydrate']<=1058.4+1e-8)
 def test_zero_default_density_never_mislabels_raw_grams_as_equivalent(self):
  self.s.food_db['豆腐']['carbohydrate']=0
  d=self.s.build_report_data(self.p);r=next(x for x in d['food_standard_evaluation']['rows'] if x['key']=='beans_energy')
  self.assertEqual('-',r['evaluation'])
  self.assertIsNone(r['target_min'])
  self.assertNotIn('豆腐等价量',r['label'])
 def test_category_summary_names_the_same_equivalent_used_by_detailed_evaluation(self):
  d=self.s.build_report_data(self.p)
  for row in d['food_standard_evaluation']['rows']:
   if row['key'] in ['grains_remainder','beans_energy','tubers_energy','livestock_remainder','seafood']:
    cat=self.s.food_db[row['representative']]['category'];e=d['category_result'][cat]['reference_equivalent']
    self.assertEqual(row['actual'],e['value']);self.assertEqual(row['representative'],e['representative'])
 def test_all_outputs_remove_requested_copy(self):
  d=self.s.build_report_data(self.p)
  with tempfile.TemporaryDirectory() as t:
   for style in ['modern','legacy']:
    p=Path(t)/(style+'.pdf');NutritionPDFBuilder().build({**d,'report_style':style},p)
    with fitz.open(p) as doc:text=''.join(x.get_text() for x in doc)
    for phrase in ['示例食谱','烹调用油','按蛋白质估计','肉类（含水产品）']:
     self.assertNotIn(phrase,text)
   import openpyxl
   p=Path(t)/'report.xlsx';NutritionExcelBuilder().build(d,p);w=openpyxl.load_workbook(p);text=''.join(str(c.value or '') for s in w for row in s for c in row);w.close()
   for phrase in ['示例食谱','烹调用油','按蛋白质估计','肉类（含水产品）']:self.assertNotIn(phrase,text)
if __name__=='__main__':unittest.main()
