import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import fitz
from openpyxl import load_workbook

from nutrition_report.nutrition import NutritionService
from nutrition_report.builders.pdf import NutritionPDFBuilder
from nutrition_report.builders.excel import NutritionExcelBuilder
from nutrition_report.builders.presentation import evaluation_warnings


HIDDEN = ('代表食物估算（需复核）', '训练计划估算', '周净消耗÷7',
          '非完整全天总消耗', '既有优质蛋白至少一半约束下', '蛋白质计划点由')


class ReportDisplayCleanupTests(unittest.TestCase):
    def report(self, sport='足球', **updates):
        user = dict(projectType=sport, weight=60, bmrMin=1300, bmrMax=1500,
                    gender='female', age=22, activityLevel='3', athleteType='team', trainingPhase='training')
        user.update(updates)
        return NutritionService().build_report_data(dict(user=user, meals=[dict(name='米饭', amount=100)]))

    def fixture(self, sport='足球'):
        d = self.report(sport)
        d['food_standard_evaluation']['warnings'].append('代表食物估算（需复核）：鱼、鸡肉')
        d['report_checks']['warnings'].extend([
            '既有优质蛋白至少一半约束下，示例食谱蛋白质计划点由128.52g/天调整为148.52g/天，仍在个人蛋白质参考范围内；个人需求上下限不变。',
            '保留测试：原始数据存在缺失，请核查。'])
        return d

    def test_nuts_immediately_follows_vegetables_without_changing_topic_count(self):
        for energy_user in ({}, {'bmrMin': 400, 'bmrMax': 500}, {'bmrMin': 3000, 'bmrMax': 3500}):
            d = self.report(**energy_user)
            keys = [i['key'] for i in d['suggestion_items']]
            self.assertEqual(17, len(keys))
            self.assertEqual(keys.index('vegetables')+1, keys.index('nuts'))
            self.assertIn('坚果', d['suggestions'][keys.index('nuts')])

    def test_pdf_both_styles_hide_requested_copy_keep_numbers_and_other_alerts(self):
        with tempfile.TemporaryDirectory() as root:
            for sport in ['足球', '篮球']:
                for style in ['modern', 'legacy']:
                    with self.subTest(sport=sport, style=style):
                        d = self.fixture(sport)
                        d['report_style'] = style
                        before = deepcopy(d)
                        p = Path(root)/(sport+style+'.pdf')
                        NutritionPDFBuilder().build(d, p)
                        with fitz.open(p) as pdf:
                            text = ''.join(page.get_text() for page in pdf)
                        compact = ''.join(text.split())
                        for phrase in HIDDEN:
                            self.assertNotIn(phrase, compact)
                        self.assertIn('1732-2256' if sport == '足球' else '2015.5-2997.6', compact)
                        self.assertIn('运动净消耗', compact)
                        self.assertIn('保留测试', compact)
                        self.assertEqual(before, d)

    def test_excel_and_warning_union_use_same_display_policy(self):
        d = self.fixture()
        before = deepcopy(d)
        with tempfile.TemporaryDirectory() as root:
            p = Path(root)/'report.xlsx'
            NutritionExcelBuilder().build(d, p)
            w = load_workbook(p)
            text = '\n'.join(str(c.value or '') for sheet in w for row in sheet for c in row)
            w.close()
        for phrase in HIDDEN:
            self.assertNotIn(phrase, text)
            self.assertNotIn(phrase, '\n'.join(evaluation_warnings(d)))
        self.assertIn('1732-2256', text)
        self.assertIn('保留测试', text)
        self.assertEqual(before, d)

    def test_incompatible_plan_warning_is_not_hidden(self):
        d = self.report()
        d['report_checks']['warnings'] = ['既有优质蛋白至少一半约束下，示例食谱蛋白质计划点由100.00g/天调整为200.00g/天，已超个人蛋白质参考上限，现有食谱约束不相容；请核对约束，不自动倒扣肉类为0。']
        warnings = '\n'.join(evaluation_warnings(d))
        self.assertIn('超', warnings)
        self.assertIn('不相容', warnings)

    def test_manual_suggestions_preserved_verbatim(self):
        payload = dict(user=dict(projectType='足球', weight=60), meals=[dict(name='米饭', amount=100)],
                       autoEvaluation=False, manualEvaluations={'overallSuggestions': '坚果：人工第一条\n蔬菜：人工第二条'})
        d = NutritionService().build_report_data(payload)
        self.assertEqual(['坚果：人工第一条', '蔬菜：人工第二条'], d['suggestions'])


if __name__ == '__main__':
    unittest.main()
