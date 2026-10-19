import unittest
from copy import deepcopy
from scripts.import_bmr_ranges import merge_ranges


class BmrImportTest(unittest.TestCase):
    def test_only_unique_exact_names_and_preserve_other_data(self):
        people=[dict(id='a',general={'姓名':'甲','人工备注':'保留'},food_rows=[{'x':1}]),
                dict(id='b',general={'姓名':'乙'}),dict(id='c',general={'姓名':'乙'})]
        original=deepcopy(people)
        result,audit=merge_ranges(people,{'甲':(1200,1400),'乙':(1300,1500),'丙':(1400,1600)})
        self.assertEqual(original,people)
        self.assertEqual(1200,result[0]['general']['BMR最低值'])
        self.assertEqual('保留',result[0]['general']['人工备注'])
        self.assertEqual(original[0]['food_rows'],result[0]['food_rows'])
        self.assertNotIn('BMR最低值',result[1]['general'])
        self.assertEqual(['乙'],audit['ambiguous_names'])
        self.assertEqual(['丙'],audit['unmatched_names'])
        self.assertEqual(1,audit['matched_count'])

    def test_conflicting_existing_range_requires_review(self):
        with self.assertRaisesRegex(ValueError,'已有BMR'):
            merge_ranges([dict(id='a',general={'姓名':'甲','BMR最低值':1100,'BMR最高值':1400})],{'甲':(1200,1400)})
