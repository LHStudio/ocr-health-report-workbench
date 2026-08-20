from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import local_service  # noqa: E402


class NutritionSunlightCvMappingTests(unittest.TestCase):
    def test_sunlight_cv_results_fill_blank_general_fields(self) -> None:
        person = local_service.nutrition_blank_person("ocr/fixture")
        data = {
            "structured": {
                "questionnaire": {
                    "sunlight": {
                        "time": {"selected": ["下午3点之后"]},
                        "body_parts": {"selected": ["胳膊", "腿"]},
                    }
                }
            },
            "visual_elements": [
                {"label": "晒太阳时段-下午3点之后", "selected": True},
                {"label": "皮肤暴露部位-胳膊", "selected": True, "multi_select": True},
            ],
        }

        local_service.apply_cloud_questionnaire_result(data, person)

        self.assertEqual("下午3点之后", person["general"]["晒太阳时段"])
        self.assertEqual("胳膊、腿", person["general"]["皮肤暴露部位"])
        self.assertEqual(2, len(person["checkbox_review"]))

    def test_sunlight_cv_does_not_override_zero_sunlight(self) -> None:
        person = local_service.nutrition_blank_person("ocr/fixture")
        person["general"]["每日户外日照时长(小时)"] = "0"
        data = {
            "structured": {"questionnaire": {"sunlight": {"time": {"selected": ["下午3点之后"]}, "body_parts": {"selected": ["腿"]}}}},
            "visual_elements": [],
        }

        local_service.apply_cloud_questionnaire_result(data, person)

        self.assertEqual("", person["general"]["晒太阳时段"])
        self.assertEqual("", person["general"]["皮肤暴露部位"])


if __name__ == "__main__":
    unittest.main()
