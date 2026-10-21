"""Verify the modern profile/grid contract on actual offline-generated PDFs."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import Paragraph, Table

from nutrition_report import NutritionReportService
from nutrition_report.builders import pdf as pdf_module


CATEGORIES = ("谷类", "薯类", "蔬菜", "水果", "畜禽肉", "水产品", "蛋类",
              "豆类", "坚果", "奶类", "零食", "运动营养食品", "饮料", "酒类")


def cell_text(value):
    if isinstance(value, (list, tuple)):
        return "".join(cell_text(item) for item in value)
    return value.getPlainText() if isinstance(value, Paragraph) else str(value or "")


def paragraphs(value):
    if isinstance(value, Paragraph):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from paragraphs(item)


def line_segments(page):
    """Read real PDF strokes, including rectangles emitted by table borders."""
    for drawing in page.get_drawings():
        color = drawing.get("color")
        if color is None or drawing.get("stroke_opacity", 1) == 0:
            continue
        for item in drawing["items"]:
            if item[0] == "l":
                yield item[1], item[2], color
            elif item[0] == "re":
                r = item[1]
                for start, end in ((r.tl, r.tr), (r.tr, r.br), (r.br, r.bl), (r.bl, r.tl)):
                    yield start, end, color


class ReportGridFollowupTest(unittest.TestCase):
    maxDiff = 800

    def setUp(self):
        self.service = NutritionReportService(prefer_cloud=False)
        self.report = self.service.build_report_data({
            "user": {"name": "网格测试甲", "age": 22, "gender": "female", "weight": 65,
                     "activityLevel": "2", "athleteType": "team", "trainingPhase": "training",
                     "projectType": "球类", "trainingYears": "7年", "currentStatus": "正常训练",
                     "fatFreeMass": "50.4"},
            "meals": [{"name": "米饭", "amount": 200}, {"name": "鲜奶", "amount": 450}],
            "autoEvaluation": False,
            "manualEvaluations": {"categoryEvaluations": {"谷类": "人工分类结论"},
                                  "standardEvaluations": {"nuts": "人工专项结论"},
                                  "overallSuggestions": "人工建议原文保留"},
            "report_style": "modern",
        })

    def render(self, data=None):
        data = self.report if data is None else data
        original = deepcopy(data)
        captured, drawn = [], []

        class ObservedTable(Table):
            # Observe the real Table; do not replace layout, splitting or PDF drawing.
            def __init__(table, *args, **kwargs):
                super().__init__(*args, **kwargs)
                captured.append(table)

            def drawOn(table, canvas, x, y, _sW=0):
                left, bottom = canvas.absolutePosition(table._hAlignAdjust(x, _sW), y)
                drawn.append({"table": table, "page": canvas.getPageNumber() - 1,
                              "left": left, "bottom": bottom,
                              "columns": tuple(table._colpositions),
                              "rows": tuple(table._rowpositions)})
                return super().drawOn(canvas, x, y, _sW)

        tmp = tempfile.TemporaryDirectory(prefix="nutrition-grid-")
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "report.pdf"
        with patch.object(pdf_module, "Table", ObservedTable):
            self.service.pdf_builder.build(data, path)
        self.assertEqual(original, data, "Presentation must not mutate inputs or manual values")
        doc = fitz.open(path)
        self.addCleanup(doc.close)
        return doc, captured, drawn

    def profile(self, tables):
        matches = [table for table in tables
                   if table._cellvalues and "姓名" in cell_text(table._cellvalues[0][0])]
        self.assertTrue(matches, "Profile table must be present")
        return matches[0]

    def data_tables(self, drawn):
        tables = []
        for record in drawn:
            values = [[cell_text(cell) for cell in row] for row in record["table"]._cellvalues]
            if values and values[0][0] == "食物摄入量评估报告":
                tables.append(("food", 1, record))
            elif values and values[0][:2] == ["项目", "摄入量 / 参考值"]:
                tables.append(("energy", 0, record))
            elif values and values[0][:3] == ["项目", "实际摄入", "参考目标"]:
                tables.append(("athlete", 0, record))
        return tables

    def assert_segment(self, page, start, end, color_predicate, message):
        tolerance = 0.8
        vertical = abs(start[0] - end[0]) < tolerance
        for p, q, color in line_segments(page):
            if not color_predicate(color):
                continue
            if vertical:
                if (abs(p.x - start[0]) < tolerance and abs(q.x - start[0]) < tolerance
                        and min(p.y, q.y) <= min(start[1], end[1]) + tolerance
                        and max(p.y, q.y) >= max(start[1], end[1]) - tolerance):
                    return
            elif (abs(p.y - start[1]) < tolerance and abs(q.y - start[1]) < tolerance
                  and min(p.x, q.x) <= min(start[0], end[0]) + tolerance
                  and max(p.x, q.x) >= max(start[0], end[0]) - tolerance):
                return
        self.fail(message + f"; missing stroke {start!r} -> {end!r}")

    def assert_bounds(self, doc):
        for page in doc:
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        x0, y0, x1, y1 = span["bbox"]
                        self.assertGreaterEqual(x0, 38, span["text"])
                        self.assertLessEqual(x1, page.rect.width - 38, span["text"])
                        self.assertGreaterEqual(y0, 20, span["text"])
                        self.assertLessEqual(y1, page.rect.height - 20, span["text"])

    def test_profile_has_four_independent_left_aligned_cells_per_row(self):
        _, tables, _ = self.render()
        profile = self.profile(tables)
        self.assertEqual(3, len(profile._cellvalues))
        self.assertEqual([4, 4, 4], [len(row) for row in profile._cellvalues],
                         "Labels and values need separate cells, not centered concatenations")
        expected = [("姓名", "网格测试甲", "年龄", "22 岁"),
                    ("项目种类", "球类", "训练年限", "7年"),
                    ("当前状态", "正常训练", "去脂体重（瘦体重）", "50.4 kg")]
        for actual, wanted in zip(profile._cellvalues, expected):
            self.assertEqual(wanted, tuple(cell_text(cell).strip().rstrip("：:") for cell in actual))
            for cell in actual:
                parts = list(paragraphs(cell))
                self.assertTrue(parts)
                self.assertTrue(all(part.style.alignment == TA_LEFT for part in parts))

    def test_profile_pdf_labels_and_values_start_at_shared_column_edges(self):
        doc, _, _ = self.render()
        page = doc[0]
        columns = [("姓名", "项目种类", "当前状态"), ("网格测试甲", "球类", "正常训练"),
                   ("年龄", "训练年限", "去脂体重"), ("22 岁", "7年", "50.4 kg")]
        anchors = []
        for texts in columns:
            boxes = [page.search_for(text)[0] for text in texts]
            x_values = [box.x0 for box in boxes]
            self.assertLess(max(x_values) - min(x_values), 1.0,
                            f"Profile column must be left-aligned: {texts!r} {x_values!r}")
            anchors.append(min(x_values))
        self.assertTrue(all(right - left > 15 for left, right in zip(anchors, anchors[1:])), anchors)

    def test_dark_headers_have_white_vertical_column_separators(self):
        doc, _, drawn = self.render()
        tables = self.data_tables(drawn)
        self.assertEqual({"food", "energy", "athlete"}, {name for name, _, _ in tables})
        for name, header, record in tables:
            with self.subTest(table=name, page=record["page"]):
                page = doc[record["page"]]
                top = page.rect.height - record["bottom"] - record["rows"][header]
                bottom = page.rect.height - record["bottom"] - record["rows"][header + 1]
                for column in record["columns"][1:-1]:
                    x = record["left"] + column
                    self.assert_segment(page, (x, top + 2), (x, bottom - 2),
                                        lambda rgb: min(rgb) > 0.98,
                                        name + " dark header needs a white vertical separator")

    def test_light_body_cells_have_gray_vertical_and_horizontal_grid(self):
        doc, _, drawn = self.render()
        for name, header, record in self.data_tables(drawn):
            with self.subTest(table=name, page=record["page"]):
                page = doc[record["page"]]
                rows = record["rows"]
                top = page.rect.height - record["bottom"] - rows[header + 1]
                bottom = page.rect.height - record["bottom"] - rows[-1]
                gray = lambda rgb: 0.4 < min(rgb) < 0.98 and max(rgb) - min(rgb) < 0.15
                for column in record["columns"]:
                    x = record["left"] + column
                    self.assert_segment(page, (x, top + 2), (x, bottom - 2), gray,
                                        name + " body needs gray vertical borders")
                left, right = record["left"], record["left"] + record["columns"][-1]
                for row in rows[header + 2:]:
                    y = page.rect.height - record["bottom"] - row
                    self.assert_segment(page, (left + 2, y), (right - 2, y), gray,
                                        name + " body needs gray horizontal borders")

    def test_normal_first_page_keeps_all_categories_and_manual_values(self):
        doc, _, _ = self.render()
        first = doc[0].get_text()
        for category in CATEGORIES:
            self.assertIn(category, first)
        all_text = "".join(page.get_text() for page in doc)
        for text in ("人工分类结论", "人工专项结论"):
            self.assertIn(text, all_text)
        self.assertNotIn("人工建议原文保留",all_text)
        self.assertEqual(["人工建议原文保留"],self.report["withheld_manual_suggestions"])
        self.assert_bounds(doc)

    def test_long_profile_and_split_tables_preserve_text_without_overflow(self):
        data = deepcopy(self.report)
        data["user"]["projectType"] = "长项目名称自动换行核验" * 12 + "项目末尾标记"
        data["user"]["trainingYears"] = "较长训练经历说明" * 12 + "训练末尾标记"
        data["category_result"]["谷类"]["evaluation"] = "人工分类评价保留原文。" * 80 + "分类末尾标记"
        seed = deepcopy(data["athlete_evaluation"]["rows"][0])
        for index in range(35):
            row = deepcopy(seed)
            row.update(key=f"grid_page_{index}", label=f"分页核查项目{index:02d}")
            row.pop("display", None)
            data["athlete_evaluation"]["rows"].append(row)
        doc, _, _ = self.render(data)
        compact = "".join("".join(page.get_text().split()) for page in doc)
        for marker in ("项目末尾标记", "训练末尾标记", "分类末尾标记"):
            self.assertEqual(1, compact.count(marker), marker)
        for index in range(35):
            marker = f"分页核查项目{index:02d}"
            self.assertEqual(1, compact.count(marker), marker)
        self.assertGreater(len(doc), 4)
        self.assert_bounds(doc)


if __name__ == "__main__":
    unittest.main()
