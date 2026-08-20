from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import local_service as service  # noqa: E402
from scripts import rebuild_nutrition_job as rebuild  # noqa: E402


def person_fixture() -> dict:
    person = service.nutrition_blank_person("ocr/fixture")
    person["food_rows"] = [
        {
            "食物编号": "1.1",
            "食物名称": "米饭",
            "平均每次食用量": "50g",
            "次数": "",
            "频率周期(请核对)": "未识别",
            "是否不吃": "",
            "OCR原始行": "1.1米饭 | 50g |  | 2 | 3 |  |",
            "人工核对备注": "多个频率列同时有正数：每周=2、每月=3",
        }
    ]
    return person


class NutritionRebuildAuditTest(unittest.TestCase):
    def test_visual_audits_layer_in_order_and_can_keep_evidence_only_rows(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root / "first.json"
            second = root / "second.json"
            first.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "person": "ocr/fixture",
                                "code": "1.1",
                                "visual_class": "handwriting_or_conflict",
                                "suggested_period": "每周",
                                "suggested_count": "2",
                                "confidence": 0.9,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            second.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "person": "ocr/fixture",
                                "code": "1.1",
                                "suggested_count": "3",
                            },
                            {
                                "person": "ocr/fixture",
                                "code": "2.1",
                                "apply": False,
                                "visual_class": "confirmed_value",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            indexed = rebuild.load_food_visual_audits([first, second])

        self.assertEqual("每周", indexed["ocr/fixture"]["1.1"]["suggested_period"])
        self.assertEqual("3", indexed["ocr/fixture"]["1.1"]["suggested_count"])
        self.assertNotIn("2.1", indexed["ocr/fixture"])

    def test_confirmed_value_applies_human_verified_period_and_count(self) -> None:
        person = person_fixture()
        person["food_rows"][0]["次数"] = "24"
        person["food_rows"][0]["频率周期(请核对)"] = "每周"
        person["food_rows"][0]["人工核对备注"] = "每周次数疑似异常“24”"
        visual = {
            person["id"]: {
                "1.1": {
                    "visual_class": "confirmed_value",
                    "visual_conclusion": "原图确认最终填写每月3-4次",
                    "suggested_period": "每月",
                    "suggested_count": "3-4",
                    "confidence": 0.98,
                }
            }
        }

        rebuild.apply_food_visual_audit(person, visual)

        row = person["food_rows"][0]
        self.assertEqual(("每月", "3-4", ""), (row["频率周期(请核对)"], row["次数"], row["人工核对备注"]))
        self.assertEqual("accepted_visual_confirmation", person["food_visual_audit"][0]["status"])

    def test_confirmed_value_requires_high_confidence_and_valid_period(self) -> None:
        person = person_fixture()
        visual = {
            person["id"]: {
                "1.1": {
                    "visual_class": "confirmed_value",
                    "suggested_period": "每周",
                    "suggested_count": "2",
                    "confidence": 0.7,
                }
            }
        }

        with self.assertRaises(ValueError):
            rebuild.apply_food_visual_audit(person, visual)

    def test_quantity_confirmation_is_orthogonal_to_period_confirmation(self) -> None:
        person = person_fixture()
        person["food_rows"][0]["平均每次食用量"] = "10050g"
        person["food_rows"][0]["人工核对备注"] = "食用量疑似异常“10050g”；多个频率列同时有正数"
        visual = {
            person["id"]: {
                "1.1": {
                    "visual_class": "confirmed_value",
                    "suggested_period": "每周",
                    "suggested_count": "2",
                    "confidence": 0.98,
                    "quantity_class": "confirmed_quantity",
                    "suggested_quantity": "100g",
                    "quantity_confidence": 0.99,
                }
            }
        }

        rebuild.apply_food_visual_audit(person, visual)

        row = person["food_rows"][0]
        self.assertEqual(("每周", "2", "100g", ""), (
            row["频率周期(请核对)"], row["次数"], row["平均每次食用量"], row["人工核对备注"]
        ))
        self.assertEqual(2, len(person["food_visual_audit"]))

    def test_confirmed_source_quantity_blank_stays_empty_without_review_note(self) -> None:
        person = person_fixture()
        person["food_rows"][0]["平均每次食用量"] = "瑞幸"
        person["food_rows"][0]["人工核对备注"] = "已识别进食频率，但食用量没有有效数字"
        visual = {
            person["id"]: {
                "1.1": {
                    "quantity_class": "confirmed_quantity_blank",
                    "quantity_confidence": 0.99,
                    "quantity_conclusion": "原件只写品牌，没有数量数字",
                }
            }
        }

        rebuild.apply_food_visual_audit(person, visual)

        row = person["food_rows"][0]
        self.assertEqual(("", ""), (row["平均每次食用量"], row["人工核对备注"]))
        self.assertEqual("confirmed_source_blank", person["food_visual_audit"][0]["status"])

    def test_cell_period_agreement_does_not_reopen_a_confirmed_quantity_blank(self) -> None:
        person = person_fixture()
        visual = {
            person["id"]: {
                "1.1": {
                    "visual_class": "handwriting_or_conflict",
                    "suggested_period": "每周",
                    "suggested_count": "2",
                    "confidence": 0.98,
                    "quantity_class": "confirmed_quantity_blank",
                    "quantity_confidence": 0.99,
                }
            }
        }
        cell = {
            person["id"]: {
                "1.1": {
                    "status": "accepted",
                    "selected_period": "每周",
                    "count": "2",
                    "reliable_counts": {"每周": ["2"]},
                    "text_by_period": {"每周": "2"},
                }
            }
        }

        rebuild.apply_food_visual_audit(person, visual)
        rebuild.apply_food_cell_audit(person, visual, cell)

        row = person["food_rows"][0]
        self.assertEqual(("每周", "2", "", ""), (
            row["频率周期(请核对)"], row["次数"], row["平均每次食用量"], row["人工核对备注"]
        ))

    def test_confirmed_blank_becomes_an_actual_empty_period(self) -> None:
        person = person_fixture()
        visual = {
            person["id"]: {
                "1.1": {
                    "visual_class": "true_blank",
                    "visual_conclusion": "五个频率格均为空",
                    "confidence": 0.99,
                }
            }
        }

        rebuild.apply_food_visual_audit(person, visual)

        row = person["food_rows"][0]
        self.assertEqual(("", "", "", ""), (row["频率周期(请核对)"], row["次数"], row["是否不吃"], row["人工核对备注"]))

    def test_confirmed_period_blank_preserves_a_filled_quantity(self) -> None:
        person = person_fixture()
        person["food_rows"][0]["平均每次食用量"] = "25g"
        visual = {
            person["id"]: {
                "1.1": {
                    "visual_class": "confirmed_period_blank",
                    "visual_conclusion": "数量有填写，但五个周期格均为空",
                    "confidence": 0.99,
                }
            }
        }

        rebuild.apply_food_visual_audit(person, visual)

        row = person["food_rows"][0]
        self.assertEqual(("25g", "", "", ""), (
            row["平均每次食用量"], row["频率周期(请核对)"], row["次数"], row["人工核对备注"]
        ))

    def test_high_confidence_visual_candidate_can_resolve_an_ocr_ink_conflict(self) -> None:
        person = person_fixture()
        visual = {
            person["id"]: {
                "1.1": {
                    "visual_class": "handwriting_or_conflict",
                    "visual_conclusion": "每月格是擦除痕迹，每周2清晰",
                    "suggested_period": "每周",
                    "suggested_count": "2",
                    "suggested_quantity": "50g",
                    "confidence": 0.93,
                }
            }
        }
        cell = {
            person["id"]: {
                "1.1": {
                    "status": "conflict",
                    "selected_period": "",
                    "count": "",
                    "reliable_counts": {"每周": ["2"]},
                    "text_by_period": {"每周": "2", "每月": ""},
                }
            }
        }

        rebuild.apply_food_visual_audit(person, visual)
        rebuild.apply_food_cell_audit(person, visual, cell)

        row = person["food_rows"][0]
        self.assertEqual(("每周", "2", ""), (row["频率周期(请核对)"], row["次数"], row["人工核对备注"]))
        self.assertEqual("accepted_agreement", person["food_cell_audit"][0]["status"])

    def test_disagreeing_cell_ocr_remains_for_manual_review(self) -> None:
        person = person_fixture()
        visual = {
            person["id"]: {
                "1.1": {
                    "visual_class": "handwriting_or_conflict",
                    "visual_conclusion": "倾向每周2",
                    "suggested_period": "每周",
                    "suggested_count": "2",
                    "confidence": 0.93,
                }
            }
        }
        cell = {
            person["id"]: {
                "1.1": {
                    "status": "accepted",
                    "selected_period": "每月",
                    "count": "3",
                    "reliable_counts": {"每月": ["3"]},
                    "text_by_period": {"每月": "3"},
                }
            }
        }

        rebuild.apply_food_visual_audit(person, visual)
        rebuild.apply_food_cell_audit(person, visual, cell)

        row = person["food_rows"][0]
        self.assertEqual("未识别", row["频率周期(请核对)"])
        self.assertIn("单元格 OCR", row["人工核对备注"])
        self.assertEqual("evidence_mismatch", person["food_cell_audit"][0]["status"])

    def test_two_ocr_variants_with_an_explicit_contradiction_do_not_auto_apply(self) -> None:
        person = person_fixture()
        visual = {
            person["id"]: {
                "1.1": {
                    "visual_class": "handwriting_or_conflict",
                    "visual_conclusion": "倾向每周2",
                    "suggested_period": "每周",
                    "suggested_count": "2",
                    "confidence": 0.95,
                }
            }
        }
        cells = {
            person["id"]: {
                "1.1": [
                    {
                        "image_variant": "ink",
                        "status": "conflict",
                        "reliable_counts": {"每周": ["2"]},
                        "text_by_period": {"每周": "2"},
                    },
                    {
                        "image_variant": "grayscale",
                        "status": "accepted",
                        "selected_period": "每月",
                        "count": "3",
                        "reliable_counts": {"每月": ["3"]},
                        "text_by_period": {"每月": "3"},
                    },
                ]
            }
        }

        rebuild.apply_food_visual_audit(person, visual)
        rebuild.apply_food_cell_audit(person, visual, cells)

        self.assertEqual("未识别", person["food_rows"][0]["频率周期(请核对)"])
        self.assertTrue(person["food_cell_audit"][0]["contradictory"])

    def test_food_name_provenance_alone_is_not_a_review_risk(self) -> None:
        self.assertFalse(service.nutrition_food_note_requires_review("OCR项目原文：果汁饮料、奶茶"))
        self.assertFalse(service.nutrition_food_note_requires_review("仅识别到 0（每天列“0”），按不吃处理"))
        self.assertFalse(service.nutrition_food_note_requires_review("食用量为 0，按不吃处理"))
        self.assertFalse(service.nutrition_food_note_requires_review("数量栏最终可读作550ml。"))
        self.assertTrue(service.nutrition_food_note_requires_review("OCR项目原文：果汁饮料；次数疑似异常"))

    def test_raw_cell_candidates_accept_chinese_one_and_trailing_stroke_noise(self) -> None:
        self.assertEqual(["1"], rebuild.raw_cell_count_candidates("一", "每天"))
        self.assertEqual(["1"], rebuild.raw_cell_count_candidates("1-", "每周"))
        self.assertEqual([], rebuild.raw_cell_count_candidates("48", "每周"))


if __name__ == "__main__":
    unittest.main()
