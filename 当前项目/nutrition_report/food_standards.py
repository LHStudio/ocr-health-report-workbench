"""用户2026-10-12新增标准；规则达标计数不是临床风险评分。"""
import math
from .report_policy import amount_status, DEFICIT, EXCESS
from .food_conversion import staple_equivalents
from collections import defaultdict
from .adapter import FOOD_REFERENCE_MAP


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError):
        return None


def evaluate_food_standards(payload, food_db, athlete_config=None):
    user = payload.get('user') or {}
    config = athlete_config or {}
    types = config.get('types', {})
    selected = str(user.get('athleteType') or '').strip()
    if not selected:
        project = str(user.get('projectType') or '').strip()
        selected = next((key for key, rule in types.items() if project in rule.get('projects', [])), '')
    vegetable_min = max(400, number(config.get('vegetables_g_min')) or 0,
                        number(types.get(selected, {}).get('vegetables_g_min')) or 0)
    weight = number(user.get('weight'))
    scale = number(user.get('foodTargetScale'))
    # These existing fixed targets and dimensionless ratios remain evaluable
    # outside 60-70 kg; only actual missing intake/denominators block scoring.
    # Retain an explicitly supplied >70 kg scaling factor, never invent one.
    scale = scale if weight and weight > 70 and scale is not None and scale >= 1 else 1
    notes = [
        '基础膳食参考标准',
        '主食等价总重=谷类原粮等价量+豆类大豆等价量+薯类记录重量；豆类至少5%、薯类至少15%，因此谷类占比上限为80%，不是必须达到80%。',
        '水产品占比按肉类日均重量计算；畜禽肉为肉类总量扣除水产品后的部分，包含畜肉和禽肉。',
        '奶粉、奶酪折算鲜奶等价量=记录克数×该食物每100g蛋白质/鲜奶每100g蛋白质；鲜奶、酸奶按原重。折算只用于奶量评价，营养素不重复计算。',
        '蔬菜最低400g/天，原有运动分类要求更高时取更高下限；采用最低量规则，不以先前500g封顶。',
        '优质蛋白=肉（含水产品）+蛋+奶的蛋白质克数/所有记录食物蛋白质克数；不含补充剂。',
        '每项定量规则达标记1、未达标记0、无法判断不计分；仅在全部定量项均可判断时显示达标率。谷类上限由豆类、薯类下限推导，达标率不作为医学综合评分。',
    ]
    totals = defaultdict(lambda: defaultdict(float))
    missing = set()
    missing_nutrient_parameters = []
    unknown_all = False
    source = payload.get('source_foods')
    blanks_are_zero = payload.get('blank_food_policy') == 'not_eaten'
    if source is not None:
        known = {row['food'] for row in source if 'food' in row}
        invalid = {w.get('food') for w in payload.get('conversion_warnings', []) if w.get('code') in
                   {'unresolved_period', 'missing_quantity', 'unsupported_quantity_unit', 'missing_次数',
                    'invalid_次数', 'negative_value', 'invalid_quantity', 'missing_食用量'}}
        known -= invalid
        for name, (reference, _) in FOOD_REFERENCE_MAP.items():
            if name in invalid:
                continue  # 无法换算的条目已由适配器排除，不阻断其他有效摄入的评价。
            if blanks_are_zero and name not in known and name not in invalid:
                continue  # 完成问卷未列出的食物也按未食用，不当作漏填。
            category = food_db.get(reference, {}).get('category')
            if not category:
                continue  # 无营养库映射的条目不参与计算，原因仍保留在换算记录中。
            elif name not in known:
                missing.add(category)
    milk_equivalent = 0
    milk_trace = []
    milk_protein = number(food_db.get('鲜奶', {}).get('protein'))
    for meal in payload.get('meals') or []:
        name = str(meal.get('name') or '')
        info = food_db.get(name)
        grams = number(meal.get('amount'))
        if not info and grams is not None and grams > 0 and name in {v[0] for v in FOOD_REFERENCE_MAP.values()}:
            # Explicitly selected reference missing from the API is missing
            # nutrient data, not an unmatched OCR row that may be skipped.
            unknown_all = True
            missing_nutrient_parameters.append(dict(food=name, nutrient='完整营养密度'))
            notes.append(f'{name}已指定为计算食物，但营养库缺少其密度；不能替换或按0计入完整营养结论。')
            continue
        if not info or grams is None:
            continue  # 与营养合计一致：忽略未匹配或无法换算的条目。
        category = info.get('category') or ''
        totals[category]['grams'] += grams
        if category == '奶类':
            if name in {'奶粉', '奶酪'} and grams:
                protein = number(info.get('protein'))
                if not milk_protein or protein is None:
                    missing.add('奶类')
                    milk_trace.append(f'{name}无法折算：鲜奶或该食品蛋白质数据缺失/鲜奶基准为0')
                else:
                    equivalent = grams * protein / milk_protein
                    milk_equivalent += equivalent
                    milk_trace.append(f'{name} {grams:g}g×{protein:g}/{milk_protein:g}={equivalent:.2f}g鲜奶等价量')
            else:
                milk_equivalent += grams
        # Every nutrient used by the report must be known for consumed foods.
        # Explicit finite zeros are valid; missing/invalid values are unknown,
        # not zero intake. Unmatched and unconvertible rows were skipped above.
        for nutrient in ('energy', 'protein', 'carbohydrate', 'fat', 'calcium'):
            value = number(info.get(nutrient))
            if value is None:
                missing.add(category)
                record = dict(food=name, nutrient=nutrient)
                if record not in missing_nutrient_parameters:
                    missing_nutrient_parameters.append(record)
                    notes.append(f'{name}缺少有效营养参数 {nutrient}；不能将未知参数当作0生成完整营养结论。')
            else:
                totals[category][nutrient] += value * grams / 100

    def complete(categories):
        return not unknown_all and not missing.intersection(categories)

    def total(categories, unit='grams'):
        return sum(totals[cat][unit] for cat in categories)

    rows = []

    def add(key, label, groups, low=None, high=None, ratio=None, target=None, note='', qualitative=None, actual_override=None, advisory=False, over_label='偏多'):
        is_ratio = ratio is not None
        unit = '%' if is_ratio else 'g/天'
        blocked = ''
        if not complete(groups):
            actual = None
            blocked = '-'  # 非空但无法换算的条目保留在换算说明，不误计为0。
        elif is_ratio:
            numerator, denominator = ratio
            actual = numerator / denominator * 100 if denominator > 0 else None
            if actual is None:
                blocked = '-'
        else:
            actual = actual_override if actual_override is not None else total(groups)
        lo = low * (1 if is_ratio else scale) if low is not None else None
        hi = high * (1 if is_ratio else scale) if high is not None else None
        if target is None:
            target = (f'≤ {hi:g}' if lo is None else f'{lo:g}–{hi:g}' if hi is not None else f'≥ {lo:g}') + ' ' + unit
        status, score, gap = blocked, None, None
        if advisory:
            # 通用建议/类别说明不依赖体重；不替无标准的类别编造定量评价。
            status = qualitative(actual)
            if blocked and blocked != '-':
                note = '；'.join(filter(None, (note, blocked)))
        elif not status:
            if qualitative is not None:
                status = qualitative(actual)
            else:
                status = amount_status(actual, lo, hi)
                score = 1 if status == '适中' else 0
                gap = actual - lo if status in DEFICIT else actual - hi if status in EXCESS else 0
                if status in EXCESS:
                    status = over_label
        rows.append(dict(key=key, label=label, actual=round(actual, 4) if actual is not None else None,
                         unit=unit, target=target, gap=round(gap, 4) if gap is not None else None,
                         score=score, machine_evaluation=status, evaluation=status, note=note, target_min=lo, target_max=hi))

    staples = {'谷类', '豆类', '薯类'}
    meat = {'畜禽肉', '水产品'}
    animal = meat | {'奶类', '蛋类'}
    equivalents = staple_equivalents(payload, food_db)
    staple_weight = sum(v for v in equivalents.values() if v is not None)
    if any(v is None for v in equivalents.values()):
        missing.update(staples)
    beans_min, tubers_min = 5, 15
    add('nuts', '坚果', {'坚果'}, 10)
    add('grains_remainder', '谷类占主食等价重量', staples, high=100-beans_min-tubers_min,
        ratio=(equivalents['谷类'] or 0, staple_weight), note='等价重量占比上限80%')
    add('tubers_energy', '薯类占主食等价重量', staples, tubers_min,
        ratio=(equivalents['薯类'] or 0, staple_weight), note='等价重量占比至少15%')
    add('beans_energy', '豆类占主食等价重量', staples, beans_min,
        ratio=(equivalents['豆类'] or 0, staple_weight), note='等价重量占比至少5%')
    for row in rows[-3:]:
        row['ratio_basis'] = 'equivalent_weight'
        row['denominator_g'] = staple_weight if all(v is not None for v in equivalents.values()) else None
    milk_note = (f'鲜奶基准蛋白质 {milk_protein:g} g/100g；' if milk_protein else '') + '；'.join(milk_trace)
    add('milk', '奶类鲜奶等价量', {'奶类'}, 400, note=milk_note or '鲜奶、酸奶原重；奶粉奶酪按蛋白质折算', actual_override=milk_equivalent)
    add('eggs', '蛋类', {'蛋类'}, 50, note='每个鸡蛋按50g；显式克数不二次折算')
    add('seafood', '水产品占肉类重量', meat, 30,
        ratio=(total({'水产品'}), total(meat)))
    add('livestock_remainder', '畜禽肉', meat, high=70,
        ratio=(total({'畜禽肉'}), total(meat)), note='占比上限=100%-水产品最低占比30%，不新增独立计分项')
    rows[-1]['score'] = None  # Same constraint as seafood, not a second scored rule.
    add('fruit', '水果', {'水果'}, 200, 500)
    add('vegetables', '蔬菜', {'蔬菜'}, vegetable_min,
        note=f'取400g与原有分类标准的较高值：{vegetable_min:g}g/天（基础体重）')
    add('snacks', '零食', {'零食'}, target='不建议吃零食',
        qualitative=lambda _: '不建议吃零食', advisory=True)
    all_categories = set(totals) | set(missing)
    add('quality_protein', '肉蛋奶优质蛋白占比', all_categories, 50,
        ratio=(total(animal, 'protein'), total(all_categories, 'protein')))
    judged = [r for r in rows if r['score'] is not None]
    passed = sum(r['score'] for r in judged)
    total_rules = len([r for r in rows if r['key'] not in {'livestock_remainder', 'snacks'}])
    summary = dict(passed=passed, evaluated=len(judged), total=total_rules,
                   attainment_percent=round(passed / total_rules * 100, 1) if len(judged) == total_rules else None)
    summary['text'] = f'定量规则达标 {passed}/{len(judged)} 项；可评价 {len(judged)}/{total_rules} 项。' + (
        f'完整达标率 {summary["attainment_percent"]:g}%（非医学综合评分）。' if len(judged) == total_rules else
        '存在未评价项，不给出总分或完整达标率。')
    if source is not None:
        proxies = sorted({r.get('food') for r in source if r.get('reference_exact') is False})
        if proxies:
            notes.append('代表食物估算（需复核）：' + '、'.join(proxies))
    return dict(source='用户新增膳食标准 2026-10-12', rows=rows, summary=summary, warnings=notes,
                nutrient_record_complete=not unknown_all and not missing,
                missing_nutrient_parameters=missing_nutrient_parameters)
