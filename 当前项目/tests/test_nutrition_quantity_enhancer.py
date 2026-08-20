from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from openpyxl import Workbook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import enhance_nutrition_quantities as enhancer  # noqa: E402
from scripts import enhance_nutrition_cells as cells  # noqa: E402


class NutritionQuantityEnhancerTest(unittest.TestCase):
    def make_workbook(self, path: Path) -> None:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "食物频率明细"
        worksheet.append(
            [
                "人员文件夹", "食物编号", "食物名称", "平均每次食用量", "次数",
                "频率周期(请核对)", "是否不吃", "OCR原始行", "人工核对备注",
            ]
        )
        worksheet.append(["ocr/1", "1.1", "米饭", "1000g", "1", "每天", "", "raw-a", "食用量疑似异常“1000g”"])
        worksheet.append(["ocr/1", "1.2", "大米粥", "", "", "未识别", "", "raw-b", ""])
        worksheet.append(["ocr/2", "2.1", "馒头", "50g", "1", "每天", "", "raw-c", "普通备注"])
        workbook.save(path)
        workbook.close()

    def test_default_scope_uses_quantity_risk_notes_and_explicit_targets_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.xlsx"
            self.make_workbook(path)

            flagged, people = enhancer.collect_quantity_targets(path)
            explicit, _ = enhancer.collect_quantity_targets(path, explicit_targets=["ocr/1:1.2"])
            missing, _ = enhancer.collect_quantity_targets(path, scope="missing")

        self.assertEqual([("ocr/1", "1.1")], [(row["person"], row["code"]) for row in flagged])
        self.assertEqual([("ocr/1", "1.2")], [(row["person"], row["code"]) for row in explicit])
        self.assertEqual([("ocr/1", "1.2")], [(row["person"], row["code"]) for row in missing])
        self.assertEqual(["ocr/1", "ocr/2"], people)

    def test_quantity_cell_uses_original_gray_pixels_and_two_variants(self) -> None:
        spec = cells.TABLE_SPECS[0]
        table = np.full((spec.output_height, spec.output_width), 255, dtype=np.uint8)
        x0, y0, x1, y1 = enhancer.quantity_cell_bounds(spec, 0)
        table[y0 + 4 : y0 + 22, x0 + 30 : x0 + 38] = 70

        crop = enhancer.extract_quantity_cell(table, spec, 0)
        variants = enhancer.make_quantity_variants(crop)
        strip, mappings = enhancer.build_quantity_strip(variants)

        self.assertEqual((y1 - y0, x1 - x0), crop.shape)
        self.assertEqual(70, int(crop.min()))
        self.assertEqual(enhancer.VARIANTS, tuple(m["variant"] for m in mappings))
        self.assertEqual((enhancer.QUANTITY_CELL_HEIGHT, enhancer.QUANTITY_BAND_WIDTH), strip.shape)
        self.assertLess(int(strip.min()), 100)

    def test_ocr_box_maps_back_to_quantity_variant(self) -> None:
        mappings = []
        for index, variant in enumerate(enhancer.VARIANTS):
            x0 = index * (enhancer.QUANTITY_CELL_WIDTH + enhancer.QUANTITY_CELL_GAP)
            mappings.append(
                {
                    "variant": variant,
                    "x_start": x0,
                    "x_end": x0 + enhancer.QUANTITY_CELL_WIDTH,
                    "y_start": 100,
                    "y_end": 210,
                }
            )
        bands = [
            {
                "id": "ocr/3|20",
                "person": "ocr/3",
                "code": "20",
                "x_start": 0,
                "x_end": enhancer.QUANTITY_BAND_WIDTH,
                "y_start": 100,
                "y_end": 210,
                "variants": mappings,
            }
        ]
        threshold_x = enhancer.QUANTITY_CELL_WIDTH + enhancer.QUANTITY_CELL_GAP
        items = [{"text": "50g", "score": 0.92, "box": [threshold_x + 20, 120, threshold_x + 120, 190]}]

        result = enhancer.map_ocr_items(items, bands)

        self.assertEqual(1, len(result["mapped"]))
        self.assertEqual(("ocr/3", "20", "threshold"), tuple(result["mapped"][0][key] for key in ("person", "code", "variant")))

    def test_two_route_agreement_is_only_a_review_candidate(self) -> None:
        agreed = {
            "grayscale": [{"text": "250", "score": 0.93, "box": [0, 0, 30, 20]}, {"text": "ml", "score": 0.90, "box": [35, 0, 65, 20]}],
            "threshold": [{"text": "250ml", "score": 0.88, "box": [0, 0, 70, 20]}],
        }
        conflict = {
            "grayscale": [{"text": "250ml", "score": 0.93, "box": [0, 0, 70, 20]}],
            "threshold": [{"text": "350ml", "score": 0.88, "box": [0, 0, 70, 20]}],
        }

        agreed_result = enhancer.review_quantity(agreed)
        conflict_result = enhancer.review_quantity(conflict)

        self.assertEqual(("consistent_candidate", "250ml", True), (agreed_result["status"], agreed_result["proposed_quantity"], agreed_result["manual_review_required"]))
        self.assertEqual(("conflict", "", True), (conflict_result["status"], conflict_result["proposed_quantity"], conflict_result["manual_review_required"]))

    def test_quantity_normalization_does_not_invent_units_or_reverse_ranges(self) -> None:
        self.assertEqual("50g", enhancer.normalize_quantity_candidate(" ５０ g "))
        self.assertEqual("1-2勺", enhancer.normalize_quantity_candidate("1～2 勺"))
        self.assertEqual("", enhancer.normalize_quantity_candidate("50"))
        self.assertEqual("", enhancer.normalize_quantity_candidate("3-1g"))
        self.assertEqual("", enhancer.normalize_quantity_candidate("O ml"))


if __name__ == "__main__":
    unittest.main()
