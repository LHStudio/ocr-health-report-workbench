"""先评价总量，再评价结构；不将蛋白质克数直接当作肉类食物克数。"""
from .athlete import display_number

STAPLE_RATIOS = {'beans_energy', 'tubers_energy', 'grains_remainder'}
PROTEIN_RATIOS = {'seafood', 'quality_protein'}


def apply_quantity_priority(nutrition, athlete, standard, foods, food_db, categories, config):
    rows = {r['key']: r for r in athlete['rows']}
    complete = standard['nutrient_record_complete']
    energy = nutrition['energy']
    protein, carb = rows['protein'], rows['carbohydrate']
    energy_known = complete and energy.get('standard') is not None
    staple_low = complete and ((energy_known and energy['value'] < energy['standard']) or carb['evaluation'] == '不足')
    protein_low = complete and protein['evaluation'] == '不足'
    staple_ready = energy_known and not staple_low
    protein_ready = complete and protein['evaluation'] in {'适中', '过多'}
    notes = []
    if staple_low:
        current = sum(f['amount'] for f in foods if f['category'] in {'谷类', '豆类', '薯类'})
        message = f'主食总量目前约 {display_number(current)} g/天；'
        if energy_known:
            message += f"总能量目前 {display_number(energy['value'])} kcal/天，参考目标 {display_number(energy['standard'])} kcal/天；"
        if carb['evaluation'] == '不足':
            message += f"碳水化合物目前 {display_number(carb['actual'])} g/天，参考目标 {carb['target']}，尚差 {display_number(-carb['gap'])} g/天；"
        notes.append(message + '应先增加主食，谷类、豆类、薯类均可补充。')
    if protein_low:
        notes.append(f"先补足蛋白质：目前 {display_number(protein['actual'])} g/天，参考目标 {protein['target']}，尚差 {display_number(-protein['gap'])} g/天；增加肉类（含水产品）、奶类和蛋类等蛋白质来源，达标后再考虑结构占比。")

    for row in standard['rows']:
        key = row['key']
        if key not in STAPLE_RATIOS | PROTEIN_RATIOS:
            continue
        low, ready = (staple_low, staple_ready) if key in STAPLE_RATIOS else (protein_low, protein_ready)
        if low or not ready:
            status = '不足' if low else '-'
            row.update(evaluation=status, machine_evaluation=status, score=None, gap=None,
                       evaluation_basis='quantity_first' if low else 'quantity_unknown')
            row['note'] = ('总能量或碳水不足，先补足主食' if key in STAPLE_RATIOS else '总蛋白质不足，先补足蛋白质来源') if low else '总量是否满足尚无法确认，暂不评价占比'
            row['note'] += '，占比暂不评价。'
        else:
            mapping = {'不足': '能量占比偏低', '过多': '能量占比偏高', '适中': '能量占比适中'} if key in STAPLE_RATIOS else {'不足': '占比偏低', '过多': '占比偏高', '适中': '占比适中'}
            row.update(evaluation=mapping.get(row['evaluation'], row['evaluation']),
                       machine_evaluation=mapping.get(row['machine_evaluation'], row['machine_evaluation']), evaluation_basis='ratio')
    if protein_low:
        for row in standard['rows']:
            if row['key'] in {'milk', 'eggs', 'livestock_remainder'}:
                row.update(evaluation='不足', machine_evaluation='不足', evaluation_basis='quantity_first')
                row['note'] += '；先补足总蛋白质。'
        for category in {'奶类', '蛋类', '畜禽肉', '水产品'}:
            categories[category]['evaluation'] = '不足'

    meat_row, meat_message = meat_reference(protein, foods, food_db, complete)
    standard['rows'].insert(next(i for i, r in enumerate(standard['rows']) if r['key'] == 'seafood'), meat_row)
    judged = [r for r in standard['rows'] if r['score'] is not None]
    total = standard['summary']['total']
    passed = sum(r['score'] for r in judged)
    standard['summary'].update(passed=passed, evaluated=len(judged), attainment_percent=round(passed/total*100,1) if len(judged)==total else None)
    standard['summary']['text'] = f'定量规则达标 {passed}/{len(judged)} 项；可评价 {len(judged)}/{total} 项。' + (
        f'完整达标率 {passed/total*100:g}%（非医学综合评分）。' if len(judged)==total else '总量不足或存在未评价项，不给出完整达标率。')
    return notes, meat_message


def meat_reference(protein_row, foods, food_db, complete):
    meat = [f for f in foods if f['category'] in {'畜禽肉', '水产品'}]
    actual = sum(f['amount'] for f in meat) if complete else None
    actual_protein = sum(f['nutrition']['protein'] for f in meat)
    excluded = sum(f['nutrition']['protein'] for f in foods if f['category'] in {'谷类', '奶类', '蛋类'})
    lower = protein_row.get('target_min') if complete and protein_row['evaluation'] != '-' else None
    residual = max(0, lower-excluded) if lower is not None else None
    density = actual_protein/actual if actual and actual_protein > 0 else None
    basis = '按当前肉类（含水产品）加权蛋白质密度折算'
    if density is None:
        fallback = food_db.get('牛肉', {}).get('protein')
        density = float(fallback)/100 if fallback and float(fallback)>0 else None
        basis = '当前肉类无有效密度，暂以牛肉蛋白质含量估算，选择具体肉类后需复核'
    target = residual/density if residual is not None and density else None
    shortfall = max(0, target-actual) if target is not None and actual is not None else None
    note = '肉类蛋白质参考量=max(总蛋白质参考下限−谷类蛋白质−奶类蛋白质−蛋类蛋白质,0)；其他食物蛋白质另计。' + basis + '。'
    status = ('不足' if protein_row['evaluation']=='不足' else '适中') if target is not None else '-'
    row = dict(key='meat',label='肉类（含水产品）', actual=round(actual,4) if actual is not None else None,
               unit='g/天',target=f'约 {display_number(target)} g/天' if target is not None else '暂无法折算',
               target_grams=target,shortfall_grams=shortfall,protein_target=residual,
               gap=round(actual-target,4) if target is not None else None,score=None,
               machine_evaluation=status,evaluation=status,note=note,evaluation_basis='quantity_first')
    if target is None:
        message='肉类（含水产品）参考目标暂无法折算：请先核对总蛋白质目标、完整饮食记录及肉类蛋白质含量。'
    else:
        message=f'肉类（含水产品）：目前 {display_number(actual)} g/天，参考目标约 {display_number(target)} g/天，按谷、奶、蛋扣除口径估算尚差 {display_number(shortfall)} g/天。'
        message+= '总蛋白质不足，优先补量，肉、奶、蛋均可增加。' if protein_row['evaluation']=='不足' else '总蛋白质已满足，不按此估算缺口机械加量，再结合结构占比调整。'
        if '加权蛋白质密度折算' not in basis:
            message += basis + '。'
    return row,message
