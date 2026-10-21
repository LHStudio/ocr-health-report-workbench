import re
import unittest
from pathlib import Path
from reportlab.lib.styles import ParagraphStyle
from nutrition_report.food_standards import evaluate_food_standards
from nutrition_report.nutrition import NutritionService
from nutrition_report.builders.pdf import NutritionPDFBuilder


class ReportFeedbackTest(unittest.TestCase):
    def setUp(self):
        self.db = {k: dict(category=v, energy=100, protein=10, fat=1, carbohydrate=10, calcium=10)
                   for k, v in {'谷':'谷类','豆':'豆类','薯':'薯类','鸡肉':'畜禽肉','牛肉':'畜禽肉','鱼':'水产品','糕点':'零食'}.items()}

    def result(self, **amounts):
        return evaluate_food_standards({'user': {'weight':65},
            'meals':[{'name':k,'amount':v} for k,v in amounts.items()]},self.db)

    def test_grain_remainder_uses_derived_upper_bound_not_fixed_target(self):
        for amount, evaluation, score in [(800,'适中',1),(801,'过多',0),(700,'适中',1)]:
            result=self.result(谷=amount,豆=50,薯=150)
            row=next(r for r in result['rows'] if r['key']=='grains_remainder')
            self.assertEqual(evaluation,row['evaluation'])
            self.assertEqual(score,row['score'])
            self.assertEqual('≤ 80 %',row['target'])
            self.assertEqual(10,result['summary']['total'])
        row=next(r for r in self.result(谷=0,豆=0,薯=0)['rows'] if r['key']=='grains_remainder')
        self.assertIsNone(row['score'])
        self.assertEqual('-',row['evaluation'])

    def test_poultry_is_in_non_seafood_meat_without_false_warning(self):
        row=next(r for r in self.result(鸡肉=20,牛肉=70,鱼=30)['rows'] if r['key']=='livestock_remainder')
        self.assertEqual('畜禽肉',row['label'])
        self.assertEqual(75,row['actual'])
        self.assertEqual('过多',row['evaluation'])
        self.assertEqual('≤ 70 %',row['target'])
        self.assertIsNone(row['score'])
        self.assertIn('水产品',row['note'])

    def test_snacks_show_only_requested_advice_for_positive_zero_and_missing(self):
        for amount in [0,10]:
            row=next(r for r in self.result(糕点=amount)['rows'] if r['key']=='snacks')
            self.assertEqual('不建议吃零食',row['evaluation'])
            self.assertIsNone(row['score'])
        report=NutritionService().build_report_data({'user':{},'meals':[], 'source_foods':[]})
        row=next(r for r in report['food_standard_evaluation']['rows'] if r['key']=='snacks')
        self.assertEqual('不建议吃零食',row['evaluation'])
        self.assertIsNone(row['actual'])
        self.assertIsNone(row['score'])

    def test_drinks_and_alcohol_are_literal_hyphens(self):
        report=NutritionService(food_db=self.db).build_report_data({'user':{'weight':65},'meals':[]})
        self.assertEqual('-',report['category_result']['饮料']['evaluation'])
        self.assertEqual('-',report['category_result']['酒类']['evaluation'])
        self.assertEqual('-',report['nutrition']['energy']['evaluation'])

    def test_suggestions_are_concise_without_changing_numeric_precision(self):
        report=NutritionService(food_db=self.db).build_report_data({'user':{'weight':65},
            'meals':[{'name':'谷','amount':912.3456},{'name':'豆','amount':23.4567},{'name':'薯','amount':42.1234}]})
        text='\n'.join(report['suggestions'])
        self.assertNotRegex(text,r'\d+\.\d{3,}')
        self.assertNotIn('请结合训练复核调整',text)
        self.assertLessEqual(text.count('结合训练'),1)
        row=next(r for r in report['food_standard_evaluation']['rows'] if r['key']=='beans_energy')
        self.assertNotEqual(round(row['actual'],1),row['actual'])

    def test_suggestions_are_full_width_separate_rows_with_hanging_indent(self):
        style=ParagraphStyle('test',fontName='Helvetica',fontSize=10)
        suggestions=['目前 35.1 g/天，建议逐步调整。','请结合训练情况调整。']
        table=NutritionPDFBuilder()._build_food_report({},['零食','饮料'],normal=style,
            header=style,category_style=style,suggestions=suggestions)
        self.assertEqual(7,len(table._cellvalues))
        self.assertEqual('整体评估及建议',table._cellvalues[4][0].getPlainText())
        for idx in [4,5,6]: self.assertIn(('SPAN',(0,idx),(-1,idx)),table._spanCmds)
        paragraph=table._cellvalues[5][0]
        self.assertGreater(paragraph.style.leading,12)
        self.assertGreater(paragraph.style.leftIndent,0)
        self.assertIn('<nobr>35.1\u00a0g/天</nobr>',paragraph.text)

    def test_frontend_preserves_report_evaluations_including_hyphens(self):
        source=(Path(__file__).resolve().parents[1]/'src/components/NutritionWorkspace.vue').read_text(encoding='utf8')
        line=next(l for l in source.splitlines() if l.startswith('function machineEvaluationText('))
        self.assertNotIn("return text === '-' ? ''",line)
        self.assertNotIn("return '偏少'",line)


if __name__=='__main__': unittest.main()
