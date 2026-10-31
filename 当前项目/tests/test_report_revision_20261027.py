from copy import deepcopy
import math
import unittest
from nutrition_report import NutritionReportService
from nutrition_report.adapter import build_payload_from_ocr_person
from nutrition_report.builders.presentation import evaluation_rows
from nutrition_report.report_policy import amount_status, attach_energy_availability, finalize_report_copy, interpretation_lines
from nutrition_report.report_checks import build_overall_suggestions


class ReportRevisionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = NutritionReportService(prefer_cloud=False)

    def payload(self, sport='足球'):
        return {'user': {'projectType':sport,'age':20,'weight':60,'gender':'female',
            'athleteType':'strength' if sport=='体操' else 'team','trainingPhase':'training',
            'bmrMin':1600,'bmrMax':1800,'fatFreeMass':45,'activityLevel':'2'},
            'meals':[{'name':'馒头','amount':150},{'name':'米饭','amount':200},
                     {'name':'蛋糕','amount':150},{'name':'鲜奶','amount':100}]}

    def test_severity_boundaries(self):
        for actual, expected in ((0,'严重不足'),(49.99,'严重不足'),(50,'严重不足'),
            (50.01,'不足'),(89.99,'不足'),(90,'适中'),(99.99,'适中'),(100,'适中'),
            (120,'适中'),(120.01,'适中'),(132,'适中'),(132.01,'偏多'),(1000,'偏多')):
            self.assertEqual(expected,amount_status(actual,100,120))
        self.assertEqual('-',amount_status(None,100,120))
        self.assertEqual('-',amount_status(float('nan'),100,120))

    def test_athlete_tolerance_preserves_reference_bounds_and_calculations(self):
        from nutrition_report.athlete import evaluate_athlete
        service=self.service.nutrition_service
        report=self.service.build_report_data(self.payload())
        user=report['user'];nutrition=report['nutrition']
        original,_=evaluate_athlete(user,deepcopy(nutrition),{},service.athlete_config)
        for target in original['rows']:
            key=target['key'];low=target['target_min'];high=target['target_max']
            if key=='vegetables':continue
            cases=[(low*.9,'适中'),(low*.9-.01,'不足')]
            if high is not None:cases.extend([(high*1.1,'适中'),(high*1.1+.01,'偏多')])
            for value,expected in cases:
                with self.subTest(key=key,value=value):
                    n=deepcopy(nutrition)
                    if key=='calcium':n[key]['value']=value
                    else:n[key]=value
                    before=deepcopy(n)
                    actual,_=evaluate_athlete(user,n,{},service.athlete_config)
                    row=next(r for r in actual['rows'] if r['key']==key)
                    self.assertEqual(expected,row['evaluation'])
                    for field in ['actual','target_min','target_max','target','target_planning']:
                        self.assertEqual(value if field=='actual' else target[field],row[field])
                    self.assertEqual(before['energy'],n['energy'])

    def test_scalar_energy_tolerance_is_not_applied_twice(self):
        service=self.service.nutrition_service
        for value,expected in [(1799,'不足'),(1800,'适宜'),(2200,'适宜'),(2201,'偏多')]:
            self.assertEqual(expected,service._eval_energy_against_standard(value,2000))
        for value,expected in [(89.99,'不足'),(90,'适中'),(110,'适中'),(110.01,'偏多')]:
            self.assertEqual(expected,amount_status(value,100,100))
        self.assertEqual('适中',amount_status(900,100,None))
        self.assertEqual('适中',amount_status(0,None,100))

    def test_cooked_conversion_and_source_preservation(self):
        payload=self.payload(); original=deepcopy(payload)
        report=self.service.build_report_data(payload)
        self.assertEqual(original,payload)
        foods={f['name']:f for f in report['foods']}
        self.assertEqual(100,foods['小麦面粉']['amount'])
        self.assertEqual(366,foods['小麦面粉']['nutrition']['energy'])
        self.assertEqual(200,foods['米饭']['amount'])
        self.assertEqual(232,foods['米饭']['nutrition']['energy'])
        self.assertEqual(200,report['category_result']['谷类']['value'])
        self.assertEqual(200,next(r for r in evaluation_rows(report) if r['key']=='grains_remainder')['actual'])
        self.assertIn('生米折算100.0g',report['category_result']['谷类']['weight_note'])
        raw=self.service.build_report_data({**payload,'meals':[{'name':'生米','amount':100}]})
        self.assertEqual(232,raw['nutrition']['energy']['value'])

    def test_adapter_conversion_is_not_applied_twice(self):
        person={'general':{},'food_rows':[{'食物名称':name,'频率周期(请核对)':'每天',
            '次数':'1','平均每次食用量':amount} for name,amount in [('馒头','150g'),('米饭','200g')]]}
        before=deepcopy(person)
        adapted=build_payload_from_ocr_person(person,user_overrides=self.payload()['user'])
        self.assertEqual(100,adapted.payload['meals'][0]['amount'])
        self.assertEqual(150,adapted.source_foods[0]['daily_grams'])
        report=self.service.build_report_data(adapted.payload)
        self.assertEqual(598,report['nutrition']['energy']['value'])
        self.assertEqual(before,person)

    def test_ea_threshold_missing_and_interval(self):
        for ei,eee,status in ((1600,[400,400],'risk'),(1750,[400,400],'above_threshold'),
            (1800,[400,600],'possible_risk'),(100,[400,600],'risk')):
            report={'user':{'fatFreeMass':45},'nutrition':{'energy':{'value':ei,'training_expenditure':{'net_daily_kcal':eee}}}}
            attach_energy_availability(report)
            ea=report['nutrition']['energy']['availability']
            self.assertEqual(status,ea['status'])
            self.assertAlmostEqual((ei-max(eee))/45,ea['min'])
        for ffm in (None,0,-1,float('nan'),float('inf')):
            report['user']['fatFreeMass']=ffm
            attach_energy_availability(report)
            self.assertEqual('missing',report['nutrition']['energy']['availability']['status'])

    def test_sport_order_grouping_calcium_and_interpretation(self):
        for sport, order in (('足球',['energy','protein','calcium']),('篮球',['energy','protein','calcium']),
                             ('体操',['energy','protein','vegetables','calcium'])):
            report=self.service.build_report_data(self.payload(sport))
            keys=[i['key'] for i in report['suggestion_items']]
            self.assertEqual(order,keys[:len(order)])
            self.assertEqual('hydration',keys[-1])
            self.assertFalse(set(keys)&{'snacks','quality_protein','milk','livestock_remainder','seafood','grains_remainder','beans_energy','tubers_energy'})
            self.assertIn('奶类',report['suggestions'][1])
            self.assertIn('肉类（含水产品）',report['suggestions'][1])
            self.assertIn('150-200mL',report['suggestions'][-1])
            calcium=next(r for r in evaluation_rows(report) if r['key']=='calcium')
            self.assertEqual('mg/天',calcium['unit'])
            self.assertEqual(report['nutrition']['calcium']['value'],calcium['actual'])
            self.assertEqual(3,len(report['interpretation_lines']))
            self.assertIn('零食摄入过多',report['interpretation_lines'][0])
            self.assertIn('2. 三大营养素',self.service.pdf_builder._interpretation(report))
            self.assertIn('3. 膳食中的钙',self.service.pdf_builder._interpretation(report))
            self.assertNotIn('过少',str(report['suggestions']))
            self.assertNotIn('严重过多',str(report))

    def test_normal_rows_are_omitted(self):
        report=self.service.build_report_data(self.payload())
        report['nutrition']['energy']['evaluation']='适宜'
        for section in ('athlete_evaluation','food_standard_evaluation'):
            for row in report[section]['rows']: row['evaluation']='适中'
        items=build_overall_suggestions(report)
        self.assertEqual(['hydration'],[i['key'] for i in items])
        report['food_standard_evaluation']['rows'][0]['evaluation']='不足'
        items=build_overall_suggestions(report)
        self.assertEqual(['nuts','hydration'],[i['key'] for i in items])

    def test_protein_leads_group_even_when_normal_and_milk_is_low(self):
        report = self.service.build_report_data(self.payload())
        for section in ('athlete_evaluation', 'food_standard_evaluation'):
            for row in report[section]['rows']:
                row['evaluation'] = '适中'
                if row['key'] == 'milk':
                    row['evaluation'] = '不足'
        text = next(i['text'] for i in build_overall_suggestions(report) if i['key']=='protein')
        self.assertTrue(text.startswith('蛋白质：目前 '))
        self.assertIn('参考目标', text)
        self.assertIn('；适中。其中奶类不足', text)
        self.assertNotIn('蛋白质（', text)

    def test_protein_direction_and_meat_substitution_follow_total_protein(self):
        report = self.service.build_report_data(self.payload())
        for state, action in [('不足','增加'), ('严重不足','增加'), ('偏多','减少')]:
            for section in ('athlete_evaluation', 'food_standard_evaluation'):
                for row in report[section]['rows']:
                    if row['key']=='protein': row['evaluation']=state
                    if row['key']=='seafood': row['evaluation']='不足'
                    if row['key']=='livestock_remainder': row['evaluation']='偏多'
            text = next(i['text'] for i in build_overall_suggestions(report) if i['key']=='protein')
            self.assertIn('；建议'+action+'摄入。', text)
            self.assertIn('肉类中水产品不足、畜禽肉偏多', text)
            self.assertIn('用水产品替换部分畜禽肉', text)
            if state != '偏多': self.assertNotIn('减少畜禽肉', text)

    def test_macro_explanation_lists_abnormal_nutrients_without_changing_values(self):
        report = self.service.build_report_data(self.payload())
        for row in report['athlete_evaluation']['rows']:
            if row['key']=='protein': row['evaluation']='适中'
            if row['key']=='fat': row['evaluation']='偏多'
            if row['key']=='carbohydrate': row['evaluation']='不足'
        before = deepcopy(report)
        text = interpretation_lines(report)[1]
        self.assertEqual('三大营养素供能比略有失衡：脂肪偏多、碳水化合物不足。',text)
        self.assertEqual(before,report)

    def test_macro_explanation_keeps_balanced_and_unknown_cases(self):
        report = {'nutrition': {'protein':100,'fat':50,'carbohydrate':200,
            'energy': {'reference_type':'bmr','standard_min':2000,'standard_max':2000}},
            'athlete_evaluation': {'rows':[{'key':key,'target_min':0,'target_max':1000,'evaluation':'适中'}
                for key in ('protein','fat','carbohydrate')]}}
        self.assertEqual('三大营养素供能比适宜。',interpretation_lines(report)[1])
        report['nutrition']['protein']=None
        self.assertEqual('三大营养素供能比暂无法评价。',interpretation_lines(report)[1])

    def test_snack_threshold_strictly_greater_than_thirty(self):
        report=self.service.build_report_data(self.payload())
        report['nutrition']['energy'].update(value=1000,exact_value=1000)
        for snack, expected in ((299.99,False),(300,False),(300.01,True)):
            report['foods']=[{'category':'零食','nutrition':{'energy':snack}}]
            finalize_report_copy(report)
            self.assertEqual(expected,'零食摄入过多' in report['interpretation_lines'][0])

    def test_manual_conclusions_remain_verbatim(self):
        payload=self.payload()
        payload.update(autoEvaluation=False,manualEvaluations={'energyEvaluation':'人工评价',
            'proteinEvaluation':'适宜','overallSuggestions':'人工建议原文','interpretation':'人工解读原文'})
        report=self.service.build_report_data(payload)
        self.assertEqual('人工评价',report['nutrition']['energy']['evaluation'])
        self.assertEqual(['人工建议原文'],report['suggestions'])
        self.assertEqual('人工解读原文',self.service.pdf_builder._interpretation(report))

    def test_energy_priority_retains_ratio_evidence(self):
        report=self.service.build_report_data(self.payload())
        for row in report['food_standard_evaluation']['rows']:
            if row['key'] in {'grains_remainder','beans_energy','tubers_energy'}:
                self.assertEqual('energy_priority',row['evaluation_basis'])
                self.assertIn(row['evaluation'], {'不足','严重不足'})
                self.assertIn('evaluation',row['original_rule'])
                self.assertIsNone(row['display']['gap'])
                self.assertEqual('先补足主食，再调整谷豆薯比例',row['display']['target'])

    def test_soy_equivalent_is_shared_without_recalculating_nutrients(self):
        payload=self.payload()
        payload['meals']=[{'name':'豆腐','amount':52},
                          {'name':'豆腐丝/千张/豆腐干','amount':19},
                          {'name':'豆浆','amount':146}]
        before=deepcopy(payload)
        report=self.service.build_report_data(payload)
        self.assertEqual(30,report['category_result']['豆类']['value'])
        self.assertEqual(217,report['category_result']['豆类']['recorded_weight_g'])
        row=next(r for r in evaluation_rows(report) if r['key']=='beans_energy')
        self.assertEqual(30,row['actual'])
        self.assertEqual('豆类（大豆等价量）',row['label'])
        self.assertEqual([10,10,10],[i['soy_equivalent_grams'] for i in report['bean_equivalent']['items']])
        self.assertEqual(76.34,report['nutrition']['energy']['value'])
        self.assertEqual(9.92,report['nutrition']['protein'])
        self.assertEqual(158.4,report['nutrition']['calcium']['value'])
        self.assertEqual(before,payload)
        self.assertEqual([52,19,146],[f['amount'] for f in report['foods']])

    def test_soy_weekly_frequency_and_raw_beans(self):
        person={'general':{},'food_rows':[{'食物名称':name,'频率周期(请核对)':'每周',
            '次数':'1','平均每次食用量':amount} for name,amount in
            [('豆腐','364g'),('豆腐丝/千张/豆腐干','133g'),('豆浆','1022g')]]}
        adapted=build_payload_from_ocr_person(person,user_overrides=self.payload()['user'])
        report=self.service.build_report_data(adapted.payload)
        self.assertEqual(30,report['category_result']['豆类']['value'])
        adapted.payload['meals'].append({'name':'黑豆','amount':5})
        report=self.service.build_report_data(adapted.payload)
        self.assertEqual(35,report['category_result']['豆类']['value'])

    def test_soy_target_and_gap_use_the_same_equivalent_basis(self):
        # Without an energy reference, use the equivalent-weight ratio rule.
        report=self.service.build_report_data({'user':{},'meals':[
            {'name':'豆腐','amount':52},{'name':'豆腐丝/千张/豆腐干','amount':19},
            {'name':'豆浆','amount':146},{'name':'米饭','amount':4000}]})
        row=next(r for r in evaluation_rows(report) if r['key']=='beans_energy')
        target=(4000/2+30)*.05
        self.assertEqual(f'≥ {target:.2f} g/天',row['target'])
        self.assertEqual(round(30-target,2),row['gap'])
        self.assertEqual(30,row['actual'])


if __name__=='__main__': unittest.main()
