"""Intake-independent food planning from the existing personal V2 requirements.

The 80/5/15 staple-energy and 70/30 meat-weight split is an explicit planning
example using existing constraints, not a new clinical optimum. Representative
foods are selected from the active nutrient database, never the recorded meals.
"""
import math


NUTRIENTS = ('energy', 'protein', 'carbohydrate', 'fat')
REPRESENTATIVES = {
    'grains_remainder': ('谷类', '米饭'), 'beans_energy': ('豆类', '豆腐'),
    'tubers_energy': ('薯类', '土豆'), 'livestock_remainder': ('畜禽肉', '牛肉'),
    'seafood': ('水产品', '海白虾'), 'milk': ('奶类', '鲜奶'),
    'eggs': ('蛋类', '蛋类'), 'vegetables': ('蔬菜', '白菜'),
    'fruit': ('水果', '苹果'), 'nuts': ('坚果', '核桃仁'),
}
STAPLE_SHARES = {'grains_remainder': .80, 'beans_energy': .05, 'tubers_energy': .15}


def positive(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def energy_bounds(energy):
    """Use filled BMR bounds verbatim, otherwise the existing personal EER."""
    if energy.get('reference_type') == 'bmr':
        low, high = positive(energy.get('standard_min')), positive(energy.get('standard_max'))
        return (low, high) if low is not None and high is not None else (None, None)
    value = positive(energy.get('standard'))
    return value, value


def build_personal_targets(athlete, standard, food_db):
    rows = {row['key']: row for row in athlete['rows']}
    macro = {key: dict(min=rows[key].get('target_min'), max=rows[key].get('target_max'),
                       planning=rows[key].get('target_planning', rows[key].get('target_min')))
             for key in ('protein', 'carbohydrate', 'fat')}
    result = dict(macro_targets=macro, food_targets={}, planned_nutrients={}, plan_warnings=[],
                  assumptions=[
                      '个人蛋白质和碳水化合物需求沿用V2运动类型×体重；脂肪需求为个人EER或填写BMR区间的20–30%供能，不以实际摄入反推。',
                      '计划示例取原有豆类最低5%、薯类最低15%、谷类余量80%的主食能量分配，水产品取原有最低30%、畜禽肉70%的肉类重量分配；不是新增唯一食谱。',
                      '固定食物采用既有奶、蛋、蔬菜、水果、坚果目标下限；代表食物密度来自当前营养库，改变代表食谱需重新换算，不改变个人营养需求。',
                  ])
    warnings = result['plan_warnings']
    if not athlete.get('targets_applicable') or any(macro[k]['min'] is None for k in ('protein', 'carbohydrate')):
        warnings.append('个人体重、运动类型或训练阶段不足以建立适用的食物目标；不以实际摄入代替需求。')
        return result

    representatives = {}
    for key, (category, preferred) in REPRESENTATIVES.items():
        candidates = [preferred] + sorted(n for n, f in food_db.items() if f.get('category') == category and n != preferred)
        for name in candidates:
            info = food_db.get(name, {})
            if info.get('category') != category:
                continue
            try:
                values = {nutrient: float(info[nutrient]) / 100 for nutrient in NUTRIENTS}
            except (KeyError, TypeError, ValueError):
                continue
            if not all(math.isfinite(v) and v >= 0 for v in values.values()):
                continue
            if key in STAPLE_SHARES and values['energy'] <= 0:
                continue
            if key in {'seafood', 'livestock_remainder'} and values['protein'] <= 0:
                continue
            representatives[key] = (name, category, values)
            break
        if key not in representatives:
            warnings.append(f'{category}缺少有效代表食物营养参数，个人食物目标暂无法折算。')
    if len(representatives) != len(REPRESENTATIVES):
        return result

    fixed_rows = {row['key']: row for row in standard['rows']}
    fixed = {n: 0.0 for n in NUTRIENTS}
    fixed_animal_protein = 0
    food_targets = result['food_targets']
    for key in ('milk', 'eggs', 'vegetables', 'fruit', 'nuts'):
        amount = fixed_rows[key]['target_min']
        name, category, values = representatives[key]
        food_targets[key] = dict(min=amount, max=fixed_rows[key].get('target_max'), planning=amount,
                                 representative=name, category=category, note='沿用既有固定食物目标。')
        for n in NUTRIENTS:
            fixed[n] += amount * values[n]
        if key in {'milk', 'eggs'}:
            fixed_animal_protein += amount * values['protein']
    staple = {n: sum(share * representatives[k][2][n] / representatives[k][2]['energy']
                     for k, share in STAPLE_SHARES.items()) for n in NUTRIENTS}
    meat = {n: .7 * representatives['livestock_remainder'][2][n] +
               .3 * representatives['seafood'][2][n] for n in NUTRIENTS}

    def solve(carb, protein):
        # Two equations reconcile ALL planned carbohydrate and protein, including
        # meat carbohydrate and staple protein. Never subtract actual intake.
        determinant = staple['carbohydrate'] * meat['protein'] - staple['protein'] * meat['carbohydrate']
        if determinant <= 0:
            return None
        c, p = carb - fixed['carbohydrate'], protein - fixed['protein']
        staple_energy = (c * meat['protein'] - p * meat['carbohydrate']) / determinant
        meat_grams = (p * staple['carbohydrate'] - c * staple['protein']) / determinant
        if staple_energy <= 0:
            return None
        # Existing quality-protein >=50% rule is a plan constraint, not a
        # subtraction of excessive recorded grain/milk/egg consumption.
        if meat_grams * meat['protein'] + fixed_animal_protein < protein * .5:
            denominator = staple['carbohydrate'] + meat['carbohydrate'] * staple['protein'] / meat['protein']
            if denominator <= 0:
                return None
            staple_energy = (c - meat['carbohydrate'] * (fixed['protein'] - 2 * fixed_animal_protein) / meat['protein']) / denominator
            meat_grams = (staple_energy * staple['protein'] + fixed['protein'] - 2 * fixed_animal_protein) / meat['protein']
        return (staple_energy, meat_grams) if staple_energy > 0 and meat_grams > 0 else None

    point = solve(macro['carbohydrate']['planning'], macro['protein']['planning'])
    if point is None:
        warnings.append('个人营养需求与固定食物/代表食谱约束不相容，无法给出正的主食和肉类目标；请核对规范，不能将肉类需求写为0克。')
        return result
    carb_bounds = {macro['carbohydrate']['min'], macro['carbohydrate']['max'] or macro['carbohydrate']['min']}
    protein_bounds = {macro['protein']['min'], macro['protein']['max'] or macro['protein']['planning']}
    solutions = [point] + [v for c in carb_bounds for p in protein_bounds if (v := solve(c, p)) is not None]
    for key, share in STAPLE_SHARES.items():
        name, category, values = representatives[key]
        amounts = [s * share / values['energy'] for s, _ in solutions]
        food_targets[key] = dict(min=min(amounts), max=max(amounts), planning=point[0] * share / values['energy'],
                                 representative=name, category=category,
                                 note='由个人碳水/蛋白质目标与计划食物同时求解；按既有主食能量分配及固定代表密度折算。')
    for key, share in (('seafood', .3), ('livestock_remainder', .7), ('meat', 1)):
        name, category, _ = representatives['livestock_remainder' if key == 'meat' else key]
        food_targets[key] = dict(min=min(m for _, m in solutions) * share, max=max(m for _, m in solutions) * share,
                                 planning=point[1] * share, representative=name if key != 'meat' else
                                 representatives['livestock_remainder'][0] + '、' + representatives['seafood'][0],
                                 category=category if key != 'meat' else '肉类（含水产品）',
                                 note='按个人蛋白质需求减去计划食物的蛋白质，并保留既有优质蛋白约束；不扣除实际谷奶蛋摄入。')
    food_targets['quality_protein'] = dict(min=macro['protein']['min'] * .5, max=macro['protein']['max'],
                                          planning=point[1] * meat['protein'] + fixed_animal_protein,
                                          representative='肉蛋奶提供的蛋白质', category='肉蛋奶优质蛋白',
                                          note='个人总蛋白质需求至少一半来自肉蛋奶；单位为蛋白质克数，不是食物重量。')
    result['planned_nutrients'] = {n: fixed[n] + point[0] * staple[n] + point[1] * meat[n] for n in NUTRIENTS}
    result['planned_meat_protein'] = point[1] * meat['protein']
    actual_plan_protein = result['planned_nutrients']['protein']
    if abs(actual_plan_protein - macro['protein']['planning']) > 1e-6:
        requested = macro['protein']['planning']
        macro['protein']['requested_planning'] = requested
        macro['protein']['planning'] = actual_plan_protein
        inside = macro['protein']['max'] is None or actual_plan_protein <= macro['protein']['max'] + 1e-8
        result['constraints_satisfied'] = inside
        warnings.append(f'既有优质蛋白至少一半约束下，示例食谱蛋白质计划点由{requested:.2f}g/天调整为{actual_plan_protein:.2f}g/天，' +
                        ('仍在个人蛋白质参考范围内；个人需求上下限不变。' if inside else
                         '已超个人蛋白质参考上限，现有食谱约束不相容；请核对约束，不自动倒扣肉类为0。'))
    else:
        result['constraints_satisfied'] = True
    # The exemplar has no invented cooking-oil entry. A fat shortfall is an
    # explicit unallocated requirement, not a claim that the food plan meets it.
    fat_low, fat_high = macro['fat']['min'], macro['fat']['max']
    planned_fat = result['planned_nutrients']['fat']
    result['unallocated_fat_g'] = max(0, fat_low - planned_fat) if fat_low is not None else None
    if fat_low is None:
        result['constraints_satisfied'] = False
        warnings.append('缺少个人能量参考，脂肪需求未确认，示例食谱不能标记为已满足全部宏量目标。')
    elif planned_fat < fat_low - 1e-8:
        result['constraints_satisfied'] = False
        warnings.append(f'示例食谱脂肪{planned_fat:.2f}g/天，低于个人参考下限{fat_low:.2f}g/天，尚有{fat_low-planned_fat:.2f}g/天脂肪缺口；未虚构烹调用油或额外食物，请核对完整脂肪来源并重新配餐。')
    elif fat_high is not None and planned_fat > fat_high + 1e-8:
        result['constraints_satisfied'] = False
        warnings.append(f'示例食谱脂肪{planned_fat:.2f}g/天，超过个人参考上限{fat_high:.2f}g/天；现有代表食谱未满足全部宏量约束，请调整食物选择后重新配餐。')
    result['representatives'] = {key: name for key, (name, _, _) in representatives.items()}
    return result
