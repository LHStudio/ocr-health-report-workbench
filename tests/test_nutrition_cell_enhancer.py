from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import enhance_nutrition_cells as enhancer  # noqa: E402


class NutritionCellEnhancerTest(unittest.TestCase):
    def test_table_specifications_cover_all_food_codes(self) -> None:
        page1, page2 = enhancer.TABLE_SPECS

        self.assertEqual((18, 840, (184, 716), (1070, 1567)), (len(page1.codes), page1.output_height, page1.corners[0], page1.corners[2]))
        self.assertEqual((20, 920, (220, 165), (1103, 1092)), (len(page2.codes), page2.output_height, page2.corners[0], page2.corners[2]))
        self.assertEqual(900, page1.output_width)
        self.assertEqual(120, page1.header_height)
        self.assertEqual(40, page1.row_height)
        self.assertEqual((516, 602, 675, 748, 824, 900), enhancer.PERIOD_X_BOUNDARIES)
        self.assertEqual(enhancer.FOOD_CODES, page1.codes + page2.codes)
        self.assertEqual(set(enhancer.FOOD_CODES), set(enhancer.TABLE_BY_CODE))

    def test_blank_threshold_uses_max_new_ink_score(self) -> None:
        below = dict.fromkeys(enhancer.PERIODS, 0)
        below["每月"] = 11
        above = dict(below)
        above["每月"] = 16

        self.assertTrue(enhancer.is_blank_ink(below))
        self.assertFalse(enhancer.is_blank_ink(above))

    def test_quantity_zero_rule_is_literal_and_unit_bounded(self) -> None:
        self.assertTrue(enhancer.quantity_is_explicit_zero("0 勺"))
        self.assertTrue(enhancer.quantity_is_explicit_zero("0ml"))
        self.assertFalse(enhancer.quantity_is_explicit_zero("10ml"))
        self.assertFalse(enhancer.quantity_is_explicit_zero("O ml"))
        self.assertEqual(["1"], enhancer.count_candidates("1.", "每天"))

    def test_grayscale_variant_preserves_a_dark_handwritten_cell(self) -> None:
        cells = {period: np.full((30, 70), 255, dtype=np.uint8) for period in enhancer.PERIODS}
        cells["每周"][6:25, 28:36] = 35

        strip, mappings = enhancer.build_target_strip(cells, image_variant="grayscale")

        self.assertEqual((enhancer.OCR_CELL_HEIGHT, enhancer.OCR_BAND_WIDTH), strip.shape)
        self.assertEqual(enhancer.PERIODS, tuple(item["period"] for item in mappings))
        week_start = enhancer.OCR_CELL_WIDTH + enhancer.OCR_CELL_GAP
        self.assertLess(int(strip[:, week_start : week_start + enhancer.OCR_CELL_WIDTH].min()), 80)
        self.assertTrue(np.all(strip[:, : enhancer.OCR_CELL_WIDTH] == 255))

    def test_grayscale_source_does_not_depend_on_novel_ink_components(self) -> None:
        spec = enhancer.TABLE_SPECS[0]
        table = np.full((spec.output_height, spec.output_width), 255, dtype=np.uint8)
        x0, y0, x1, y1 = enhancer.period_cell_bounds(spec, 0, 0)
        table[y0 + 4 : y0 + 20, x0 + 20 : x0 + 27] = 80
        empty_ink = {period: np.zeros((y1 - y0, x1 - x0), dtype=np.uint8) for period in enhancer.PERIODS}

        grayscale = enhancer.select_ocr_period_cells(table, spec, 0, empty_ink, "grayscale")
        novel = enhancer.select_ocr_period_cells(table, spec, 0, empty_ink, "novel-ink")

        self.assertEqual(80, int(grayscale["每天"].min()))
        self.assertEqual(0, int(novel["每天"].max()))

    def test_nondefault_variants_use_separate_artifact_suffixes(self) -> None:
        self.assertEqual("", enhancer._artifact_suffix("novel-ink"))
        self.assertEqual("_grayscale", enhancer._artifact_suffix("grayscale"))

    def test_exactly_one_marked_period_and_count_is_accepted(self) -> None:
        ink = dict.fromkeys(enhancer.PERIODS, 0)
        ink["每周"] = 44
        items = {period: [] for period in enhancer.PERIODS}
        items["每周"] = [{"text": "1～2次", "score": 0.91}]

        result = enhancer.resolve_row(ink, items)

        self.assertEqual("accepted", result["status"])
        self.assertEqual("每周", result["selected_period"])
        self.assertEqual("1-2", result["count"])

    def test_multiple_marked_periods_remain_conflict(self) -> None:
        ink = dict.fromkeys(enhancer.PERIODS, 0)
        ink["每天"] = 31
        ink["每周"] = 28
        items = {period: [] for period in enhancer.PERIODS}
        items["每天"] = [{"text": "1", "score": 0.88}]
        items["每周"] = [{"text": "3", "score": 0.93}]

        result = enhancer.resolve_row(ink, items)

        self.assertEqual("conflict", result["status"])
        self.assertEqual("", result["selected_period"])
        self.assertEqual("", result["count"])

    def test_physical_not_eat_mark_is_accepted_without_ocr_guess(self) -> None:
        ink = dict.fromkeys(enhancer.PERIODS, 0)
        ink["不吃"] = 39
        items = {period: [] for period in enhancer.PERIODS}
        items["不吃"] = [{"text": "0.", "score": 0.97}]

        result = enhancer.resolve_row(ink, items)

        self.assertEqual(("accepted", "不吃", "0"), (result["status"], result["selected_period"], result["count"]))

    def test_not_eat_ink_without_explicit_zero_is_not_guessed(self) -> None:
        ink = dict.fromkeys(enhancer.PERIODS, 0)
        ink["不吃"] = 39
        items = {period: [] for period in enhancer.PERIODS}

        result = enhancer.resolve_row(ink, items)

        self.assertEqual("low_confidence", result["status"])
        self.assertTrue(result["manual_review_required"])

    def test_ocr_box_maps_to_person_code_and_frequency_cell(self) -> None:
        cells = []
        for index, period in enumerate(enhancer.PERIODS):
            x0 = index * (enhancer.OCR_CELL_WIDTH + enhancer.OCR_CELL_GAP)
            cells.append(
                {
                    "period": period,
                    "x_start": x0,
                    "x_end": x0 + enhancer.OCR_CELL_WIDTH,
                    "y_start": 200,
                    "y_end": 300,
                }
            )
        bands = [
            {
                "id": "ocr/7|20",
                "person": "ocr/7",
                "code": "20",
                "x_start": 0,
                "x_end": enhancer.OCR_BAND_WIDTH,
                "y_start": 200,
                "y_end": 300,
                "cells": cells,
            }
        ]
        month_x = 2 * (enhancer.OCR_CELL_WIDTH + enhancer.OCR_CELL_GAP)
        items = [
            {
                "text": "4",
                "score": 0.95,
                "box": [
                    [month_x + 30, 220],
                    [month_x + 80, 220],
                    [month_x + 80, 275],
                    [month_x + 30, 275],
                ],
            }
        ]

        mapped = enhancer.map_ocr_items(items, bands)

        self.assertEqual(1, len(mapped))
        self.assertEqual(("ocr/7", "20", "每月", "4"), tuple(mapped[0][key] for key in ("person", "code", "period", "text")))


if __name__ == "__main__":
    unittest.main()
