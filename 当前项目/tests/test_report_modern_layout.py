"""User-approved modern PDF layout contract; uses synthetic, offline data only."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz
from reportlab.lib import colors
from reportlab.lib.units import mm
from nutrition_report import NutritionReportService
from nutrition_report.builders import pdf as renderer


class ModernReportLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.data = NutritionReportService(prefer_cloud=False).build_report_data({
            'user': {'name': '版式测试', 'age': 25, 'weight': 65,
                     'gender': 'female', 'activityLevel': '2',
                     'athleteType': 'strength', 'trainingPhase': 'training'},
            'meals': [{'name': '米饭', 'amount': 200}, {'name': '鲜奶', 'amount': 450}],
        })
        cls.data['preview_mode'] = True
        cls.before = deepcopy(cls.data)
        cls.paragraphs = []
        original = renderer.Paragraph
        def capture(*args, **kwargs):
            p = original(*args, **kwargs)
            cls.paragraphs.append(p)
            return p
        cls.path = Path(cls.tmp.name) / 'modern.pdf'
        with patch.object(renderer, 'Paragraph', side_effect=capture):
            renderer.NutritionPDFBuilder().build(cls.data, cls.path)
        cls.doc = fitz.open(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.doc.close()
        cls.tmp.cleanup()

    def test_major_titles_are_centered_on_the_page(self):
        for title in ['营养健康评估报告', '能量及钙摄入量评估报告', '运动员专项膳食评价']:
            matches = [r for p in self.doc for r in p.search_for(title)]
            self.assertEqual(1, len(matches), title)
            self.assertAlmostEqual(self.doc[0].rect.width / 2, (matches[0].x0 + matches[0].x1) / 2, delta=1)

    def test_running_header_and_preview_banner_are_absent(self):
        for page in self.doc:
            self.assertNotIn('版式预览 / 示范数据', page.get_text())
            self.assertEqual('', page.get_textbox(fitz.Rect(0, 0, page.rect.width, 40)).strip())
            self.assertFalse([d for d in page.get_drawings() if d['rect'].y1 < 50])

    def test_energy_cells_and_athlete_targets_are_centered(self):
        selected = [p for p in self.paragraphs if p.style.name == 'EvaluationTarget' or p.getPlainText() in ('总能量摄入量', '钙', '项目', '摄入量 / 参考值')]
        self.assertGreater(len(selected), 10)
        for p in selected:
            self.assertEqual(1, p.style.alignment, p.getPlainText())
        page = next(p for p in self.doc if '能量及钙摄入量评估报告' in p.get_text())
        rect = page.search_for('总能量摄入量')[0]
        self.assertAlmostEqual(39 * mm, (rect.x0 + rect.x1) / 2, delta=1)

    def test_note_stays_small_and_white(self):
        notes = [p for p in self.paragraphs if p.style.name == 'NutritionNote']
        self.assertEqual(1, len(notes))
        self.assertEqual(colors.white, notes[0].style.backColor)
        self.assertEqual(9, notes[0].style.fontSize)

    def test_pie_diameter_is_doubled_and_labels_enlarged(self):
        drawing = renderer.NutritionPDFBuilder._build_macro_energy_chart({'protein': 100, 'fat': 80, 'carbohydrate': 300})
        pie = drawing.contents[0]
        self.assertEqual((156, 156), (pie.width, pie.height))
        self.assertGreaterEqual(pie.slices.fontSize, 11)
        self.assertLessEqual(pie.x + pie.width, drawing.width)
        self.assertLessEqual(pie.y + pie.height, drawing.height)
        self.assertLessEqual(drawing.width, 83 * mm - 24)

    def test_no_input_mutation_or_page_overflow(self):
        self.assertEqual(self.before, self.data)
        self.assertEqual(4, len(self.doc))
        for page in self.doc:
            for block in page.get_text('dict')['blocks']:
                for line in block.get('lines', []):
                    for span in line['spans']:
                        x0, y0, x1, y1 = span['bbox']
                        self.assertGreaterEqual(x0, 17 * mm)
                        self.assertLessEqual(x1, page.rect.width - 17 * mm)
                        self.assertGreaterEqual(y0, 40)
                        self.assertLessEqual(y1, page.rect.height - 8 * mm)


if __name__ == '__main__':
    unittest.main()
