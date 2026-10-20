import json
import math
from .energy_reference import bmr_bounds, energy_reference_text
from .training_energy import training_expenditure
from datetime import datetime, timezone, timedelta
from .quantity_first import apply_quantity_priority
from .gram_display import attach_gram_display
from collections import defaultdict
from pathlib import Path
from .athlete import evaluate_athlete, display_number
from .food_standards import evaluate_food_standards
from .report_checks import build_overall_suggestions, check_report_consistency, energy_summary

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
        # Keep the established outward totals while comparing personal targets
        # against unrounded sums; display rounding must not create a deficit.
        athlete_nutrition = {**nutrition_total, **nutrition_total['exact_totals']}
        athlete, suggestions = evaluate_athlete(user, athlete_nutrition, category_result, self.athlete_config)
        food_standard = evaluate_food_standards(front_json, self.food_db, self.athlete_config)
        if not food_standard['nutrient_record_complete']:
            suggestions = []
            for row in athlete['rows']:
                row.update(gap=None, machine_evaluation='-', evaluation='-')
            nutrition_total['calcium']['evaluation'] = '-'
            nutrition_total['energy']['evaluation'] = '-'
        priority_notes, meat_message = apply_quantity_priority(
            nutrition_total, athlete, food_standard, food_details, self.food_db, category_result, self.athlete_config, merged_meals=merged_meals)
        energy_gate = food_standard['energy_gate']
        # Total energy is descriptive only: it never suppresses macro findings.
        suggestions = priority_notes + suggestions
        attach_gram_display(dict(nutrition=nutrition_total, athlete_evaluation=athlete, food_standard_evaluation=food_standard, foods=food_details), self.food_db, merged_meals)
        category_keys = {'nuts': '坚果', 'beans_energy': '豆类', 'tubers_energy': '薯类',
                         'grains_remainder': '谷类', 'milk': '奶类', 'eggs': '蛋类',
                         'seafood': '水产品', 'livestock_remainder': '畜禽肉',
                         'fruit': '水果', 'vegetables': '蔬菜', 'snacks': '零食'}
        # Keep table order intact; put quality protein before other food suggestions.
        for row in sorted(food_standard['rows'], key=lambda r: r['key'] != 'quality_protein'):
            category = category_keys.get(row['key'])
            if category in category_result:
                category_result[category]['evaluation'] = ({'不足': '能量占比偏低', '过多': '能量占比偏高', '适中': '能量占比适中'}.get(row['evaluation'], row['evaluation']) if row.get('evaluation_basis') == 'ratio' and row['key'] in {'beans_energy', 'tubers_energy', 'grains_remainder'} else row['evaluation'])
                if row['key'] == 'milk':
                    category_result[category]['equivalent_value'] = row['actual']
                elif row.get('representative') and row.get('conversion_basis'):
                    category_result[category]['reference_equivalent'] = dict(
                        value=row['actual'], representative=row['representative'],
                        basis=row['conversion_basis'])
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
                    category_result[category]['evaluation'] = ({'不足': '能量占比偏低', '过多': '能量占比偏高', '适中': '能量占比适中'}.get(row['evaluation'], row['evaluation']) if row.get('evaluation_basis') == 'ratio' and row['key'] in {'beans_energy', 'tubers_energy', 'grains_remainder'} else row['evaluation'])
            next(r for r in athlete['rows'] if r['key'] == 'vegetables')['evaluation'] = vegetable['evaluation']

        generated = datetime.now(timezone(timedelta(hours=8)))
        report = {
            "user": user,
            "date": front_json.get("date"),
            "generated_date": generated.date().isoformat(),
            "generated_at": generated.strftime('%Y-%m-%d %H:%M:%S'),
            "include_quality_page": front_json.get("include_quality_page") is True,
            "foods": food_details,
            "category_result": category_result,
            "suggestions": suggestions,
            "nutrition": nutrition_total,
            "athlete_evaluation": athlete,
            "food_standard_evaluation": food_standard,
            "personal_targets": food_standard.get("personal_targets", {}),
            "autoEvaluation": auto_evaluation,
            "unmatched_foods": unmatched_foods,
            "food_data_source": dict(self.food_data_source),
            "nutrition_disclaimer": DIET_RECORD_ONLY_DISCLAIMER,
            "energy_guidance": '',
        }

        # OCR 适配器写入的可追溯信息原样带到报告构建数据中。
        for key in ("source_person_id", "source_foods", "conversion_warnings", "blank_food_policy"):
            if key in front_json:
                report[key] = front_json[key]

        if interpretation is not None:
            report["interpretation"] = interpretation

        # Do not hide a blocked assessment behind the optional OCR-quality page.
        # Keep the established non-convertible-unit gate and all manual values.
        report['assessment_status'] = 'ready' if food_standard['nutrient_record_complete'] else 'needs_review'
        report['assessment_issues'] = []
        if report['assessment_status'] == 'needs_review':
            blocking_codes = {'unresolved_period', 'missing_quantity', 'unsupported_quantity_unit',
                              'missing_次数', 'invalid_次数', 'negative_value', 'invalid_quantity',
                              'missing_食用量', 'unmapped_food', 'invalid_food_row', 'missing_food_name'}
            report['assessment_issues'] = list(dict.fromkeys(
                w['message'] for w in front_json.get('conversion_warnings', [])
                if w.get('code') in blocking_codes and w.get('message')))
            report['assessment_issues'].extend(f"{w.get('name', '未知食物')}未匹配营养库" for w in unmatched_foods)
            report['assessment_issues'].extend(
                f"{item['food']}缺少有效营养参数 {item['nutrient']}"
                for item in food_standard.get('missing_nutrient_parameters', []))
            if not report['assessment_issues']:
                report['assessment_issues'] = ['存在缺少营养参数或无法换算的食物条目，请核对原始记录。']
            review_note = '待核对，暂不作为完整营养结论：' + '；'.join(report['assessment_issues'])
            report['energy_guidance'] = review_note + '。补齐这些条目的克数或容量后，才能评价全天能量、蛋白质及主食总量。'
            # Blocking issues are displayed separately, not as a 15th advice item.

        attach_gram_display(report, self.food_db, merged_meals)
        if report['assessment_status'] == 'ready':
            report['energy_guidance'] = energy_summary(report) + '各类食物按个人营养目标与实际摄入独立比较，不按总能量方向统一增减主食。'
        # One shared 17-item structure for all energy states; explicit manual
        # advice remains verbatim and receives a separate consistency warning.
        if auto_evaluation or 'overallSuggestions' not in (front_json.get('manualEvaluations') or {}):
            report['suggestion_items'] = build_overall_suggestions(report)
            report['suggestions'] = [item['text'] for item in report['suggestion_items']]
        else:
            report['suggestion_items'] = []
        check_report_consistency(report)
        for issue in report['assessment_issues']:
            report['report_checks']['warnings'].append('数据核查：' + issue)
            report['report_checks']['status'] = 'review'
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
        bounds = bmr_bounds(user)
        resting = bounds
        training = training_expenditure(user, resting)
        if training['applied']:
            bounds = tuple(resting[i] + training['net_daily_kcal'][i] for i in (0, 1))
        energy_standard = self._lookup_energy_eer(user) if bounds is None else None
        energy_eval = self._eval_energy_against_standard(total_energy, energy_standard)
        activity = str(user.get('activityLevel', '')).strip()
        activity_label = self.female_eer.get('activity_levels', {}).get(activity, {}).get('label', '')
        standard_note = ('kcal/天 · 女性EER（按活动量）' if energy_standard is not None else
                         '请选择活动量' if not activity else '请核对年龄、性别与活动量')

        if bounds is not None:
            low, high = bounds
            energy_standard = f'{low:g}-{high:g}'
            energy_eval = '过少' if total_energy < low else '过多' if total_energy > high else '适宜'
            standard_note = 'kcal/天 · BMR建议能量区间（按填写上下限）'
            if training['applied']:
                standard_note = 'kcal/天 · 静息代谢＋日均运动净消耗（计划估算，非完整全天总消耗）'
            activity_label = ''

        nutrition_total = {
            "energy": {
                "value": round(total_energy, 2),
                "standard": energy_standard,
                "evaluation": energy_eval,
                "standard_source": ('静息代谢＋运动净消耗' if training['applied'] else 'BMR建议能量区间') if bounds is not None else self.female_eer['title'],
                "reference_type": 'bmr_plus_net' if training['applied'] else 'bmr' if bounds is not None else 'eer',
                "resting_bounds": list(resting) if resting is not None else None,
                "training_expenditure": training,
                "standard_min": bounds[0] if bounds is not None else None,
                "standard_max": bounds[1] if bounds is not None else None,
                "standard_note": standard_note,
                "activity_label": activity_label,
            },
            "protein": round(total_protein, 2),
            "fat": round(total_fat, 2),
            "carbohydrate": round(total_carb, 2),
            "exact_totals": {"protein": total_protein, "fat": total_fat, "carbohydrate": total_carb},
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

        if not math.isfinite(value) or not math.isfinite(standard) or value < 0 or standard <= 0:
            return "-"

        ratio = value / standard
        if ratio < under_ratio:
            return rules.get("under_label", "过少")
        if ratio <= over_ratio:
            return rules.get("adequate_label", "适宜")
        return rules.get("over_label", "过多")

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
                "evaluation": "-"
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
