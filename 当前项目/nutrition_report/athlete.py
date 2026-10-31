"""按用户提供的V2.0文档生成机器初稿；不推导文档未给出的评分阈值。"""
import math
from .report_policy import amount_status, DEFICIT, EXCESS
from .personal_targets import energy_bounds


def display_number(value):
    """只缩短报告文案；计算与边界判断仍使用原始精度。"""
    return f'{value:.1f}'.rstrip('0').rstrip('.')


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
            else:
                status = amount_status(actual, low, None if mode == 'minimum' else high)
                gap = actual - low if status in DEFICIT else actual - high if status in EXCESS else 0
        status = status if status in {"不足", "严重不足", "偏多", "适中"} else "-"
        rows.append(dict(key=key, label=label, actual=actual, unit=unit, target=target,
                         gap=gap, machine_evaluation=status, evaluation=status,
                         target_min=bounds[0] if bounds else None,
                         target_max=bounds[-1] if bounds and mode != 'minimum' else None))

    for key, label in (("protein", "蛋白质"), ("carbohydrate", "碳水化合物")):
        bounds = [round(n * weight, 4) for n in rule[key]] if rule and weight else None
        mode = "range" if bounds and len(bounds) == 2 else "minimum" if key == "protein" else "approx"
        add(key, label, nutrition[key], "g/天", bounds, mode, "待补充有效体重" if not weight else "")
    # Fat requirements use personal energy need, never recorded macro energy.
    energy_low, energy_high = energy_bounds(nutrition['energy'])
    fat_bounds = [energy_low * config['fat_energy_percent'][0] / 100 / 9,
                  energy_high * config['fat_energy_percent'][1] / 100 / 9] if energy_low and energy_high else None
    add("fat", "脂肪", nutrition['fat'], "g/天", fat_bounds,
        blocked='缺少有效个人能量需求，脂肪目标无法计算' if fat_bounds is None else '')
    if fat_bounds is None:
        warnings.append('缺少有效个人能量需求，脂肪目标无法计算；不以实际摄入反推。')
    calcium_target = config["calcium_mg"]["adult" if age and age >= config["adult_age"] else "minor"] if age else None
    add("calcium", "钙", nutrition["calcium"]["value"], "mg/天", [calcium_target] if age else None, "minimum", "待补充有效年龄" if not age else "")
    add("vegetables", "蔬菜", categories.get("蔬菜", {}).get("value", 0), "g/天", [config["vegetables_g_min"]], "minimum")
    for row in rows:
        row['target_planning'] = (rule['protein_preferred'] * weight
                                  if row['key'] == 'protein' and rule and rule.get('protein_preferred') and weight
                                  else row.get('target_min'))
    for category, info in categories.items():
        info["evaluation"] = "-"
    if "蔬菜" in categories:
        categories["蔬菜"]["evaluation"] = rows[-1]["evaluation"]
    # 能量独立采用现有女性EER活动量标准，不被专项V2规则覆盖。
    nutrition["calcium"]["evaluation"] = rows[-2]["evaluation"]
    suggestions = []
    for row in rows:
        if row['key'] == 'vegetables':
            continue  # 新增膳食标准统一生成蔬菜建议，避免沿用旧400g阈值。
        if row["gap"] is not None and row["gap"] < 0:
            unit = '个百分点' if row['unit'] == '%' else row['unit']
            suggestions.append(f"{row['label']}较参考{'目标' if row['key'] == 'carbohydrate' and len(rule['carbohydrate']) == 1 else '下限'}少 {display_number(abs(row['gap']))} {unit}。")
        elif row["evaluation"] in EXCESS:
            suggestions.append(f"{row['label']}高于参考上限，建议适当减少相关食物摄入。")
    if not reason and rule.get("protein_preferred") and weight:
        suggestions.append(f"团体项目蛋白质优选参考约 {display_number(rule['protein_preferred'] * weight)} g/天（1.7 g/kg）。")
    return dict(source=config["source"], scope=config["scope"], athlete_type=selected,
                athlete_label=rule["label"] if rule else "未确认", training_phase=phase,
                warnings=warnings, rows=rows, targets_applicable=not reason and bool(rule and weight),
                gap_note="差值=实际摄入−个人参考目标/边界；负值为不足，区间内为0。脂肪按个人能量需求折算克数。钙和蔬菜仅比较下限，不判断过量。"), suggestions
