import unittest,time,threading
from concurrent.futures import ThreadPoolExecutor
from nutrition_report.nutrition import NutritionService
from nutrition_report.cloud import fetch_cloud_foods
from nutrition_report.builders.pdf import NutritionPDFBuilder
from nutrition_report.builders.presentation import evaluation_rows

class LogicTest(unittest.TestCase):
 def report(self):
  db={n:dict(category=c,energy=e,protein=p,fat=f,carbohydrate=ca,calcium=0) for n,c,e,p,f,ca in [('谷','谷类',300,10,20,50),('豆','豆类',200,5,1,20),('薯','薯类',100,1,0,20),('奶','奶类',60,3,2,5),('蛋','蛋类',150,12,10,1),('肉','畜禽肉',200,20,10,0),('鱼','水产品',100,20,2,0),('果','水果',50,0,0,10),('坚果','坚果',600,10,40,20),('菜','蔬菜',20,1,0,2)]}
  amounts={'谷':300,'豆':5,'薯':5,'奶':100,'蛋':20,'肉':100,'鱼':10,'果':100,'坚果':1,'菜':400}
  payload={'user':{'name':'合成示例','weight':61.9,'age':25,'gender':'female','activityLevel':'2','athleteType':'strength','trainingPhase':'training'},'meals':[{'name':n,'amount':g} for n,g in amounts.items()]}
  return NutritionService(food_db=db).build_report_data(payload)
 def test_logic(self):
  r=self.report(); self.assertEqual('-',r['category_result']['谷类']['evaluation'])
  self.assertEqual('不足',next(x for x in r['athlete_evaluation']['rows'] if x['key']=='carbohydrate')['evaluation'])
  self.assertTrue(any('蛋白质不足：' in s for s in r['suggestions']))
  grain=next(x for x in evaluation_rows(r) if x['key']=='grains_remainder')
  self.assertEqual('-',grain['evaluation']); self.assertTrue(any('谷类缺少有效代表食物' in w for w in r['personal_targets']['plan_warnings']))
  self.assertEqual('',grain['note'])
  self.assertEqual('personal_target',next(x for x in r['food_standard_evaluation']['rows'] if x['key']=='grains_remainder')['evaluation_basis'])
  text=NutritionPDFBuilder._interpretation(r)
  self.assertNotIn('能量摄入不足，应增加碳水化合物摄入',text)
  self.assertNotIn('占比偏高',text)
  self.assertIn('按个人营养目标',text); self.assertNotIn('先补足主食总量',text)
  r['nutrition']['energy']['evaluation']='不足'
  r['athlete_evaluation']['rows']=[]
  self.assertNotIn('碳水化合物摄入不足',NutritionPDFBuilder._interpretation(r))
  r['interpretation']='人工解读保持原样';self.assertEqual('人工解读保持原样',NutritionPDFBuilder._interpretation(r))
 def test_global_interval_concurrent_batches(self):
  starts=[];ends=[]; lock=threading.Lock()
  def getter(url,**kw):
   with lock: starts.append(time.monotonic())
   time.sleep(.002)
   with lock: ends.append(time.monotonic())
   if url.endswith('category'): return {'records':[{'id':i,'name':'谷类'} for i in range(1,4)]}
   return {'records':[{'name':'谷'+str(kw['params']['categoryId']),'energy':300}]}
  with ThreadPoolExecutor(max_workers=2) as pool:
   list(pool.map(lambda _:fetch_cloud_foods(getter=getter,base_url='https://fixture.invalid'),range(2)))
  starts.sort();ends.sort()
  gaps=[b-a for a,b in zip(ends,starts[1:])]
  print('cloud request count=',len(starts),'finish-to-next-start gaps_ms=',[round(x*1000,3) for x in gaps])
  self.assertTrue(all(x>=.02 for x in gaps),gaps)
