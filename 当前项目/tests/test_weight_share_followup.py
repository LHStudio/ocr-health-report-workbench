import copy,json,tempfile,unittest
from pathlib import Path
import fitz,openpyxl
from nutrition_report import NutritionReportService
from nutrition_report.food_standards import evaluate_food_standards
from nutrition_report.food_conversion import normalize_meals,staple_equivalents
from nutrition_report.builders.presentation import evaluation_rows

class WeightShareTest(unittest.TestCase):
    def setUp(self):
        self.service=NutritionReportService(prefer_cloud=False)
        self.db=self.service.nutrition_service.food_db
        self.payload={'user':{'name':'验证','age':22,'gender':'female','weight':60,'projectType':'篮球','athleteType':'team','trainingPhase':'training','bmrMin':1500,'bmrMax':1800},
            'meals':[{'name':n,'amount':g} for n,g in [('米饭',200),('馒头',150),('豆腐',52),('豆腐丝/千张/豆腐干',19),('豆浆',146),('土豆',150)]],
            'body_composition':{'values':{'height':164,'ffm':45.5}}}

    def rules(self,payload,db=None):
        return {r['key']:r for r in evaluate_food_standards(normalize_meals(payload),db or self.db)['rows']}

    def test_weight_denominator_and_calorie_density_independence(self):
        rows=self.rules(self.payload)
        for key,value in [('grains_remainder',200),('tubers_energy',150),('beans_energy',30)]:
            self.assertAlmostEqual(value/380*100,rows[key]['actual'],places=4)
            self.assertEqual('equivalent_weight',rows[key]['ratio_basis'])
            self.assertEqual(380,rows[key]['denominator_g'])
        changed=copy.deepcopy(self.db)
        changed['豆腐']['energy']*=10
        again=self.rules(self.payload,changed)
        for key in ('grains_remainder','tubers_energy','beans_energy'):
            self.assertEqual(rows[key]['actual'],again[key]['actual'])

    def test_normalization_once_and_missing_conversion_not_zero(self):
        p=normalize_meals(self.payload)
        self.assertEqual({'谷类':200,'薯类':150,'豆类':30},staple_equivalents(p,self.db))
        self.assertEqual(staple_equivalents(p,self.db),staple_equivalents(normalize_meals(p),self.db))
        db={**self.db,'未知豆制品':{'category':'豆类','energy':100,'protein':5,'fat':0,'carbohydrate':10,'calcium':0}}
        rows=self.rules({'meals':[{'name':'未知豆制品','amount':100}]},db)
        self.assertIsNone(rows['beans_energy']['actual'])
        self.assertIsNone(rows['grains_remainder']['actual'])
        self.assertIsNone(self.rules({'meals':[]})['beans_energy']['actual'])

    def test_exact_thresholds_and_severe_deficit(self):
        p={'meals':[{'name':'小麦面粉','amount':800},{'name':'大豆','amount':50},{'name':'土豆','amount':150}]}
        db={**self.db,'大豆':{'category':'豆类','energy':300,'protein':20,'fat':10,'carbohydrate':20,'calcium':100}}
        rows=self.rules(p,db)
        for key in ('grains_remainder','tubers_energy','beans_energy'):
            self.assertEqual('适中',rows[key]['evaluation'])
        p['meals'][0]['amount']=825;p['meals'][1]['amount']=25
        rows=self.rules(p,db)
        self.assertEqual('严重不足',rows['beans_energy']['evaluation'])
        self.assertEqual('适中',rows['grains_remainder']['evaluation'])

    def test_joint_planner_uses_the_same_equivalent_weight_coefficients(self):
        from nutrition_report.joint_plan import KEYS
        data=self.service.build_report_data(self.payload)
        constraints={r['name']:r for r in data['personal_targets']['constraint_spec']}
        weights={'grains_remainder':.5,'tubers_energy':1,'beans_energy':1/5.2}
        for key,share,side in [('grains_remainder',.8,'max'),('tubers_energy',.15,'min'),('beans_energy',.05,'min')]:
            expected=[(weights.get(k,0) if k==key else 0)-share*weights.get(k,0) for k in KEYS]
            self.assertEqual(expected,constraints[key+'_share_'+side]['coefficients'])

    def test_pdf_excel_order_colors_and_body_two_columns(self):
        data=self.service.build_report_data(self.payload)
        rows={r['key']:r for r in data['food_standard_evaluation']['rows']}
        for key,status in [('grains_remainder','偏多'),('tubers_energy','不足'),('beans_energy','严重不足')]:
            rows[key]['evaluation']=status
        keys=[r['key'] for r in evaluation_rows(data)]
        self.assertLess(keys.index('grains_remainder'),keys.index('tubers_energy'))
        self.assertLess(keys.index('tubers_energy'),keys.index('beans_energy'))
        self.assertEqual('按照运动情况适量补充饮料',data['category_result']['饮料']['evaluation'])
        with tempfile.TemporaryDirectory() as tmp:
            for style in ('modern','legacy'):
                pdf=Path(tmp)/(style+'.pdf')
                self.service.pdf_builder.build(dict(data,report_style=style),pdf)
                with fitz.open(pdf) as doc:
                    first=doc[0].get_text()
                    self.assertNotIn('单位',first)
                    self.assertIn('164 cm',first)
                    spans=[s for b in doc[0].get_text('dict')['blocks'] for l in b.get('lines',[]) for s in l['spans']]
                    title=next(s for s in spans if s['text']=='营养健康评估报告')
                    body=next(s for s in spans if s['text']=='体成分结果')
                    self.assertEqual((title['font'],title['size'],title['color']),(body['font'],body['size'],body['color']))
                    page=next(p for p in doc if '运动员专项膳食评价' in p.get_text())
                    spans=[s for b in page.get_text('dict')['blocks'] for l in b.get('lines',[]) for s in l['spans']]
                    for status,color in [('不足',0xF2994A),('严重不足',0xF2994A),('偏多',0xDC2626),('不建议吃零食',0xDC2626)]:
                        self.assertTrue(any(s['text']==status and s['color']==color for s in spans),status)
            xlsx=Path(tmp)/'report.xlsx';self.service.excel_builder.build(data,xlsx)
            w=openpyxl.load_workbook(xlsx)
            self.assertEqual(2,w['体成分结果'].max_column)
            self.assertEqual(164,w['体成分结果']['B3'].value)
            self.assertIn('cm',w['体成分结果']['B3'].number_format)
            for row in w['运动员专项评价']:
                if row[-1].value in ('不足','严重不足'):
                    self.assertEqual('00F2994A',row[-1].font.color.rgb)
                if row[-1].value=='按照运动情况适量补充饮料':
                    self.assertEqual('00DC2626',row[-1].font.color.rgb)
            w.close()

if __name__=='__main__':unittest.main()
