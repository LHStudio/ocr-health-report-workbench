from __future__ import annotations

import html
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import local_service as service  # noqa: E402


JOB_DIR = PROJECT_ROOT / "data" / "jobs" / "56a4e5bfae7e4cbab27320624a475b84"


def html_table(rows: list[list[object]]) -> str:
    body = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(str(value))}</td>" for value in row)
        body.append(f"<tr>{cells}</tr>")
    return f"<table>{''.join(body)}</table>"


def parsed_saved_people() -> list[dict]:
    markdown_root = JOB_DIR / "ocr_markdown"
    excel_root = JOB_DIR / "ocr_excel"
    people: list[dict] = []
    person_dirs = [path for path in markdown_root.rglob("*") if path.is_dir() and path.name.isdigit()]
    for person_dir in sorted(person_dirs, key=lambda path: int(path.name)):
        person = service.nutrition_blank_person(f"ocr/{person_dir.name}")
        for markdown_path in sorted(person_dir.glob("*_ocr.md")):
            relative = markdown_path.relative_to(markdown_root)
            excel_path = excel_root / relative.with_suffix(".xlsx")
            markdown_parsed = service.parse_nutrition_markdown(markdown_path.read_text(encoding="utf-8"))
            excel_parsed = service.parse_nutrition_excel(excel_path.read_bytes())
            if not markdown_parsed["food_rows"]:
                markdown_parsed["food_rows"] = excel_parsed["food_rows"]
            if not markdown_parsed["supplement_rows"]:
                markdown_parsed["supplement_rows"] = excel_parsed["supplement_rows"]
            person["food_rows"].extend(markdown_parsed["food_rows"])
            person["supplement_rows"].extend(markdown_parsed["supplement_rows"])
        service.finalize_nutrition_person(person)
        people.append(person)
    return people


