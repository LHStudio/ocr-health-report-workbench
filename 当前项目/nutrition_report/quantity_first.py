"""Compare intake with personal plans; energy is a summary, never a gate."""
from .food_standards import number
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
                          protein=(v * amount / 100 if (v := number(food_db[name].get('protein'))) is not None else None),
                          carbohydrate=(v * amount / 100 if (v := number(food_db[name].get('carbohydrate'))) is not None else None))
                      for name, amount in merged_meals.items() if name in food_db]
                     if merged_meals is not None else
                     [dict(amount=f['amount'], category=f['category'], protein=f['nutrition']['protein'],
                           carbohydrate=f['nutrition']['carbohydrate']) for f in foods])
    for row in standard['rows']:
        key = row['key']
        if key not in groups:
            continue
        row['original_ratio'] = {field: row.get(field) for field in
                                 ('actual', 'unit', 'target', 'target_min', 'target_max', 'evaluation', 'score', 'gap')}
        target = plan['food_targets'].get(key, {})
        low, high = target.get('min'), target.get('max')
        known = complete or row.get('actual') is not None
        recorded_actual = sum(food['amount'] for food in precise_foods if food['category'] in groups[key]) if known else None
        representative = target.get('representative')
        nutrient = 'carbohydrate' if key in STAPLE_RATIOS else 'protein'
        values = [food[nutrient] for food in precise_foods if food['category'] in groups[key]]
        nutrient_actual = sum(values) if known and all(v is not None for v in values) else None
        density = float(food_db.get(representative, {}).get(nutrient) or 0) / 100
        actual = (nutrient_actual if key == 'quality_protein' else
                  nutrient_actual / density if nutrient_actual is not None and density > 0 else
                  None if representative else recorded_actual)
        label = labels[key] if key == 'quality_protein' or not representative else labels[key] + '（' + representative + '等价量）'
        status, score, gap = comparison(actual, low, high)
        row.update(label=label, actual=actual, unit='g/天', target=target_text(low, high),
                   target_min=low, target_max=high, target_planning=target.get('planning'),
                   gap=gap, evaluation=status, machine_evaluation=status,
                   score=None if key == 'livestock_remainder' else score,
                   note=target.get('note', '缺少适用个人需求或有效代表食物参数，不能以实际摄入反推目标。'),
                   evaluation_basis='personal_target', representative=representative,
                   recorded_actual_g=recorded_actual, actual_nutrient_g=nutrient_actual,
                   conversion_basis=nutrient, conversion_density_per_100g=density*100)
    judged = [r for r in standard['rows'] if r['score'] is not None]
    total = standard['summary']['total']
    passed = sum(r['score'] for r in judged)
    standard['summary'].update(passed=passed, evaluated=len(judged),
                               attainment_percent=round(passed / total * 100, 1) if len(judged) == total else None)
    standard['summary']['text'] = f'定量规则达标 {passed}/{len(judged)} 项；可评价 {len(judged)}/{total} 项。' + (
        f'完整达标率 {passed / total * 100:g}%（非医学综合评分）。' if len(judged) == total else
        '存在未评价项，不给出完整达标率。')
    return [], None
