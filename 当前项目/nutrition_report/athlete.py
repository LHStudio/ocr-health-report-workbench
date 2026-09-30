"""按用户提供的V2.0文档生成机器初稿；不推导文档未给出的评分阈值。"""
import math


def positive_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def evaluate_athlete(user, nutrition, categories, config):
    types = config["types"]
    selected = str(user.get("athleteType") or "").strip()
    project = str(user.get("projectType") or "").strip()
    if not selected:
        selected = next((key for key, rule in types.items() if project in rule["projects"]), "")
    rule = types.get(selected)
    phase = str(user.get("trainingPhase") or "").strip()
    if not phase:
        phase = {"正常训练": "training", "训练期": "training", "比赛期": "competition", "赛期": "competition"}.get(str(user.get("currentStatus") or "").strip(), "")
    reason = "" if phase == "training" else ("仅适用训练期，当前阶段不适用" if phase else "待确认训练阶段")
    if not rule and not reason:
        reason = "待选择运动类型（未匹配项目不自动猜测）"
    weight = positive_number(user.get("weight"))
    age = positive_number(user.get("age"))
    warnings = [config["scope"], config["adult_age_note"]]
    if reason:
        warnings.append(reason)
    if not weight:
        warnings.append("缺少有效体重，蛋白质和碳水目标无法计算。")
    if not age:
        warnings.append("缺少有效年龄，钙目标无法计算。")
    rows = []

    def add(key, label, actual, unit, bounds=None, mode="range", blocked=""):
        status = reason or blocked
        target = "未提供标准"
        gap = None
        if bounds:
            low = bounds[0]
            high = bounds[-1]
            target = (f"约 {low:g}" if mode == "approx" else f"≥ {low:g}" if mode == "minimum" else f"{low:g}–{high:g}") + " " + unit
        if not status:
            if actual is None:
                status = "无法计算（供能合计为0）"
            elif mode == "approx":
                status = "参考目标（不判定达标）"
                gap = round(actual - low, 2)
            elif actual < low:
                status = "不足"
                gap = round(actual - low, 2)
            elif mode == "range" and actual > high:
                status = "偏高"
                gap = round(actual - high, 2)
            else:
                status = "达到参考下限" if mode == "minimum" else "适宜"
                gap = 0
        rows.append(dict(key=key, label=label, actual=actual, unit=unit, target=target,
                         gap=gap, machine_evaluation=status, evaluation=status))

    for key, label in (("protein", "蛋白质"), ("carbohydrate", "碳水化合物")):
        bounds = [round(n * weight, 4) for n in rule[key]] if rule and weight else None
        mode = "range" if bounds and len(bounds) == 2 else "minimum" if key == "protein" else "approx"
        add(key, label, nutrition[key], "g/天", bounds, mode, "待补充有效体重" if not weight else "")
    # 与现有报告三大营养素供能图一致：蛋白质4、碳水4、脂肪9 kcal/g。
    macro_energy = nutrition["protein"] * 4 + nutrition["carbohydrate"] * 4 + nutrition["fat"] * 9
    fat_percent = nutrition["fat"] * 9 / macro_energy * 100 if macro_energy > 0 else None
    add("fat", "脂肪供能比", fat_percent, "%", config["fat_energy_percent"])
    calcium_target = config["calcium_mg"]["adult" if age and age >= config["adult_age"] else "minor"] if age else None
    add("calcium", "钙", nutrition["calcium"]["value"], "mg/天", [calcium_target] if age else None, "minimum", "待补充有效年龄" if not age else "")
    add("vegetables", "蔬菜", categories.get("蔬菜", {}).get("value", 0), "g/天", [config["vegetables_g_min"]], "minimum")
    for row in rows:
        if row["actual"] is not None:
            row["actual"] = round(row["actual"], 2)
    for info in categories.values():
        info["evaluation"] = "文档未提供该类别标准"
    if "蔬菜" in categories:
        categories["蔬菜"]["evaluation"] = rows[-1]["evaluation"]
    nutrition["energy"].update(standard=None, evaluation="V2.0未提供总能量标准")
    nutrition["calcium"]["evaluation"] = rows[-2]["evaluation"]
    suggestions = []
    for row in rows:
        if row["gap"] is not None and row["gap"] < 0:
            suggestions.append(f"{row['label']}较参考{'目标' if row['key'] == 'carbohydrate' and len(rule['carbohydrate']) == 1 else '下限'}少 {abs(row['gap']):g} {row['unit']}，请结合训练及完整饮食记录复核调整。")
        elif row["evaluation"] == "偏高":
            suggestions.append(f"{row['label']}高于文档参考上限，请由营养专业人员复核调整。")
    if not reason and rule.get("protein_preferred") and weight:
        suggestions.append(f"团体项目蛋白质优选参考约 {rule['protein_preferred'] * weight:g} g/天（1.7 g/kg）。")
    return dict(source=config["source"], scope=config["scope"], athlete_type=selected,
                athlete_label=rule["label"] if rule else "未确认", training_phase=phase,
                warnings=warnings, rows=rows,
                gap_note="差值=实际摄入−参考目标/边界；负值为不足，区间内为0。脂肪差值单位为百分点。钙和蔬菜仅比较下限，不判断过量。"), suggestions