class NutritionParserRegressionTest(unittest.TestCase):
    def test_full_saved_job_has_fixed_39_by_38_and_39_by_5_structure(self) -> None:
        if not JOB_DIR.is_dir():
            self.skipTest("The checked-in 39-person nutrition OCR fixture is unavailable")

        people = parsed_saved_people()
        expected_food = list(service.NUTRITION_FOOD_ITEMS.items())
        expected_supplements = list(service.NUTRITION_SUPPLEMENT_ITEMS)

        self.assertEqual(39, len(people))
        self.assertEqual(39 * 38, sum(len(person["food_rows"]) for person in people))
        self.assertEqual(39 * 5, sum(len(person["supplement_rows"]) for person in people))
        for person in people:
            self.assertEqual(expected_food, [(row["食物编号"], row["食物名称"]) for row in person["food_rows"]])
            self.assertNotIn("7", [row["食物编号"] for row in person["food_rows"]])
            self.assertEqual(expected_supplements, [row["保健品种类"] for row in person["supplement_rows"]])
            self.assertFalse(any("版本号" in row["保健品种类"] for row in person["supplement_rows"]))

    def test_food_question_7_and_supplement_version_footer_are_filtered(self) -> None:
        markdown = "".join(
            [
                html_table(
                    [
                        ["食物名称", "平均每次食用量", "每天", "每周", "每月", "每年", "不吃"],
                        ["7.回忆在过去一年里，你是否服用过以下营养保健品"],
                        ["7.1牛肉", "50g", "", "2", "", "", ""],
                    ]
                ),
                html_table(
                    [
                        ["营养保健品种类", "保健品名称", "平均每次服用量", "每天", "每周", "每月", "每年", "不吃", "备注"],
                        ["版本号：20260317V1.0"],
                        ["鱼油", "", "", "", "", "", "", "0", ""],
                    ]
                ),
            ]
        )

        parsed = service.parse_nutrition_markdown(markdown)

        self.assertEqual(["7.1"], [row["食物编号"] for row in parsed["food_rows"]])
        self.assertEqual(["鱼油"], [row["保健品种类"] for row in parsed["supplement_rows"]])

    def test_ocr12_eight_column_food_rows_do_not_shift_left(self) -> None:
        markdown = html_table(
            [
                ["食物名称", "平均每次食用量", "每天", "每周", "每月", "每年", "不吃", ""],
                ["8鸡肉、鸭肉", "20g", "1", "", "", "", "", ""],
                ["9内脏类", "20g", "", "", "1", "", "", ""],
                ["12奶粉", "0勺", "", "", "", "", "", "0"],
            ]
        )

        rows = {row["食物编号"]: row for row in service.parse_nutrition_markdown(markdown)["food_rows"]}

        self.assertEqual(("20g", "1", "每天"), (rows["8"]["平均每次食用量"], rows["8"]["次数"], rows["8"]["频率周期(请核对)"]))
        self.assertEqual(("20g", "1", "每月"), (rows["9"]["平均每次食用量"], rows["9"]["次数"], rows["9"]["频率周期(请核对)"]))
        self.assertEqual(("0勺", "0", "不吃", "是"), (rows["12"]["平均每次食用量"], rows["12"]["次数"], rows["12"]["频率周期(请核对)"], rows["12"]["是否不吃"]))

    def test_zero_and_explicit_not_eat_marks_are_normalized(self) -> None:
        self.assertEqual(("不吃", "0"), service.choose_nutrition_period(["0", "", "", "", ""])[0:2])
        self.assertEqual(("不吃", "0"), service.choose_nutrition_period(["", "", "", "", "✓"])[0:2])
        self.assertEqual(("不吃", "0"), service.choose_nutrition_period(["", "", "", "", "0."])[0:2])

        positive_period, positive_count, notes = service.choose_nutrition_period(["", "3", "", "", "0"])
        self.assertEqual(("每周", "3"), (positive_period, positive_count))
        self.assertTrue(any("并存" in note for note in notes))

        inferred = service.normalize_food_row("12", "奶粉", "0勺", ["", "", "", "", ""], "12奶粉 | 0勺")
        self.assertIsNotNone(inferred)
        self.assertEqual(("不吃", "0", "是"), (inferred["频率周期(请核对)"], inferred["次数"], inferred["是否不吃"]))

        spaced = service.normalize_food_row("12", "奶粉", "0 勺", ["", "", "", "", ""], "12奶粉 | 0 勺")
        self.assertIsNotNone(spaced)
        self.assertEqual(("不吃", "0", "是"), (spaced["频率周期(请核对)"], spaced["次数"], spaced["是否不吃"]))

    def test_count_tokens_are_normalized_without_guessing(self) -> None:
        self.assertEqual("10", service.nutrition_count_value("10."))
        self.assertEqual("3", service.nutrition_count_value("3次"))
        self.assertEqual("1-2", service.nutrition_count_value("1^2次"))
        self.assertEqual("", service.nutrition_count_value("500ml"))

        period, count, notes = service.choose_nutrition_period(["1", "3", "", "", ""])
        self.assertEqual(("未识别", ""), (period, count))
        self.assertTrue(any("多个频率列同时有正数" in note for note in notes))

    def test_q1_and_q2_do_not_capture_the_next_question_number(self) -> None:
        blank_q1 = """1. 你一般每天吃几餐？___
2. 你一般每周在家吃几天饭？0.
3. 你一般早餐的就餐地点是？
（1）家 （2）学校食堂 （3）餐馆或街头 （4）不吃
"""
        fields = service.nutrition_general_from_text(blank_q1)
        self.assertNotIn("每日餐次", fields)
        self.assertEqual("0", fields["每周在家吃饭天数"])

        filled = """1. 你一般每天吃几餐？2-3
2. 你一般每周在家吃几天饭？3
3. 你一般早餐的就餐地点是？
"""
        fields = service.nutrition_general_from_text(filled)
        self.assertEqual("2-3", fields["每日餐次"])
        self.assertEqual("3", fields["每周在家吃饭天数"])

    def test_implausible_sunlight_values_are_rejected_and_reported(self) -> None:
        fields = service.nutrition_general_from_text(
            """8. 回忆在过去3个月里的日照情况：
（1）你每周有5-70天进行户外日照。
（2）你平均每天的户外日照时长是340小时。
"""
        )

        self.assertNotIn("每周户外日照天数", fields)
        self.assertNotIn("每日户外日照时长(小时)", fields)
        self.assertIn("5-70", fields["人工备注"])
        self.assertIn("340", fields["人工备注"])

    def test_first_questionnaire_page_name_wins_over_later_page_hallucination(self) -> None:
        candidates = []
        candidates.extend(service.first_page_name_candidates([("马元明", "姓名"), ("马元明", "解析字段")], 1))
        candidates.extend([("王小丽", "姓名"), ("王小丽", "解析字段")])

        self.assertEqual("马元明", service.choose_person_name(candidates))

    def test_merged_vitamin_calcium_and_extra_creatine_are_preserved_for_review(self) -> None:
        markdown = html_table(
            [
                ["营养保健品种类", "保健品名称", "平均每次服用量", "每天", "每周", "每月", "每年", "不吃", "备注"],
                ["维生素D钙", "钙D同补", "1片", "", "2", "", "", "", ""],
                ["肌酸", "1529"],
                ["版本号：20260317V1.0"],
            ]
        )
        parsed = service.parse_nutrition_markdown(markdown)
        person = service.nutrition_blank_person("fixture-person")
        person["supplement_rows"].extend(parsed["supplement_rows"])

        service.finalize_nutrition_person(person)

        rows = {row["保健品种类"]: row for row in person["supplement_rows"]}
        self.assertEqual(list(service.NUTRITION_SUPPLEMENT_ITEMS), list(rows))
        self.assertIn("维生素D与钙合并", rows["维生素D"]["备注"])
        self.assertIn("与维生素D合并", rows["钙"]["备注"])
        self.assertTrue(
            "肌酸" in rows["其他保健品(如蛋白粉)"]["保健品名称"]
            or "肌酸" in rows["其他保健品(如蛋白粉)"]["备注"]
        )
        self.assertFalse(any("版本号" in str(value) for row in rows.values() for value in row.values()))


if __name__ == "__main__":
    unittest.main()
