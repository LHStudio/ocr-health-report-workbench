from pathlib import Path
import json,tempfile,unittest
import fitz,openpyxl
from nutrition_report import NutritionReportService
from nutrition_report.nutrition import NutritionService


class EvaluationStyleFollowupTest(unittest.TestCase):
    def report(self,carbohydrate=300):
        service=NutritionService();service.food_db['主食']={'category':'谷类','energy':1500,'protein':119,'fat':40,'carbohydrate':carbohydrate,'calcium':1000}
        return service.build_report_data({'user':{'age':25,'weight':70,'gender':'female','activityLevel':'2','athleteType':'strength','trainingPhase':'training'},'meals':[{'name':'主食','amount':100}]})

    def test_carbohydrate_point_target_classifies_below_equal_above(self):
        for actual,gap,status in [(300,-50,'不足'),(350,0,'适中'),(400,50,'过多')]:
            row=next(r for r in self.report(actual)['athlete_evaluation']['rows'] if r['key']=='carbohydrate')
            self.assertEqual(gap,row['gap'])
            self.assertEqual(status,row['machine_evaluation'])
            self.assertEqual(status,row['evaluation'])

    def test_machine_ratings_and_energy_use_three_terms(self):
        report=self.report()
        values=[r['evaluation'] for r in report['athlete_evaluation']['rows']+report['food_standard_evaluation']['rows']]
        self.assertTrue(set(values)<={'不足','过多','适中','-','不建议吃零食'},set(values))
        grain=next(r for r in report['food_standard_evaluation']['rows'] if r['key']=='grains_remainder')
        self.assertEqual('ratio',grain['evaluation_basis']);self.assertEqual(80,grain['target_max'])
        self.assertEqual('过多',report['category_result']['谷类']['evaluation'])
        for actual,status in [(1000,'过少'),(2100,'适宜'),(3000,'过多')]:
            self.assertEqual(status,NutritionService()._eval_energy_against_standard(actual,2100))

    def test_base_reference_note_does_not_claim_weight_suppression(self):
        data=self.report()['food_standard_evaluation']
        self.assertIn('基础膳食参考标准',data['warnings'])
        text=json.dumps(data,ensure_ascii=False)
        for phrase in ['不自动按体重线性加量','倍率，比值目标','低于60kg不自动外推']:
            self.assertNotIn(phrase,text)

    def test_pdf_and_excel_evaluations_use_red_only_for_alerts(self):
        service=NutritionReportService(prefer_cloud=False)
        report=self.report(400)
        with tempfile.TemporaryDirectory() as tmp:
            pdf=Path(tmp)/'sample.pdf';xlsx=Path(tmp)/'sample.xlsx'
            service.pdf_builder.build(report,pdf);service.excel_builder.build(report,xlsx)
            with fitz.open(pdf) as doc:
                spans=[s for p in doc for b in p.get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans']]
            alerts=[s for s in spans if s['text'].strip() in {'不足','过少','过多'}]
            self.assertTrue(alerts)
            self.assertTrue(all(s['color']==0xDC2626 for s in alerts),[(s['text'],s['color']) for s in alerts])
            normal=[s for s in spans if s['text'].strip()=='适中']
            self.assertTrue(normal)
            self.assertTrue(all(s['color']!=0xDC2626 for s in normal))
            wb=openpyxl.load_workbook(xlsx)
            checked=0
            for w in wb:
                for row in w:
                    for c in row:
                        if c.value in {'不足','过少','过多'}:
                            self.assertEqual('rgb',c.font.color.type if c.font.color else None)
                            self.assertEqual('DC2626',c.font.color.rgb[-6:]);checked+=1
                        elif c.value=='适中':
                            self.assertFalse(c.font.color and c.font.color.type=='rgb' and c.font.color.rgb[-6:]=='DC2626')
            self.assertGreater(checked,5)
            # The summary sheet must show the same carbohydrate decision, not a referral label.
            nutrition={r[0]:r for r in wb['营养总计'].iter_rows(min_row=2,values_only=True)}
            self.assertEqual('过多',nutrition['碳水化合物'][3])
            wb.close()

    def test_ui_options_and_alert_hooks_match_reports(self):
        root=Path(__file__).resolve().parents[1]
        source=(root/'src/components/NutritionWorkspace.vue').read_text(encoding='utf8')
        self.assertTrue('value="不足"' in source and 'value="过多"' in source)
        self.assertFalse('value="偏少"' in source or 'value="偏多"' in source)
        self.assertIn('evaluationAlertClass(finalEvaluation(row, reportReview))',source)
        self.assertIn('evaluationAlertClass(reportReview.categoryEvaluations[row.key])',source)
        self.assertIn('evaluationAlertClass(reportReview[row.key])',source)
        self.assertIn('#dc2626',(root/'src/style.css').read_text(encoding='utf8').lower())

    def test_about_version_is_2026_10_13_v5_0_4(self):
        root=Path(__file__).resolve().parents[1]
        package=json.loads((root/'package.json').read_text(encoding='utf8'))
        lock=json.loads((root/'package-lock.json').read_text(encoding='utf8'))
        self.assertEqual('7.3.2-RC7',package['version'])
        self.assertEqual('7.3.2-RC7',lock['version'])
        self.assertEqual('7.3.2-RC7',lock['packages']['']['version'])
        app=(root/'src/App.vue').read_text(encoding='utf8')
        self.assertTrue('`V${appMetadata.version}`' in app)
        readme=(root/'README.md').read_text(encoding='utf8')
        self.assertIn('当前版本：`V7.3.2-RC7`',readme)
        self.assertIn('文档更新：2026-10-16',readme)
        self.assertIn('不建议吃零食',readme)


if __name__=='__main__':unittest.main()
