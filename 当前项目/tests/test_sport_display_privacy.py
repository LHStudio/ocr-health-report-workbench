import copy
import unittest
from nutrition_report.builders.presentation import evaluation_context, evaluation_warnings, report_alerts


class SportDisplayPrivacyTest(unittest.TestCase):
    def test_review_reminders_do_not_publish_internal_thresholds(self):
        notes = [
            '蛋类记录摄入 350 g/天，达到参考下限的 7 倍；触发数据核查提醒（≥3倍工程筛查阈值，非医学上限）。请核对份量、单位、频率和营养参数，不直接认定录入错误。',
            '总能量记录达到参考值的 4 倍；触发≥3倍工程筛查提醒，非医学上限，请核查份量、单位及频率。',
            '鸡蛋日均记录 50900 g 超过单项3000 g/天工程筛查阈值；请核查是否混淆生熟重、份量、单位或频率（非医学上限，不直接判定错误）。',
        ]
        data = {'report_checks': {'warnings': notes}}
        original = copy.deepcopy(data)
        displayed = ' '.join(report_alerts(data))
        for private in ('工程', '阈值', '参考下限', '参考值的', '非医学上限', '数据核查提醒'):
            self.assertNotIn(private, displayed)
        self.assertIn('350 g/天', displayed)
        self.assertIn('50900 g', displayed)
        self.assertEqual(original, data)

    def test_internal_classification_and_policy_notes_stay_internal(self):
        data = {'athlete_evaluation': {'athlete_label': '团体（有氧+力量）',
                 'warnings': ['仅训练期', '60-70kg标准', '原文未明确年龄分界', '内部评分规则']},
                'food_standard_evaluation': {'warnings': ['基础膳食参考标准']}}
        original = copy.deepcopy(data)
        self.assertEqual('', evaluation_context(data))
        self.assertEqual([], evaluation_warnings(data))
        self.assertEqual(original, data)

    def test_questionnaire_export_keeps_shared_profile_columns(self):
        import ast
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / 'local_service.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == 'write_nutrition_workbook')
        values = {node.value for node in ast.walk(function) if isinstance(node, ast.Constant)
                  and isinstance(node.value, str)}
        self.assertTrue({'项目种类', '训练阶段', '训练年限', '当前状态', '运动量'} <= values)


if __name__ == '__main__':
    unittest.main()
