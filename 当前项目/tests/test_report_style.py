"""PDF presentation selection must not change nutrition data or Excel output."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import fitz
from fastapi import HTTPException
from openpyxl import load_workbook

import local_service
from nutrition_report import NutritionReportService
from nutrition_report.cloud import resolve_food_data


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INVALID_STYLES = (None, "", "MODERN", " modern", "other", [], {}, True, 0)


def pdf_signature(content):
    """Inspect real PDF text, fonts and vector geometry, not volatile metadata."""
    with fitz.open(stream=content, filetype="pdf") as document:
        text = "\n".join(page.get_text() for page in document)
        fonts = tuple(sorted({font[3] for page in document for font in page.get_fonts()}))
        geometry = tuple(
            (page.number, tuple(round(v, 2) for v in drawing["rect"]),
             drawing.get("fill"), drawing.get("color"))
            for page in document for drawing in page.get_drawings()
        )
        return text, fonts, geometry


def excel_signature(content):
    """Reopen worksheets and compare every value and cell-format definition."""
    workbook = load_workbook(BytesIO(content))
    try:
        return tuple((sheet.title, tuple(
            (cell.coordinate, cell.value, tuple(cell._style) if cell.has_style else None)
            for row in sheet for cell in row
        )) for sheet in workbook)
    finally:
        workbook.close()


class ReportStyleTest(unittest.TestCase):
    maxDiff = 400

    def setUp(self):
        # Candidate-local temporary data only: never an installed/live data junction.
        temp_root = PROJECT_ROOT / "data" / "jobs"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="report-style-", dir=temp_root)
        self.output = Path(self.temp.name)
        self.person = {
            "id": "style-fixture/person", "general": {"姓名": "版式测试", "体重": 60},
            "food_rows": [{"食物名称": "米饭", "平均每次食用量": "100g",
                           "次数": "2", "频率周期(请核对)": "每天"}],
        }
        self.review = {
            "categoryEvaluations": {"谷类": "人工分类结论"},
            "energyEvaluation": "人工能量结论", "calciumEvaluation": "人工钙结论",
            "overallSuggestions": "人工建议保持原文", "interpretation": "人工复核说明",
            "standardEvaluations": {"nuts": "人工专项结论"},
        }
        self.food_data = resolve_food_data(prefer_cloud=False)
        self.service = NutritionReportService(food_data=self.food_data)
        self.job_id = self.output.name
        local_service.JOBS[self.job_id] = {
            "kind": "nutrition", "status": "completed", "job_dir": self.output,
            "people": [self.person],
        }
        # External food resolution alone is substituted; service and builders remain real.
        self.factory = patch.object(local_service, "NutritionReportService",
                                    side_effect=lambda: NutritionReportService(food_data=self.food_data))
        self.factory.start()
        self.clock = patch("nutrition_report.nutrition.datetime", wraps=datetime)
        self.clock.start().now.return_value = datetime(2026, 10, 15, 12, tzinfo=timezone(timedelta(hours=8)))

    def tearDown(self):
        self.clock.stop()
        self.factory.stop()
        local_service.JOBS.pop(self.job_id, None)
        self.temp.cleanup()

    def assert_pdf_styles(self, signatures):
        self.assertEqual(signatures[0], signatures[1], "omitted style must render modern")
        self.assertTrue(signatures[1][2] != signatures[2][2], "legacy must use the original layout")
        for text, fonts, geometry in signatures:
            self.assertIn("版式测试", text)
            self.assertIn("人工建议保持原文", text)
            self.assertIn("人工专项结论", text)
            self.assertTrue(fonts)
            self.assertTrue(geometry)

    def test_default_and_explicit_metadata_leave_nutrition_and_input_unchanged(self):
        adapted = self.service.adapt_ocr_person(
            self.person, auto_evaluation=False, manual_evaluations=self.review,
            report_date="2026-10-15")
        data = []
        for options, expected in (({}, "modern"), ({"report_style": "modern"}, "modern"),
                                  ({"report_style": "legacy"}, "legacy")):
            payload = {**deepcopy(adapted.payload), **options}
            before = deepcopy(payload)
            result = self.service.build_report_data(payload)
            self.assertEqual(expected, result.get("report_style"))
            self.assertEqual(before, payload)
            data.append({key: value for key, value in result.items() if key != "report_style"})
        self.assertEqual(data[0], data[1])
        self.assertEqual(data[1], data[2])
        self.assertEqual(232.0, data[0]["nutrition"]["energy"]["value"])

    def test_json_pdf_default_modern_and_legacy_are_real_distinct_layouts(self):
        adapted = self.service.adapt_ocr_person(
            self.person, auto_evaluation=False, manual_evaluations=self.review,
            report_date="2026-10-15")
        signatures = []
        for index, options in enumerate(({}, {"report_style": "modern"}, {"report_style": "legacy"})):
            payload = {**deepcopy(adapted.payload), **options}
            before = deepcopy(payload)
            path = self.output / f"json-{index}.pdf"
            self.service.generate_pdf_from_json(payload, path)
            self.assertEqual(before, payload)
            signatures.append(pdf_signature(path.read_bytes()))
        self.assert_pdf_styles(signatures)

    def test_ocr_pdf_keyword_selects_layout_and_preserves_reviewed_inputs(self):
        original = deepcopy(self.person)
        review = deepcopy(self.review)
        signatures = []
        for index, options in enumerate(({}, {"report_style": "modern"}, {"report_style": "legacy"})):
            path = self.output / f"ocr-{index}.pdf"
            result = self.service.generate_pdf_from_ocr_person(
                self.person, path, auto_evaluation=False, manual_evaluations=self.review,
                report_date="2026-10-15", **options)
            self.assertEqual(options.get("report_style", "modern"), result["report_data"].get("report_style"))
            signatures.append(pdf_signature(path.read_bytes()))
        self.assertEqual(original, self.person)
        self.assertEqual(review, self.review)
        self.assert_pdf_styles(signatures)

    def test_invalid_json_styles_raise_value_error_without_creating_output(self):
        adapted = self.service.adapt_ocr_person(self.person)
        for index, style in enumerate(INVALID_STYLES):
            with self.subTest(style=style):
                path = self.output / f"invalid-{index}.pdf"
                payload = {**deepcopy(adapted.payload), "report_style": style}
                before = deepcopy(payload)
                with self.assertRaises(ValueError):
                    self.service.generate_pdf_from_json(payload, path)
                self.assertFalse(path.exists())
                self.assertEqual(before, payload)

    def test_invalid_ocr_style_raises_value_error_without_creating_output(self):
        for index, style in enumerate(INVALID_STYLES):
            with self.subTest(style=style):
                path = self.output / f"invalid-ocr-{index}.pdf"
                with self.assertRaises(ValueError):
                    self.service.generate_pdf_from_ocr_person(self.person, path, report_style=style)
                self.assertFalse(path.exists())

    def test_person_api_default_modern_and_legacy_preserve_manual_review(self):
        signatures = []
        for options in ({}, {"report_style": "modern"}, {"report_style": "legacy"}):
            payload = {"person": self.person, "format": "pdf", "auto_evaluation": False,
                       "manual_evaluations": self.review, "report_date": "2026-10-15", **options}
            before = deepcopy(payload)
            response = local_service.generate_nutrition_person_report(self.job_id, self.person["id"], payload)
            self.assertEqual("application/pdf", response.media_type)
            signatures.append(pdf_signature(Path(response.path).read_bytes()))
            self.assertEqual(before, payload)
        self.assert_pdf_styles(signatures)

    def test_batch_both_selects_pdf_style_but_preserves_excel_values_and_styles(self):
        signatures, excels = [], []
        for options in ({}, {"report_style": "modern"}, {"report_style": "legacy"}):
            payload = {"format": "both", "people": [self.person],
                       "reviews": {self.person["id"]: self.review}, **options}
            before = deepcopy(payload)
            response = local_service.generate_nutrition_batch_reports(self.job_id, payload)
            with zipfile.ZipFile(response.path) as archive:
                self.assertIsNone(archive.testzip())
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(2, manifest["success_count"])
                self.assertEqual(0, manifest["failure_count"])
                pdf = next(name for name in archive.namelist() if name.endswith(".pdf"))
                xlsx = next(name for name in archive.namelist() if name.endswith(".xlsx"))
                signatures.append(pdf_signature(archive.read(pdf)))
                excels.append(excel_signature(archive.read(xlsx)))
            self.assertEqual(before, payload)
        self.assert_pdf_styles(signatures)
        self.assertEqual(excels[0], excels[1])
        self.assertEqual(excels[1], excels[2])

    def test_excel_only_ignores_valid_pdf_style_without_changing_cells(self):
        person_excels, batch_excels = [], []
        for options in ({}, {"report_style": "modern"}, {"report_style": "legacy"}):
            payload = {"person": self.person, "format": "excel", "auto_evaluation": False,
                       "manual_evaluations": self.review, **options}
            before = deepcopy(payload)
            response = local_service.generate_nutrition_person_report(self.job_id, self.person["id"], payload)
            person_excels.append(excel_signature(Path(response.path).read_bytes()))
            self.assertEqual(before, payload)
            batch = {"format": "excel", "reviews": {self.person["id"]: self.review}, **options}
            response = local_service.generate_nutrition_batch_reports(self.job_id, batch)
            with zipfile.ZipFile(response.path) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(1, manifest["success_count"])
                self.assertEqual(0, manifest["failure_count"])
                self.assertFalse(any(name.endswith(".pdf") for name in archive.namelist()))
                xlsx = next(name for name in archive.namelist() if name.endswith(".xlsx"))
                batch_excels.append(excel_signature(archive.read(xlsx)))
        self.assertEqual(person_excels[0], person_excels[1])
        self.assertEqual(person_excels[1], person_excels[2])
        self.assertEqual(batch_excels[0], batch_excels[1])
        self.assertEqual(batch_excels[1], batch_excels[2])

    def test_invalid_person_api_styles_are_400_before_any_output(self):
        for style in INVALID_STYLES:
            with self.subTest(style=style):
                payload = {"person": self.person, "format": "pdf", "report_style": style}
                before = deepcopy(payload)
                with self.assertRaises(HTTPException) as error:
                    local_service.generate_nutrition_person_report(self.job_id, self.person["id"], payload)
                self.assertEqual(400, error.exception.status_code)
                self.assertEqual(before, payload)
                self.assertEqual([], list(self.output.rglob("*")))

    def test_invalid_batch_api_styles_are_400_before_any_output(self):
        for style in INVALID_STYLES:
            with self.subTest(style=style):
                payload = {"format": "both", "report_style": style}
                before = deepcopy(payload)
                with self.assertRaises(HTTPException) as error:
                    local_service.generate_nutrition_batch_reports(self.job_id, payload)
                self.assertEqual(400, error.exception.status_code)
                self.assertEqual(before, payload)
                self.assertEqual([], list(self.output.rglob("*")))


if __name__ == "__main__":
    unittest.main()
