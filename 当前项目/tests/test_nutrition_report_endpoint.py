from __future__ import annotations

import shutil
import sys
import unittest
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import local_service  # noqa: E402


class NutritionReportEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.job_id = "nutrition-report-endpoint-test"
        self.job_dir = PROJECT_ROOT / "data" / "jobs" / self.job_id
        shutil.rmtree(self.job_dir, ignore_errors=True)
        self.person = {
            "id": "受试者:张三",
            "general": {"姓名": "张三", "调查日期": "2026-07-21"},
            "food_rows": [
                {"食物名称": "米饭", "平均每次食用量": "100g", "次数": "2", "频率周期(请核对)": "每天"},
            ],
        }
        local_service.JOBS[self.job_id] = {
            "kind": "nutrition", "status": "completed", "job_dir": self.job_dir, "people": [self.person],
        }

    def tearDown(self) -> None:
        local_service.JOBS.pop(self.job_id, None)
        shutil.rmtree(self.job_dir, ignore_errors=True)

    def test_reviewed_person_can_export_local_pdf_with_safe_filename(self) -> None:
        response = local_service.generate_nutrition_person_report(
            self.job_id,
            self.person["id"],
            {
                "person": self.person,
                "format": "pdf",
                "user_overrides": {"age": 22, "gender": "female", "activityLevel": "2", "weight": 55},
            },
        )

        reports = local_service.JOBS[self.job_id]["nutrition_reports"][self.person["id"]]
        report_path = self.job_dir / reports[0]["path"]
        self.assertEqual("application/pdf", response.media_type)
        self.assertTrue(report_path.is_file())
        self.assertEqual(b"%PDF", report_path.read_bytes()[:4])
        self.assertNotIn(":", report_path.name)
        self.assertEqual(1, reports[0]["usable_food_count"])

    def test_preview_returns_live_nutrition_values(self) -> None:
        result = local_service.preview_nutrition_person({
            "person": self.person,
            "user_overrides": {"age": 20, "gender": "male", "height": 168, "weight": 79, "activityLevel": "1"},
        })
        self.assertTrue(result["success"])
        self.assertEqual(1, result["usable_food_count"])
        self.assertGreater(result["preview"]["nutrition"]["energy"]["value"], 0)
        self.assertIsNone(result["preview"]["nutrition"]["energy"]["standard"])

    def test_body_based_export_supports_person_ids_with_slashes_and_timestamp_filename(self) -> None:
        self.person["id"] = "ocr/张三"
        local_service.JOBS[self.job_id]["people"] = [self.person]

        response = local_service.generate_nutrition_report(
            self.job_id,
            {"person": self.person, "format": "excel", "user_overrides": {"name": "新姓名"}},
        )

        encoded_name = response.headers.get("x-report-filename", "")
        from urllib.parse import unquote
        filename = unquote(encoded_name)
        self.assertRegex(filename, r"^新姓名_营养分析报告_[0-9a-f]{8}_\d{8}_\d{6}\.xlsx$")
        reports = local_service.JOBS[self.job_id]["nutrition_reports"]["ocr/张三"]
        self.assertTrue((self.job_dir / reports[0]["path"]).is_file())

    def test_export_uses_the_confirmed_manual_evaluation_payload(self) -> None:
        local_service.generate_nutrition_report(
            self.job_id,
            {
                "person": self.person,
                "format": "excel",
                "auto_evaluation": False,
                "manual_evaluations": {
                    "categoryEvaluations": {"谷类": "偏多"},
                    "energyEvaluation": "适宜",
                    "calciumEvaluation": "偏少",
                    "overallSuggestions": "人工建议",
                    "interpretation": "已人工复核",
                },
            },
        )
        reports = local_service.JOBS[self.job_id]["nutrition_reports"][self.person["id"]]
        self.assertEqual("manual_reviewed", reports[0]["evaluation_mode"])

    def test_completed_job_state_recovers_after_memory_clear(self) -> None:
        recovery_id = "a" * 32
        recovery_dir = PROJECT_ROOT / "data" / "jobs" / recovery_id
        shutil.rmtree(recovery_dir, ignore_errors=True)
        recovery_dir.mkdir(parents=True)
        persisted = {
            "kind": "nutrition", "status": "completed", "output_filename": "result.xlsx",
            "people": [self.person], "total_files": 1, "completed_files": 1,
            "message": "recovered", "output_relative": "output/result.xlsx",
        }
        (recovery_dir / "nutrition_job_state.json").write_text(json.dumps(persisted, ensure_ascii=False), encoding="utf-8")
        try:
            local_service.JOBS.pop(recovery_id, None)
            recovered = local_service.recover_nutrition_job(recovery_id)
            self.assertIsNotNone(recovered)
            self.assertEqual(self.person["id"], recovered["people"][0]["id"])
            self.assertEqual("/local-files/" + recovery_id + "/output/result.xlsx", recovered["output_url"])
        finally:
            local_service.JOBS.pop(recovery_id, None)
            shutil.rmtree(recovery_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
