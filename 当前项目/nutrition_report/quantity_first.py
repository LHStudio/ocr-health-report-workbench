"""Compare intake with personal plans; energy is a summary, never a gate."""
from .athlete import display_number
from .personal_targets import build_personal_targets

STAPLE_RATIOS = {'beans_energy', 'tubers_energy', 'grains_remainder'}
PROTEIN_RATIOS = {'seafood', 'quality_protein', 'livestock_remainder'}


def target_text(low, high, planning=None):
    if low is None:
        return '暂无法折算'
    if high is None:
        return f'≥ {low:.2f} g/天'
    if abs(high - low) < 1e-8:
        return f'约 {low:.2f} g/天'
    return f'{low:.2f}–{high:.2f} g/天'


def comparison(actual, low, high):
    if actual is None or low is None:
        return '-', None, None
    # Avoid numerical cancellation only; this is not a nutrition tolerance band.
    if actual < low - 1e-8:
        return '不足', 0, actual - low
    if high is not None and actual > high + 1e-8:
        return '过多', 0, actual - high
    return '适中', 1, 0


def apply_quantity_priority(nutrition, athlete, standard, foods, food_db, categories, config, merged_meals=None):
    complete = standard['nutrient_record_complete']
    standard['energy_gate'] = ({'适宜': 'adequate', '适中': 'adequate', '过多': 'excess',
                               '过少': 'deficit', '不足': 'deficit'}.get(nutrition['energy'].get('evaluation'), 'unknown')
                              if complete else 'unknown')
    plan = build_personal_targets(athlete, standard, food_db)
    standard['personal_targets'] = plan
    standard['warnings'].extend(plan['plan_warnings'])
    groups = {'beans_energy': {'豆类'}, 'tubers_energy': {'薯类'}, 'grains_remainder': {'谷类'},
              'seafood': {'水产品'}, 'livestock_remainder': {'畜禽肉'},
              'quality_protein': {'畜禽肉', '水产品', '奶类', '蛋类'}}
    labels = {'beans_energy': '豆类', 'tubers_energy': '薯类', 'grains_remainder': '谷类',
              'seafood': '水产品', 'livestock_remainder': '畜禽肉', 'quality_protein': '肉蛋奶优质蛋白'}
    precise_foods = ([dict(amount=amount, category=food_db[name].get('category', ''),
                          protein=amount * float(food_db[name].get('protein') or 0) / 100)
                      for name, amount in merged_meals.items() if name in food_db]
                     if merged_meals is not None else
                     [dict(amount=f['amount'], category=f['category'], protein=f['nutrition']['protein']) for f in foods])
    for row in standard['rows']:
        key = row['key']
        if key not in groups:
            continue
        row['original_ratio'] = {field: row.get(field) for field in
                                 ('actual', 'unit', 'target', 'target_min', 'target_max', 'evaluation', 'score', 'gap')}
        target = plan['food_targets'].get(key, {})
        low, high = target.get('min'), target.get('max')
        known = complete or row.get('actual') is not None
        actual = (sum(food['protein'] if key == 'quality_protein' else food['amount']
                      for food in precise_foods if food['category'] in groups[key]) if known else None)
        status, score, gap = comparison(actual, low, high)
        row.update(label=labels[key], actual=actual, unit='g/天', target=target_text(low, high),
                   target_min=low, target_max=high, target_planning=target.get('planning'),
                   gap=gap, evaluation=status, machine_evaluation=status,
                   score=None if key == 'livestock_remainder' else score,
                   note=target.get('note', '缺少适用个人需求或有效代表食物参数，不能以实际摄入反推目标。'),
                   evaluation_basis='personal_target', representative=target.get('representative'))
    meat_row, meat_message = meat_reference(plan, precise_foods, complete)
    standard['rows'].insert(next(i for i, r in enumerate(standard['rows']) if r['key'] == 'seafood'), meat_row)
    judged = [r for r in standard['rows'] if r['score'] is not None]
    total = standard['summary']['total']
    passed = sum(r['score'] for r in judged)
    standard['summary'].update(passed=passed, evaluated=len(judged),
                               attainment_percent=round(passed / total * 100, 1) if len(judged) == total else None)
    standard['summary']['text'] = f'定量规则达标 {passed}/{len(judged)} 项；可评价 {len(judged)}/{total} 项。' + (
        f'完整达标率 {passed / total * 100:g}%（非医学综合评分）。' if len(judged) == total else
        '存在未评价项，不给出完整达标率。')
    return [], meat_message


def meat_reference(plan, foods, complete):
    target = plan['food_targets'].get('meat', {})
    low, high, planning = target.get('min'), target.get('max'), target.get('planning')
    actual = sum(f['amount'] for f in foods if f['category'] in {'畜禽肉', '水产品'}) if complete else None
    status, _, gap = comparison(actual, low, high)
    shortfall = max(0, low - actual) if low is not None and actual is not None else None
    note = target.get('note', '个人需求或代表食谱约束不足，不能将肉类需求写为0克。')
    row = dict(key='meat', label='肉类（含水产品）', actual=actual, unit='g/天',
               target=target_text(low, high), target_min=low, target_max=high,
               target_grams=planning, target_planning=planning, shortfall_grams=shortfall,
               protein_target=plan.get('planned_meat_protein'), gap=gap, score=None,
               machine_evaluation=status, evaluation=status, note=note,
               evaluation_basis='personal_target', representative=target.get('representative'))
    message = (f'肉类（含水产品）：目前 {display_number(actual)} g/天，个人参考目标 {row["target"]}，{status}。'
               if actual is not None and low is not None else
               '肉类（含水产品）参考目标或实际摄入暂无法完整比较，请核对个人需求及有效饮食记录，不将未知需求写为0克。')
    return row, message
