from copy import deepcopy
from pathlib import Path
import tempfile, unittest
import fitz, openpyxl
from nutrition_report import NutritionReportService


class UnifiedNutritionPresentationTest(unittest.TestCase):
    def setUp(self):
        self.service = NutritionReportService(prefer_cloud=False)
        self.report = self.service.build_report_data({
            'user': {'age':25, 'weight':65, 'gender':'female', 'activityLevel':'2', 'athleteType':'strength', 'trainingPhase':'training'},
            'meals': [{'name':'米饭','amount':200}, {'name':'鲜奶','amount':450}, {'name':'苹果','amount':600}],
            'autoEvaluation':False, 'manualEvaluations':{'proteinEvaluation':'人工蛋白质', 'standardEvaluations':{'nuts':'人工坚果', 'vegetables':''}}})

    def test_exports_merge_rows_without_changing_data(self):
        original = deepcopy(self.report)
        banned = ['原文未明确年龄分界', '差值=实际摄入', '用户新增膳食标准 2026-10-12', '完整达标率', '机器初稿', '规则分', '规则得分', '新增膳食标准逐项评价']
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp)/'report.pdf'; xlsx = Path(tmp)/'report.xlsx'
            self.service.pdf_builder.build(self.report,pdf)
            self.service.excel_builder.build(self.report,xlsx)
            with fitz.open(pdf) as doc:
                all_text = '\n'.join(p.get_text() for p in doc)
                evaluation_text = '\n'.join(p.get_text() for p in doc if '运动员专项膳食评价' in p.get_text())
            wb = openpyxl.load_workbook(xlsx)
            self.assertNotIn('新增膳食标准',wb.sheetnames)
            ws = wb['运动员专项评价']; values = list(ws.values)
            self.assertIn(('项目','实际摄入','单位','参考目标','差值','最终评价','口径'), values)
            cells = '\n'.join(str(c.value or '') for w in wb for row in w for c in row)
            for phrase in banned:
                self.assertNotIn(phrase,all_text)
                self.assertNotIn(phrase,cells)
            expected = {r['key']:r for r in self.report['athlete_evaluation']['rows']}
            expected.update({r['key']:r for r in self.report['food_standard_evaluation']['rows']})
            for row in expected.values():
                matching = [v for v in values if v[0] == row['label']]
                self.assertEqual(1,len(matching),row['label'])
                actual = matching[0]
                self.assertEqual((row['actual'],row['unit'],row['target'],row['gap']),actual[1:5])
                # Empty strings are stored as blank cells by openpyxl, not missing decisions.
                self.assertEqual(row['evaluation'],actual[5] or '')
                self.assertIn(''.join(row['label'].split()),''.join(evaluation_text.split()))
            for manual in ['人工蛋白质','人工坚果']:
                self.assertIn(manual,all_text); self.assertIn(manual,cells)
            wb.close()
        self.assertEqual(original,self.report)

    def test_ui_has_one_evaluation_preview_and_no_machine_column(self):
        source = (Path(__file__).resolve().parents[1]/'src/components/NutritionWorkspace.vue').read_text(encoding='utf8')
        self.assertIn('运动员专项膳食评价',source)
        for phrase in ['<th>机器初稿</th>','<th>规则分</th>','food_standard_evaluation.summary.text','athlete_evaluation.gap_note']:
            self.assertNotIn(phrase,source)
        self.assertIn('unifiedEvaluationRows',source)

    def test_presentation_helper_handles_partial_data_and_dedupes_without_mutation(self):
        from nutrition_report.builders.presentation import evaluation_rows, evaluation_warnings
        data = {'athlete_evaluation':{'rows':[{'key':'vegetables','evaluation':'old'}], 'warnings':['成年分界按18岁实现，原文未明确年龄分界，需业务确认。','缺少体重']},
                'food_standard_evaluation':{'rows':[{'key':'vegetables','evaluation':''},{'key':'milk','evaluation':'不足'}], 'warnings':['缺少体重','60-70kg标准']}}
        original = deepcopy(data)
        self.assertEqual(['vegetables','milk'],[r['key'] for r in evaluation_rows(data)])
        self.assertEqual('',evaluation_rows(data)[0]['evaluation'])
        self.assertEqual(['缺少体重'],evaluation_warnings(data))
        self.assertEqual(original,data)
        self.assertEqual([],evaluation_rows({}))
        self.assertEqual(['milk'],[r['key'] for r in evaluation_rows({'food_standard_evaluation':{'rows':[{'key':'milk'}]}})])


if __name__ == '__main__': unittest.main()
