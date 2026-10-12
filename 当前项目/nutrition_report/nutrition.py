import json
from collections import defaultdict
from pathlib import Path
from .athlete import evaluate_athlete, display_number
from .food_standards import evaluate_food_standards

DIET_RECORD_ONLY_DISCLAIMER = "以上营养成分仅根据记录饮食计算，不包含维生素、矿物质、蛋白粉等其他补充剂摄入。"


class NutritionService:
    """原营养项目的计算核心，改为使用包内资源且不依赖运行目录。"""

    def __init__(self, food_db_path=None, config_path=None, eer_path=None, *, food_db=None, food_data_source=None):
        package_root = Path(__file__).resolve().parent
        food_db_path = Path(food_db_path) if food_db_path else package_root / "data" / "food_db.json"
        config_path = Path(config_path) if config_path else package_root / "config" / "nutrition_template.json"
        eer_path = Path(eer_path) if eer_path else package_root / "config" / "female_energy_eer.json"

        if food_db is None:
            with open(food_db_path, "r", encoding="utf-8") as f:
                self.food_db = json.load(f)
        else:
            self.food_db = dict(food_db)
        self.food_data_source = dict(food_data_source or {})

        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        with open(eer_path, "r", encoding="utf-8") as f:
            self.female_eer = json.load(f)
        with open(package_root / "config" / "athlete_intervention_v2.json", encoding="utf-8") as f:
            self.athlete_config = json.load(f)

    def build_report_data(self, front_json):
        user = front_json.get("user", {})
        meals = front_json.get("meals", [])
        auto_evaluation = front_json.get("autoEvaluation", True)

        merged_meals = self._merge_meals(meals)
        food_details, nutrition_total, unmatched_foods = self._calculate_nutrition(merged_meals, user)
        category_result = self._build_category_result_from_foods(food_details)
        athlete, suggestions = evaluate_athlete(user, nutrition_total, category_result, self.athlete_config)
        food_standard = evaluate_food_standards(front_json, self.food_db, self.athlete_config)
        if not food_standard['nutrient_record_complete']:
            suggestions = []
            for row in athlete['rows']:
                row.update(gap=None, machine_evaluation='-', evaluation='-')
            nutrition_total['calcium']['evaluation'] = '-'
            nutrition_total['energy']['evaluation'] = '-'
        category_keys = {'nuts': '坚果', 'beans_energy': '豆类', 'tubers_energy': '薯类',
                         'grains_remainder': '谷类', 'milk': '奶类', 'eggs': '蛋类',
                         'seafood': '水产品', 'livestock_remainder': '畜禽肉',
                         'fruit': '水果', 'vegetables': '蔬菜', 'snacks': '零食'}
        for row in food_standard['rows']:
            category = category_keys.get(row['key'])
            if category in category_result:
                category_result[category]['evaluation'] = row['evaluation']
                if row['key'] == 'milk':
                    category_result[category]['equivalent_value'] = row['actual']
            if row['score'] == 0:
                evaluation = '超过上限' if row['evaluation'] == '超过' else row['evaluation']
                suggestions.append(f"{row['label']}{evaluation}：目前 {display_number(row['actual'])} {row['unit']}，参考目标 {row['target']}。")
        if suggestions:
            suggestions.append('请结合训练量和完整饮食记录，在营养专业人员指导下调整上述摄入。')
        # New food rules supersede the old vegetable-only rule, including scope/data gates.
        vegetable = next(r for r in food_standard['rows'] if r['key'] == 'vegetables')
        athlete['rows'] = [dict(vegetable) if r['key'] == 'vegetables' else r for r in athlete['rows']]
        athlete['gap_note'] = '差值=实际摄入−参考目标/边界；负值为不足，区间内为0。比值差值单位为百分点。蔬菜采用2026-10-12新增标准。'
        interpretation = None

        if not auto_evaluation:
            manual = front_json.get("manualEvaluations") or {}
            category_result, suggestions, nutrition_total, interpretation = (
                self._apply_manual_evaluations(
                    category_result, suggestions, nutrition_total, manual
                )
            )
            for row in athlete["rows"]:
                key = row["key"]
                if key == "vegetables":
                    row["evaluation"] = category_result.get("蔬菜", {}).get("evaluation", row["evaluation"])
                else:
                    field = f"{key}Evaluation"
                    if field in manual:
                        row["evaluation"] = str(manual[field] or "").strip()
            for row in food_standard['rows']:
                overrides = manual.get('standardEvaluations') or {}
                if row['key'] in overrides:
                    row['evaluation'] = str(overrides[row['key']] or '').strip()
                elif category_keys.get(row['key']) in (manual.get('categoryEvaluations') or {}):
                    row['evaluation'] = category_result[category_keys[row['key']]]['evaluation']
                category = category_keys.get(row['key'])
                if category in category_result:
                    category_result[category]['evaluation'] = row['evaluation']
            next(r for r in athlete['rows'] if r['key'] == 'vegetables')['evaluation'] = vegetable['evaluation']

        report = {
            "user": user,
            "date": front_json.get("date"),
            "foods": food_details,
            "category_result": category_result,
            "suggestions": suggestions,
            "nutrition": nutrition_total,
            "athlete_evaluation": athlete,
            "food_standard_evaluation": food_standard,
            "autoEvaluation": auto_evaluation,
            "unmatched_foods": unmatched_foods,
            "food_data_source": dict(self.food_data_source),
            "nutrition_disclaimer": DIET_RECORD_ONLY_DISCLAIMER,
        }

        # OCR 适配器写入的可追溯信息原样带到报告构建数据中。
        for key in ("source_person_id", "source_foods", "conversion_warnings", "blank_food_policy"):
            if key in front_json:
                report[key] = front_json[key]

        if interpretation is not None:
            report["interpretation"] = interpretation

        return report

    def build_intake_preview(self, front_json):
        """复用营养计算逻辑，返回各类摄入量与营养素合计（供手动评价参考）"""
        return self.build_report_data({**front_json, "autoEvaluation": True})
    def _apply_manual_evaluations(self, category_result, suggestions, nutrition_total, manual):
        category_evals = manual.get("categoryEvaluations") or {}
        for cat, info in category_result.items():
            if cat in category_evals:
                info["evaluation"] = str(category_evals[cat] or "").strip()

        if 'overallSuggestions' in manual:
            overall = str(manual.get("overallSuggestions", "")).strip()
            suggestions = [line.strip() for line in overall.splitlines() if line.strip()]

        energy_eval = str(manual.get("energyEvaluation", "")).strip()
        if "energyEvaluation" in manual:
            nutrition_total["energy"]["evaluation"] = energy_eval

        calcium_eval = str(manual.get("calciumEvaluation", "")).strip()
        if "calciumEvaluation" in manual:
            nutrition_total["calcium"]["evaluation"] = calcium_eval

        interpretation = str(manual.get("interpretation", "")).strip()

        return category_result, suggestions, nutrition_total, interpretation

    def _merge_meals(self, meals):
        meal_sum = defaultdict(float)

        for item in meals:
            name = str(item.get("name", "")).strip()
            amount = item.get("amount", 0)

            if not name:
                continue

            try:
                amount = float(amount)
            except Exception:
                amount = 0

            meal_sum[name] += amount

        return meal_sum

    def _calculate_nutrition(self, merged_meals, user=None):
        details = []
        unmatched_foods = []

        total_energy = 0.0
        total_protein = 0.0
        total_fat = 0.0
        total_carb = 0.0
        total_calcium = 0.0

        for food_name, grams in merged_meals.items():
            food_info = self.food_db.get(food_name)

            if not food_info:
                unmatched_foods.append({"name": food_name, "amount": round(grams, 1)})
                continue

            factor = grams / 100.0

            energy = self._safe_float(food_info.get("energy")) * factor
            protein = self._safe_float(food_info.get("protein")) * factor
            fat = self._safe_float(food_info.get("fat")) * factor
            carbohydrate = self._safe_float(food_info.get("carbohydrate")) * factor
            calcium = self._safe_float(food_info.get("calcium")) * factor

            total_energy += energy
            total_protein += protein
            total_fat += fat
            total_carb += carbohydrate
            total_calcium += calcium

            details.append({
                "name": food_name,
                "amount": round(grams, 1),
                "category": food_info.get("category", ""),
                "data_source": self.food_data_source.get("label", ""),
                "nutrition": {
                    "energy": round(energy, 2),
                    "protein": round(protein, 2),
                    "fat": round(fat, 2),
                    "carbohydrate": round(carbohydrate, 2),
                    "calcium": round(calcium, 2)
                }
            })

        user = user or {}
        energy_standard = self._lookup_energy_eer(user)
        energy_eval = self._eval_energy_against_standard(total_energy, energy_standard)
        activity = str(user.get('activityLevel', '')).strip()
        activity_label = self.female_eer.get('activity_levels', {}).get(activity, {}).get('label', '')
        standard_note = ('kcal/天 · 女性EER（按活动量）' if energy_standard is not None else
                         '请选择活动量' if not activity else '请核对年龄、性别与活动量')

        nutrition_total = {
            "energy": {
                "value": round(total_energy, 2),
                "standard": energy_standard,
                "evaluation": energy_eval,
                "standard_source": self.female_eer['title'],
                "standard_note": standard_note,
                "activity_label": activity_label,
            },
            "protein": round(total_protein, 2),
            "fat": round(total_fat, 2),
            "carbohydrate": round(total_carb, 2),
            "calcium": {
                "value": round(total_calcium, 2),
                "evaluation": "待专项评价"
            }
        }

        return details, nutrition_total, unmatched_foods

    def _lookup_energy_eer(self, user):
        gender = str(user.get("gender", "")).strip()
        if gender != "female":
            return None

        age = self._safe_float(user.get("age"), default=-1)
        weight = self._safe_float(user.get("weight"))
        activity = str(user.get("activityLevel", "")).strip()

        if age < 0 or not activity:
            return None

        age_group = None
        for group in self.female_eer.get("age_groups", []):
            if group["age_min"] <= age < group["age_max"]:
                age_group = group
                break

        if not age_group:
            return None

        level_data = age_group.get("levels", {}).get(activity)
        if not level_data:
            return None

        if level_data.get("type") == "per_kg":
            if weight <= 0:
                return None
            return round(level_data["kcal"] * weight, 1)

        standard = level_data["kcal"]

        stage = str(user.get("physiologicalStage", "")).strip()
        stages = self.female_eer.get("physiological_stages", {})
        if stage and stage in stages:
            standard += stages[stage].get("bonus_kcal", 0)

        return standard

    def _eval_energy_against_standard(self, value, standard):
        rules = self.female_eer.get("evaluation_rules", {})
        under_ratio = rules.get("under_ratio", 0.9)
        over_ratio = rules.get("over_ratio", 1.1)

        try:
            value = float(value)
            standard = float(standard)
        except Exception:
            return "-"

        if standard <= 0:
            return "-"

        ratio = value / standard
        if ratio < under_ratio:
            return rules.get("under_label", "不足")
        if ratio <= over_ratio:
            return rules.get("adequate_label", "适宜")
        return rules.get("over_label", "偏高")

    def _build_category_result_from_foods(self, food_details):
        # 1. 先把配置里的所有分类都初始化为 0
        category_sum = {
            category: 0.0
            for category in self.config["food_category_map"].keys()
        }

        # 2. 把实际食物摄入量累加进去
        for item in food_details:
            category = item.get("category", "").strip()
            amount = self._safe_float(item.get("amount", 0))

            if category in category_sum:
                category_sum[category] += amount

        # 3. 所有分类都生成评价结果
        result = {}
        for cat, val in category_sum.items():
            result[cat] = {
                "value": round(val, 1),
                "evaluation": "-" if cat in {"饮料", "酒类"} else "文档未提供该类别标准"
            }

        return result

    def _evaluate_category(self, category, value):
        rules = self.config["category_evaluation"].get(
            category,
            self.config["category_evaluation"].get("default", [])
        )

        for r in rules:
            if r["min"] <= value <= r["max"]:
                return r["label"]

        return "-"

    def _generate_suggestions(self, category_result):
        rules = self.config["suggestion_rules"]
        res = []

        for cat, info in category_result.items():
            label = info["evaluation"]
            if label in rules and rules[label]:
                res.append(rules[label].replace("{category}", cat))

        return res

    def _eval_nutrition(self, value, key):
        rules = self.config["nutrition_eval"][key]

        try:
            value = float(value)
        except Exception:
            return "-"

        for r in rules:
            if r["min"] <= value <= r["max"]:
                return r["label"]

        return "-"

    def _safe_float(self, value, default=0.0):
        try:
            return float(value)
        except Exception:
            return default
