import unittest
from nutrition_report.nutrition import NutritionService
from nutrition_report.adapter import _build_user


class AthleteInterventionTest(unittest.TestCase):
    def setUp(self):
        self.service = NutritionService(food_db={"测试": {"category": "蔬菜", "energy": 2000, "protein": 119, "fat": 40, "carbohydrate": 350, "calcium": 1000}})

    def report(self, **user):
        return self.service.build_report_data({"user": {"athleteType": "strength", "trainingPhase": "training", "age": 18, "weight": 70, **user}, "meals": [{"name": "测试", "amount": 100}]})

    def rows(self, **user):
        return {r["key"]: r for r in self.report(**user)["athlete_evaluation"]["rows"]}

    def test_strength_targets_and_exact_lower_boundary(self):
        rows = self.rows()
        self.assertEqual("119–140 g/天", rows["protein"]["target"])
        self.assertEqual("适中", rows["protein"]["evaluation"])
        self.assertEqual("约 350 g/天", rows["carbohydrate"]["target"])
        self.assertEqual("适中", rows["carbohydrate"]["evaluation"])

    def test_team_target_and_hidden_preferred_suggestion(self):
        rows = self.rows(athleteType="team")
        self.assertEqual("105–140 g/天", rows["protein"]["target"])
        self.assertEqual("约 490 g/天", rows["carbohydrate"]["target"])
        self.assertFalse(any("蛋白质优选参考" in s for s in self.report(athleteType="team")["suggestions"]))

    def test_endurance_has_no_protein_upper_limit(self):
        rows = self.rows(athleteType="endurance")
        self.assertEqual("≥ 84 g/天", rows["protein"]["target"])
        self.assertEqual("适中", rows["protein"]["evaluation"])
        self.assertEqual("560–700 g/天", rows["carbohydrate"]["target"])

    def test_age_boundary_and_calcium(self):
        self.assertEqual("≥ 1300 mg/天", self.rows(age=17)["calcium"]["target"])
        self.assertEqual("适中", self.rows(age=18)["calcium"]["evaluation"])
        self.assertEqual(-300, self.rows(age=17)["calcium"]["gap"])

    def test_invalid_and_missing_numbers_do_not_default(self):
        for invalid in (None, "", "NaN", "Infinity", -1, 0, "70kg"):
            with self.subTest(invalid=invalid):
                self.assertEqual("-", self.rows(weight=invalid)["protein"]["evaluation"])
                self.assertIsNone(self.rows(weight=invalid)["protein"]["gap"])
                self.assertEqual("-", self.rows(age=invalid)["calcium"]["evaluation"])
                self.assertIsNone(self.rows(age=invalid)["calcium"]["gap"])

    def test_phase_and_project_gates(self):
        for phase in ("competition", "other", ""):
            self.assertTrue(all(row["gap"] is None for key, row in self.rows(trainingPhase=phase).items() if key != 'vegetables'))
        self.assertEqual("-", self.rows(athleteType="", projectType="未知项目")["protein"]["evaluation"])
        self.assertTrue(any("待选择" in w for w in self.report(athleteType="", projectType="未知项目")["athlete_evaluation"]["warnings"]))
        self.assertEqual("105–140 g/天", self.rows(athleteType="", projectType="女足")["protein"]["target"])
        self.assertEqual("适中", self.rows(trainingPhase="", currentStatus="正常训练")["protein"]["evaluation"])

    def test_categories_use_food_rules_and_energy_needs_activity_profile(self):
        report = self.report()
        self.assertEqual("不足", report["category_result"]["蛋类"]["evaluation"])
        self.assertEqual("-", report["nutrition"]["energy"]["evaluation"])
        self.assertIsNone(report['nutrition']['energy']['standard'])
        self.assertEqual(-300, self.rows()["vegetables"]["gap"])
        vegetable = next(r for r in report['food_standard_evaluation']['rows'] if r['key']=='vegetables')
        self.assertEqual(-300, vegetable['gap'])

    def test_fat_percentage_and_zero_energy(self):
        row = self.rows()["fat"]
        self.assertAlmostEqual(40 * 9 / (119 * 4 + 350 * 4 + 40 * 9) * 100, row["actual"], places=2)
        report = self.service.build_report_data({"user": {"athleteType": "strength", "trainingPhase": "training"}})
        row = next(r for r in report["athlete_evaluation"]["rows"] if r["key"] == "fat")
        self.assertIsNone(row["actual"])

    def test_weight_changes_targets_and_preview_matches(self):
        self.assertEqual("136–160 g/天", self.rows(weight=80)["protein"]["target"])
        payload = {"user": {"weight": 70, "athleteType": "team", "trainingPhase": "training"}}
        self.assertEqual(self.service.build_report_data(payload), self.service.build_intake_preview(payload))

    def test_manual_evaluation_preserves_machine_trace(self):
        report = self.service.build_report_data({"user": {"weight": 70, "athleteType": "strength", "trainingPhase": "training"}, "autoEvaluation": False, "manualEvaluations": {"proteinEvaluation": "已复核"}})
        row = report["athlete_evaluation"]["rows"][0]
        self.assertEqual("不足", row["machine_evaluation"])
        self.assertEqual("已复核", row["evaluation"])

    def test_adapter_passes_new_fields(self):
        self.assertEqual("team", _build_user({}, {"athleteType": "team"})["athleteType"])
        self.assertEqual("training", _build_user({}, {"trainingPhase": "training"})["trainingPhase"])

    def test_manual_blank_clears_evaluation(self):
        report = self.service.build_report_data({"user": {"weight": 70, "athleteType": "strength", "trainingPhase": "training"}, "autoEvaluation": False, "manualEvaluations": {"proteinEvaluation": "", "calciumEvaluation": "", "categoryEvaluations": {"蔬菜": ""}}})
        rows = {r["key"]: r for r in report["athlete_evaluation"]["rows"]}
        for key in ("protein", "calcium", "vegetables"):
            self.assertEqual("", rows[key]["evaluation"])
            self.assertTrue(rows[key]["machine_evaluation"])
