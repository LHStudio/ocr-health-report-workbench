import copy
import json
import tempfile
import unittest
from pathlib import Path
import fitz
from nutrition_report.adapter import _build_user
from nutrition_report.service import NutritionReportService
from scripts.export_nutrition_roster import apply_export_estimates


class RosterExportFollowupTest(unittest.TestCase):
    def person(self, invalid=False):
        return {'id':'fixture/1','general':{'姓名':'测试队员','性别':'女','年龄':'22','体重':'65','项目种类':'篮球','运动类型':'team','运动量':'3'},
            'food_rows':[{'食物名称':'米饭','平均每次食用量':'300g','次数':'3','频率周期(请核对)':'每天'},
                         {'食物名称':'虾','平均每次食用量':'4只g' if invalid else '40g','次数':'4','频率周期(请核对)':'每周'}]}

    def test_default_training_matches_existing_workspace_without_mutating_cache(self):
        person=self.person();before=copy.deepcopy(person)
        s=NutritionReportService(prefer_cloud=False)
        report=s.build_report_data(s.adapt_ocr_person(person).payload)
        self.assertEqual('training',report['user']['trainingPhase'])
        self.assertEqual(before,person)
        self.assertIn(report['nutrition']['energy']['evaluation'],['过少','适宜','过多'])
        self.assertTrue(all(r['evaluation']!='-' for r in report['athlete_evaluation']['rows']))

    def test_explicit_phase_and_current_status_remain_authoritative(self):
        self.assertEqual('',_build_user(self.person(),{'trainingPhase':''})['trainingPhase'])
        self.assertEqual('competition',_build_user(self.person(),{'trainingPhase':'competition'})['trainingPhase'])
        p=self.person();p['general']['当前状态']='比赛期'
        self.assertEqual('competition',_build_user(p,None)['trainingPhase'])
        p['general']['训练阶段']=''
        self.assertEqual('',_build_user(p,None)['trainingPhase'])

    def test_invalid_portions_are_not_fabricated_and_visible_with_quality_page_off(self):
        s=NutritionReportService(prefer_cloud=False);a=s.adapt_ocr_person(self.person(True))
        r=s.build_report_data(a.payload)
        self.assertTrue(r['food_standard_evaluation']['nutrient_record_complete'])
        self.assertIn(r['nutrition']['energy']['evaluation'], {'过少','适宜','过多'})
        self.assertEqual('ready',r['assessment_status'])
        self.assertEqual([],r['assessment_issues'])
        self.assertTrue(any(w.get('food') == '虾' and '4只g' in w.get('message','') for w in r['conversion_warnings']))
        self.assertFalse(any(f['name']=='虾' for f in r['foods']))
        with tempfile.TemporaryDirectory() as tmp:
            for style in ('modern','legacy'):
                path=Path(tmp)/(style+'.pdf');s.pdf_builder.build({**r,'report_style':style},path)
                with fitz.open(path) as doc:
                    text=''.join(p.get_text() for p in doc)
                    self.assertNotIn('待核对：存在未换算食物',doc[0].get_text())
                    self.assertNotIn('OCR 换算与数据质量说明',text)

    def test_complete_records_keep_existing_energy_and_staple_contract(self):
        s=NutritionReportService(prefer_cloud=False);a=s.adapt_ocr_person(self.person());r=s.build_report_data(a.payload)
        self.assertEqual('ready',r['assessment_status'])
        self.assertEqual([],r['assessment_issues'])
        self.assertNotIn('待核对',''.join(r['suggestions']))
        for row in r['food_standard_evaluation']['rows']:
            if row['key'] in {'beans_energy','tubers_energy','grains_remainder'}:
                self.assertEqual('ratio',row['evaluation_basis'])
                self.assertIn(row['evaluation'], {'不足','过少','适中','过多'})

    def test_export_estimates_make_common_ocr_shorthand_complete(self):
        person=self.person(True)
        person['food_rows'].extend([
            {'食物名称':'奶粉','平均每次食用量':'2勺','次数':'2','频率周期(请核对)':'每周'},
            {'食物名称':'果汁饮料','平均每次食用量':'外星人1瓶','次数':'1','频率周期(请核对)':'每天'},
            {'食物名称':'包子/饺子','平均每次食用量':'100/80.g','次数':'1','频率周期(请核对)':'每周'},
        ])
        before=copy.deepcopy(person)
        estimated=apply_export_estimates(person)
        self.assertEqual('60g',estimated['food_rows'][1]['平均每次食用量'])
        self.assertEqual('20g',estimated['food_rows'][2]['平均每次食用量'])
        self.assertEqual('500ml',estimated['food_rows'][3]['平均每次食用量'])
        self.assertEqual('90g',estimated['food_rows'][4]['平均每次食用量'])
        egg={'食物名称':'蛋类','平均每次食用量':'只吃蛋白2个','次数':'2','频率周期(请核对)':'每周'}
        egg_estimated=apply_export_estimates({'food_rows':[egg]})
        self.assertEqual('60g',egg_estimated['food_rows'][0]['平均每次食用量'])
        drink=apply_export_estimates({'food_rows':[{'食物名称':'咖啡','平均每次食用量':'300.ml'}]})
        self.assertEqual('300ml',drink['food_rows'][0]['平均每次食用量'])
        zero=apply_export_estimates({'food_rows':[{'食物名称':'奶粉','平均每次食用量':'0勺'}]})
        self.assertEqual('0勺',zero['food_rows'][0]['平均每次食用量'])
        self.assertEqual(before,person)
        s=NutritionReportService(prefer_cloud=False)
        report=s.build_report_data(s.adapt_ocr_person(estimated).payload)
        self.assertEqual('ready',report['assessment_status'])
        self.assertTrue(all(r['evaluation']!='-' for r in report['athlete_evaluation']['rows']))

if __name__=='__main__':unittest.main()
