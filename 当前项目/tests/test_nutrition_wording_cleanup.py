from copy import deepcopy
from pathlib import Path
import tempfile, unittest
import fitz, openpyxl
from nutrition_report import NutritionReportService


class NutritionWordingCleanupTest(unittest.TestCase):
    def test_cleanup_keeps_values_and_renders_context_on_one_line(self):
        service=NutritionReportService(prefer_cloud=False)
        data=service.build_report_data({'user':{'age':25,'weight':65,'gender':'female','activityLevel':'2','athleteType':'strength','trainingPhase':'training'},'meals':[{'name':'米饭','amount':200},{'name':'鲜奶','amount':450}]})
        before=deepcopy(data)
        banned=['参考目标/口径','参数来自用户提供文档，需营养专业人员审核','因此谷类占比上限为80%，不是必须达到80%','采用最低量规则，不以先前500g封顶','显式克数不二次折算']
        with tempfile.TemporaryDirectory() as tmp:
            pdf=Path(tmp)/'report.pdf';xlsx=Path(tmp)/'report.xlsx'
            service.pdf_builder.build(data,pdf);service.excel_builder.build(data,xlsx)
            with fitz.open(pdf) as doc:
                text=''.join(''.join(p.get_text().split()) for p in doc)
                lines=[''.join(s['text'] for s in line['spans']) for p in doc for b in p.get_text('dict')['blocks'] for line in b.get('lines',[])]
            self.assertIn('力量为主 · 仅训练期 · 基础膳食参考标准',lines)
            wb=openpyxl.load_workbook(xlsx); ws=wb['运动员专项评价']
            cells=''.join(''.join(str(c.value or '').split()) for w in wb for row in w for c in row)
            self.assertEqual('力量为主 · 仅训练期 · 基础膳食参考标准',ws['A2'].value)
            for t in banned:self.assertNotIn(t,text);self.assertNotIn(t,cells)
            self.assertNotIn('每个鸡蛋按50g',text)
            self.assertNotIn('每个鸡蛋按50g',cells)
            self.assertIn('先补足主食总量',text)
            self.assertEqual('≥ 50 g/天',next(r for r in data['food_standard_evaluation']['rows'] if r['key']=='eggs')['target'])
            self.assertNotIn('豆类至少5%、薯类至少15%',text)
            self.assertIn('参考目标',text)
            wb.close()
        self.assertEqual(before,data)

    def test_ui_uses_the_same_cleaned_context_and_heading(self):
        source=(Path(__file__).resolve().parents[1]/'src/components/NutritionWorkspace.vue').read_text(encoding='utf8')
        self.assertNotIn('参考目标 / 口径',source)
        self.assertIn('unifiedEvaluationContext',source)


if __name__=='__main__':unittest.main()
