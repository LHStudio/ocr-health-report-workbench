"""Food-equivalent conversion from the existing personal V2 requirements.

The 80/5/15 staple-energy and 70/30 meat-weight split is an explicit planning
conversion convention, not a second menu or a second nutritional requirement.
Densities come from the active nutrient database, never from recorded amounts.
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
    """Use interval reference (resting + net if applicable), otherwise personal EER."""
    if energy.get('reference_type') in {'bmr', 'bmr_plus_net'}:
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
                      '个人蛋白质和碳水化合物需求沿用V2运动类型×体重；脂肪需求为个人能量参考的20–30%供能（适用足球/篮球为静息代谢＋运动净消耗，否则沿用BMR/EER），不以实际摄入反推。',
                      '克数换算沿用豆类5%、薯类15%、谷类余量80%的分配端点，水产品30%、畜禽肉70%；这些是换算口径，不是第二套营养需求。',
                      '固定食物采用既有奶、蛋、蔬菜、水果、坚果目标下限；默认食物每克营养来自当前营养库，各类贡献只计一次，不据此生成另一份食谱评价。',
                  ])
    warnings = result['plan_warnings']
    if not athlete.get('targets_applicable') or any(macro[k]['min'] is None for k in ('protein', 'carbohydrate')):
        warnings.append('个人体重、运动类型或训练阶段不足以建立适用的食物目标；不以实际摄入代替需求。')
        return result

    representatives = {}
    for key, (category, preferred) in REPRESENTATIVES.items():
        candidates = [preferred]  # User-confirmed defaults; never silently switch food identity.
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
            if key in STAPLE_SHARES and (values['energy'] <= 0 or values['carbohydrate'] <= 0):
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
    def within_requirements(solution):
        energy, grams = solution
        for nutrient in ('carbohydrate', 'protein'):
            value = fixed[nutrient] + energy * staple[nutrient] + grams * meat[nutrient]
            low, high = macro[nutrient]['min'], macro[nutrient]['max']
            if value < low - 1e-8 or (high is not None and value > high + 1e-8):
                return False
        return True

    candidates = [point]
    for carb in carb_bounds:
        for protein in protein_bounds:
            solution = solve(carb, protein)
            if solution is not None:
                candidates.append(solution)
    solutions = [solution for solution in candidates if within_requirements(solution)]
    result['conversion_solutions'] = [dict(staple_energy=s, internal_meat_g=m,
        **{n: fixed[n] + s*staple[n] + m*meat[n] for n in ('carbohydrate','protein')}) for s,m in solutions]
    if not solutions:
        warnings.append('默认食物密度与个人营养需求不相容，暂不输出不相容的食物目标。')
        return result

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
    # These are conversion contributions, not a second intake/meal evaluation.
    # In particular, do not compare conversion fat with the person's fat need:
    # fat evaluation uses recorded intake against athlete.rows['fat'] only.
    actual_conversion_protein = result['planned_nutrients']['protein']
    requested = macro['protein']['planning']
    result['protein_conversion'] = dict(requested=requested, value=actual_conversion_protein,
        within_personal_range=(macro['protein']['min'] - 1e-8 <= actual_conversion_protein and
            (macro['protein']['max'] is None or actual_conversion_protein <= macro['protein']['max'] + 1e-8)))
    result['conversion_scope'] = '碳水化合物、蛋白质需求到默认食物等价克数的换算；不是另一份实际饮食或完整食谱。'
    if not result['protein_conversion']['within_personal_range']:
        warnings.append('默认食物密度与现有分配约束无法在个人蛋白质参考范围内同时满足碳水目标；请核对换算规则，暂不输出不相容的食物目标。')
        for key in ('grains_remainder','beans_energy','tubers_energy','seafood','livestock_remainder','meat'):
            food_targets.pop(key, None)
    result['representatives'] = {key: name for key, (name, _, _) in representatives.items()}
    return result
