import unittest
from nutrition_report.report_checks import build_overall_suggestions


class MinimumOnlyAdviceTest(unittest.TestCase):
    def test_meeting_a_minimum_does_not_assert_unbounded_intake_is_appropriate(self):
        row=dict(key='nuts',label='坚果',actual=1000,unit='g/天',target='≥ 10 g/天',
                 target_min=10,target_max=None,evaluation='适中')
        report={'food_standard_evaluation':{'rows':[row]}}
        text=next(x['text'] for x in build_overall_suggestions(report) if x['key']=='nuts')
        self.assertNotIn('保持在个人参考范围内',text)
        self.assertIn('最低参考量',text)


if __name__=='__main__':
    unittest.main()
