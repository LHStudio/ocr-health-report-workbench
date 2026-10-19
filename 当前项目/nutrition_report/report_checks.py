"""Shared report advice and traceable, non-diagnostic pre-export consistency checks.

Checks never edit intake or manual conclusions. 3x reference and 3000 g/food/day
are engineering review triggers, NOT physiological or clinical upper limits.
"""
import math
import re


REVIEW_THRESHOLDS = {
    'reference_multiple': 3.0,
    'single_food_g_day': 3000.0,
    'basis': '报告数据质量工程筛查阈值；非医学上限，不据此判定录入错误。',
}


def finite_number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def energy_summary(report):
    value = (report.get('nutrition') or {}).get('energy', {}).get('evaluation')
    return {'适宜': '总能量适宜。', '适中': '总能量适宜。', '过多': '总能量过多。',
            '过少': '总能量过少。', '不足': '总能量过少。'}.get(value, '总能量暂无法评价。')


def _rows(report):
    result = {}
    for section in ('athlete_evaluation', 'food_standard_evaluation'):
        result.update({r['key']: r for r in (report.get(section) or {}).get('rows', [])})
    return result


def _number(value):
    value = finite_number(value)
    return f'{value:.1f}'.rstrip('0').rstrip('.') if value is not None else '未确认'


def _row_advice(row, label=None):
    if not row:
        return f'{label or "本项"}：个人参考目标或记录尚不完整，暂不判断增减。'
    label = label or row.get('label', row['key'])
    shown = {**row, **(row.get('display') or {})}
    status = row.get('evaluation') or '未确认'
    actual = finite_number(shown.get('actual'))
    if actual is None or status in {'-', '未确认'}:
        return f'{label}：目前摄入或个人参考目标尚不完整，暂不判断增减；参考目标 {shown.get("target", "未确认")}。'
    direction = ('应增加本类摄入' if status in {'不足', '过少', '偏低', '占比偏低', '能量占比偏低'}
                 else '应减少本类摄入' if status in {'过多', '偏高', '占比偏高', '能量占比偏高'}
                 else '保持在个人参考范围内' if status in {'适中', '适宜', '占比适中', '能量占比适中'}
                 else '结合完整记录和专业意见调整')
    if status in {'适中', '适宜'} and row.get('target_min') is not None and row.get('target_max') is None:
        direction = '已达到最低参考量；本规则不判断过量，请同时查看数据核查提醒'
    return f'{label}{status}：目前 {_number(actual)} {shown.get("unit", "")}，参考目标 {shown.get("target", "未确认")}；{direction}。'


def build_overall_suggestions(report):
    """The same 14 topics for every energy state; alerts remain outside this list."""
    rows = _rows(report)
    meat = ' '.join(_row_advice(rows.get(key), label) for key, label in (
        ('meat', '肉类（含水产品）'), ('seafood', '其中水产品'), ('livestock_remainder', '其中畜禽肉')))
    low_carb = (rows.get('carbohydrate') or {}).get('evaluation') in {'不足', '过少'}
    staple_parts = []
    for key, label in (('grains_remainder', '谷类'), ('beans_energy', '豆类'), ('tubers_energy', '薯类')):
        text = _row_advice(rows.get(key), label)
        if low_carb and (rows.get(key) or {}).get('evaluation') in {'过多', '偏高', '能量占比偏高'}:
            text = text.replace('应减少本类摄入', '本类超过计划分配；当前总碳水不足，优先补足不足的豆类、薯类等来源，不直接减少主食总碳水')
        staple_parts.append(text)
    staples = ' '.join(staple_parts)
    items = [('energy', energy_summary(report))]
    items += [(key, _row_advice(rows.get(key), label)) for key, label in (
        ('protein', '蛋白质'), ('carbohydrate', '碳水化合物'), ('fat', '脂肪'),
        ('calcium', '钙'), ('nuts', '坚果'))]
    items += [('staples', '主食各类别按个人碳水目标分配：' + staples)]
    items += [(key, _row_advice(rows.get(key), label)) for key, label in (
        ('milk', '奶类鲜奶等价量（按蛋白质估计）'), ('eggs', '蛋类'))]
    items += [('meat', meat)]
    items += [(key, _row_advice(rows.get(key), label)) for key, label in (
        ('fruit', '水果'), ('vegetables', '蔬菜'))]
    items += [('snacks', '零食：建议尽量不吃；不以零食替代正餐。'),
              ('quality_protein', _row_advice(rows.get('quality_protein'), '肉蛋奶优质蛋白') +
               ' 请结合训练量及完整记录，在营养专业人员指导下调整。')]
    return [{'key': key, 'text': text} for key, text in items]


