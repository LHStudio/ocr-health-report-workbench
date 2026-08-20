from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nutrition_report import FoodDataResult, NutritionReportService, clear_food_data_cache, resolve_food_data  # noqa: E402


class NutritionCloudSourceTest(unittest.TestCase):
    def tearDown(self) -> None:
        clear_food_data_cache()

    def test_cloud_values_are_used_by_nutrition_calculation(self) -> None:
        source = FoodDataResult(
            foods={
                "米饭": {
                    "category": "谷类", "energy": 999, "protein": 8,
                    "fat": 7, "carbohydrate": 6, "calcium": 5,
                }
            },
            metadata={
                "kind": "cloud", "label": "云端食物营养库", "cloud_available": True,
                "message": "营养数据来源：云端食物营养库", "queried_at": "2026-07-21T16:00:00+08:00",
                "base_url": "https://example.test/api/trophic", "error": "",
            },
        )
        report = NutritionReportService(food_data=source).build_report_data({
            "user": {}, "meals": [{"name": "米饭", "amount": 100}],
        })

        self.assertEqual(999.0, report["nutrition"]["energy"]["value"])
        self.assertEqual("cloud", report["food_data_source"]["kind"])
        self.assertEqual("云端食物营养库", report["foods"][0]["data_source"])

    def test_cloud_failure_falls_back_locally_with_visible_message(self) -> None:
        def unavailable(**_kwargs):
            raise ConnectionError("测试连接被拒绝")

        result = resolve_food_data(
            base_url="https://unavailable.example/api/trophic",
            cache_ttl_seconds=0,
            fetcher=unavailable,
        )

        self.assertEqual("local", result.metadata["kind"])
        self.assertFalse(result.metadata["cloud_available"])
        self.assertIn("云端无法访问", result.metadata["message"])
        self.assertIn("测试连接被拒绝", result.metadata["error"])
        self.assertIn("米饭", result.foods)

    def test_cloud_result_is_cached(self) -> None:
        calls = []

        def fetch_once(**_kwargs):
            calls.append(1)
            return {"测试食物": {"category": "谷类", "energy": 1}}

        first = resolve_food_data(base_url="https://cache.example/api/trophic", fetcher=fetch_once)
        second = resolve_food_data(base_url="https://cache.example/api/trophic", fetcher=fetch_once)

        self.assertEqual(1, len(calls))
        self.assertFalse(first.metadata["cache_hit"])
        self.assertTrue(second.metadata["cache_hit"])


if __name__ == "__main__":
    unittest.main()
