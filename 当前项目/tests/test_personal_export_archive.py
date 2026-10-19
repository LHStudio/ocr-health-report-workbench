import unittest
from scripts.export_nutrition_roster import archive_filename


class PersonalExportArchiveTest(unittest.TestCase):
    def test_archive_count_comes_from_export_results(self):
        self.assertEqual('全部运动员营养报告_44人.zip', archive_filename(44))
        self.assertEqual('全部运动员营养报告_1人.zip', archive_filename(1))


if __name__ == '__main__':
    unittest.main()