_REDUCE_STAPLES = re.compile(r'(?:减少|控制|限制|下调).{0,12}(?:主食|碳水|谷类|豆类|薯类)|(?:主食|碳水|谷类|豆类|薯类).{0,12}(?:减少|控制|限制|下调)')
_INCREASE_STAPLES = re.compile(r'(?:增加|补足|补充|上调).{0,12}(?:主食|碳水)|(?:主食|碳水).{0,12}(?:增加|补足|补充|上调)')


def _unqualified_direction(text, pattern):
    for clause in re.split(r'[。；;\n]', text):
        for match in pattern.finditer(clause):
            context = clause[max(0, match.start()-12):match.end()]
            if not re.search(r'(?:不|勿|无需|避免).{0,10}(?:减少|控制|限制|下调|增加|补足|补充|上调)', context):
                return True
    return False


def check_report_consistency(report):
    """Run after manual overrides and displays are applied, before any export."""
    checks, warnings, corrections = [], [], []
    rebuild_advice = False
    automatic = report.get('autoEvaluation', True)
    rows = _rows(report)

    def add(code, key, message, **extra):
        record = dict(code=code, key=key, message=message, **extra)
        if not any(c['code'] == code and c['key'] == key for c in checks):
            checks.append(record)
            warnings.append(message)

    for key, row in rows.items():
        actual = finite_number(row.get('actual'))
        if row.get('actual') is not None and (actual is None or actual < 0):
            add('invalid_numeric', key, f'{row.get("label", key)}存在非有限值或负值，无法据此判断摄入；请核查原始数据。')
        lower, upper = finite_number(row.get('target_min')), finite_number(row.get('target_max'))
        if (row.get('evaluation_basis') == 'personal_target' or key in {'protein', 'carbohydrate', 'fat', 'calcium'}) and actual is not None and (lower is not None or upper is not None):
            # Exactly the planner's arithmetic epsilon, not a dietary tolerance.
            expected = ('不足' if lower is not None and actual < lower-1e-8 else
                        '过多' if upper is not None and actual > upper+1e-8 else '适中')
            if row.get('machine_evaluation') in {'不足', '过少', '过多', '适中', '适宜'} and row.get('machine_evaluation') != expected:
                if automatic:
                    before = row.get('evaluation')
                    row.update(machine_evaluation=expected, evaluation=expected,
                        gap=actual-lower if expected == '不足' else actual-upper if expected == '过多' else 0)
                    if row.get('display'):
                        row['display']['gap'] = row['gap']
                    category = {'grains_remainder':'谷类','beans_energy':'豆类','tubers_energy':'薯类',
                                'seafood':'水产品','livestock_remainder':'畜禽肉'}.get(key)
                    if category in report.get('category_result', {}):
                        report['category_result'][category]['evaluation'] = expected
                    if key == 'calcium':
                        report['nutrition']['calcium']['evaluation'] = expected
                    if row.get('score') is not None:
                        row['score'] = 1 if expected == '适中' else 0
                    corrections.append(dict(code='evaluation', key=key, before=before, after=expected))
                    rebuild_advice = True
                    add('machine_evaluation_corrected', key,
                        f'{row.get("label", key)}机器评价与个人目标数值不一致，已按实际摄入及目标边界纠正为“{expected}”；摄入数据未改写。')
                else:
                    add('manual_conflict', key, f'{row.get("label", key)}最终评价与个人目标边界计算“{expected}”不一致；保留人工结论，请复核。')
        reference = upper if upper is not None and upper > 0 else lower
        if actual is not None and reference and actual >= reference * REVIEW_THRESHOLDS['reference_multiple']:
            bound = '上沿' if upper is not None else '下限'
            add('extreme_intake', key,
                f'{row.get("label", key)}记录摄入 {_number(actual)} {row.get("unit", "")}，达到参考{bound}的 {_number(actual/reference)} 倍；触发数据核查提醒（≥3倍工程筛查阈值，非医学上限）。请核对份量、单位、频率和营养参数，不直接认定录入错误。',
                actual=actual, reference=reference, threshold=REVIEW_THRESHOLDS['reference_multiple'])
        if not automatic and row.get('evaluation') != row.get('machine_evaluation'):
            add('manual_conflict', key,
                f'{row.get("label", key)}人工结论“{row.get("evaluation", "")}”与机器计算“{row.get("machine_evaluation", "-")}”不同；已保留人工结论，请复核。')
        if key == 'meat':
            target = finite_number(row.get('target_grams'))
            if target is not None and target <= 0:
                add('zero_meat_target', key,
                    '肉类（含水产品）参考目标为0或负值，不能据此建议完全不吃肉；请核查个人蛋白质目标、计划蛋奶豆谷来源及分配可行性。')

    for key, value in (report.get('nutrition') or {}).items():
        raw = value.get('value') if isinstance(value, dict) else value
        numeric = finite_number(raw)
        if raw is not None and (numeric is None or numeric < 0):
            add('invalid_numeric', key, f'营养合计 {key} 存在非有限值或负值，请核查数据；未自动改写原始数值。')
    energy = (report.get('nutrition') or {}).get('energy') or {}
    actual = finite_number(energy.get('value'))
    ref = finite_number(energy.get('standard_max')) or finite_number(energy.get('standard'))
    if actual is not None and ref and report.get('assessment_status') != 'needs_review':
        low = finite_number(energy.get('standard_min')) if energy.get('reference_type') == 'bmr' else ref*.9
        high = ref if energy.get('reference_type') == 'bmr' else ref*1.1
        expected_energy = '过少' if low is not None and actual < low else '过多' if actual > high else '适宜'
        final_energy = {'适中':'适宜', '不足':'过少'}.get(energy.get('evaluation'), energy.get('evaluation'))
        if final_energy != expected_energy:
            if automatic:
                before = energy.get('evaluation')
                energy['evaluation'] = expected_energy
                corrections.append(dict(code='evaluation', key='energy', before=before, after=expected_energy))
                rebuild_advice = True
                add('machine_evaluation_corrected', 'energy',
                    f'总能量机器评价与既有能量参考边界不一致，已纠正为“{expected_energy}”；能量数值和参考上下限未修改。')
            else:
                add('manual_conflict', 'energy',
                    f'总能量人工结论“{energy.get("evaluation", "")}”与实际摄入及既有参考边界计算“{expected_energy}”不同；已保留人工结论，请复核。')
    if energy.get('reference_type') == 'bmr':
        add('bmr_reference_scope', 'energy',
            '当前能量比较沿用填写的BMR区间。BMR是静息代谢参考，不等于全天训练能量需要；未擅自乘活动系数或修改已填上下限，请由营养专业人员确认适用口径。')
    minima = [finite_number((rows.get(key) or {}).get('target_min')) for key in ('protein', 'carbohydrate', 'fat')]
    if all(v is not None for v in minima) and ref:
        minimum_energy = minima[0]*4 + minima[1]*4 + minima[2]*9
        if minimum_energy > ref:
            add('macro_energy_conflict', 'energy',
                f'个人蛋白质、碳水化合物和脂肪目标下限合计供能约 {_number(minimum_energy)} kcal/天，已超过当前能量参考上沿 {_number(ref)} kcal/天；两套标准不能同时满足，请核查训练量及BMR/EER口径，未自动削减营养目标。',
                macro_minimum_kcal=minimum_energy, energy_reference_upper=ref)
    if actual is not None and ref and actual >= ref * REVIEW_THRESHOLDS['reference_multiple']:
        add('extreme_intake', 'energy', f'总能量记录达到参考值的 {_number(actual/ref)} 倍；触发≥3倍工程筛查提醒，非医学上限，请核查份量、单位及频率。', actual=actual, reference=ref)
    for food in report.get('foods') or []:
        amount = finite_number(food.get('amount'))
        if amount is None or amount < 0:
            add('invalid_numeric', 'food:'+str(food.get('name')), f'{food.get("name", "食物")}记录量无效，请核查原始份量；未自动改写记录。')
        elif amount > REVIEW_THRESHOLDS['single_food_g_day']:
            add('extreme_intake', 'food:'+str(food.get('name')),
                f'{food.get("name", "食物")}日均记录 {_number(amount)} g 超过单项3000 g/天工程筛查阈值；请核查是否混淆生熟重、份量、单位或频率（非医学上限，不直接判定错误）。')

    plans = (report.get('food_standard_evaluation') or {}).get('personal_targets') or {}
    for index, message in enumerate(plans.get('plan_warnings') or []):
        add('target_plan_review', str(index), str(message))

    carb = rows.get('carbohydrate') or {}
    carb_state = carb.get('machine_evaluation') or carb.get('evaluation')
    if carb_state in {'不足', '过少'} and any((rows.get(key) or {}).get('machine_evaluation') == '过多'
                                             for key in ('grains_remainder', 'beans_energy', 'tubers_energy')):
        add('staple_mix_reallocation', 'staple_mix',
            '总碳水化合物不足但部分主食类别超过计划分配：应补足不足的来源并复核搭配，不直接按总能量或单类超量减少主食总碳水。类别数值评价和实际摄入保持不变。')
    conflict_pattern = _REDUCE_STAPLES if carb_state in {'不足', '过少'} else _INCREASE_STAPLES if carb_state == '过多' else None
    # Only total-staple / carbohydrate direction is checked. Reducing one grain
    # while increasing beans/tubers is a valid reallocation, not a contradiction.
    candidates = list(report.get('suggestions') or []) + [report.get('interpretation') or '']
    conflicts = [str(s) for s in candidates if conflict_pattern and _unqualified_direction(str(s), conflict_pattern)
                 and not str(s).startswith('主食各类别按个人碳水目标分配：')]
    if conflicts:
        if automatic:
            before = list(report.get('suggestions') or [])
            items = build_overall_suggestions(report)
            report['suggestion_items'] = items
            report['suggestions'] = [i['text'] for i in items]
            corrections.append(dict(code='staple_direction', before=before, after=list(report['suggestions'])))
            add('machine_advice_corrected', 'staples',
                '自动核查发现主食总量建议与碳水化合物评价方向矛盾，已按个人目标重建机器建议；实际摄入数据未改写。')
        else:
            add('manual_conflict', 'staples',
                f'人工主食总量建议与碳水化合物机器评价“{carb_state}”方向冲突；人工建议未自动改写，请复核。')

    if rebuild_advice:
        report['suggestion_items'] = build_overall_suggestions(report)
        report['suggestions'] = [item['text'] for item in report['suggestion_items']]

    report['report_checks'] = dict(version='2026-10-19', checks=checks,
        warnings=warnings, corrections=corrections, thresholds=dict(REVIEW_THRESHOLDS),
        status='review' if checks else 'passed')
    return report['report_checks']
