"""先评价总量，再评价结构；不将蛋白质克数直接当作肉类食物克数。"""
from .athlete import display_number
from .energy_reference import energy_reference_text

STAPLE_RATIOS = {'beans_energy', 'tubers_energy', 'grains_remainder'}
PROTEIN_RATIOS = {'seafood', 'quality_protein', 'livestock_remainder'}


def apply_quantity_priority(nutrition, athlete, standard, foods, food_db, categories, config):
    rows = {r['key']: r for r in athlete['rows']}
    complete = standard['nutrient_record_complete']
    energy = nutrition['energy']
    protein, carb = rows['protein'], rows['carbohydrate']
    # The EER tolerance gates ONLY grains, beans and tubers. Non-staple
    # quantities/proportions keep their own rules regardless of total energy.
    state = ({'适宜':'adequate','适中':'adequate','过多':'excess','过少':'deficit','不足':'deficit'}
             .get(energy.get('evaluation'), 'unknown') if complete else 'unknown')
    standard['energy_gate'] = state
    notes = []
    if state == 'deficit':
        current = sum(f['amount'] for f in foods if f['category'] in {'谷类', '豆类', '薯类'})
        message = f'主食总量目前约 {display_number(current)} g/天；'
        message += f"总能量目前 {display_number(energy['value'])} kcal/天，参考目标 {energy_reference_text(energy)} kcal/天；"
        if carb['evaluation'] == '不足':
            message += f"碳水化合物目前 {display_number(carb['actual'])} g/天，参考目标 {carb['target']}，尚差 {display_number(-carb['gap'])} g/天；"
        notes.append(message + '应先增加主食，谷类、豆类、薯类均按过少评价，暂不按主食内部占比判断增减；其他食物仍按各自标准评价。')
        if protein['evaluation'] == '不足':
            notes.append(f"蛋白质不足：目前 {display_number(protein['actual'])} g/天，参考目标 {protein['target']}，尚差 {display_number(-protein['gap'])} g/天；蛋白质来源按各自参考目标调整。")
    elif state == 'excess':
        notes.append(f"总能量过多：目前 {display_number(energy['value'])} kcal/天，参考目标 {energy_reference_text(energy)} kcal/天；应先控制主食总量，谷类、豆类、薯类均按过多评价，暂不按主食内部占比提出加量建议；其他食物仍按各自标准评价。")
    elif state == 'adequate':
        notes.append('总能量适宜：保持全天饮食总量，按各类食物占比和既有参考目标调整搭配，以替换为主，不整体加量。')

    for row in standard['rows']:
        key = row['key']
        if key not in STAPLE_RATIOS | PROTEIN_RATIOS:
            continue
        if key in STAPLE_RATIOS and state != 'adequate':
            status = {'excess':'过多','deficit':'过少','unknown':'-'}[state]
            row['component_evaluation'] = row['evaluation']
            row['component_score'] = row['score']
            row['component_gap'] = row['gap']
            row.update(evaluation=status, machine_evaluation=status, score=None, gap=None,
                       evaluation_basis='energy_' + state)
            row['note'] += '；仅谷类、豆类、薯类评价依据总能量方向；能量适宜后再评价主食内部占比。'
        elif key in STAPLE_RATIOS | PROTEIN_RATIOS:
            mapping = {'不足': '能量占比偏低', '过多': '能量占比偏高', '适中': '能量占比适中'} if key in STAPLE_RATIOS else {'不足': '占比偏低', '过多': '占比偏高', '适中': '占比适中'}
            row.update(evaluation=mapping.get(row['evaluation'], row['evaluation']),
                       machine_evaluation=mapping.get(row['machine_evaluation'], row['machine_evaluation']), evaluation_basis='ratio')
    meat_row, meat_message = meat_reference(protein, foods, food_db, complete)
    if state == 'adequate':
        meat_message = meat_message.replace('总蛋白质不足，可优先补充。','在保持总能量的前提下调整蛋白质来源搭配。')
    standard['rows'].insert(next(i for i, r in enumerate(standard['rows']) if r['key'] == 'seafood'), meat_row)
    judged = [r for r in standard['rows'] if r['score'] is not None]
    total = standard['summary']['total']
    passed = sum(r['score'] for r in judged)
    standard['summary'].update(passed=passed, evaluated=len(judged), attainment_percent=round(passed/total*100,1) if len(judged)==total else None)
    standard['summary']['text'] = f'定量规则达标 {passed}/{len(judged)} 项；可评价 {len(judged)}/{total} 项。' + (
        f'完整达标率 {passed/total*100:g}%（非医学综合评分）。' if len(judged)==total else '总能量未进入适宜区间或存在未评价项，不给出完整达标率。')
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
        message=f'肉类（含水产品）：目前 {display_number(actual)} g/天，参考目标约 {display_number(target)} g/天，'
        message+= '总蛋白质不足，可优先补充。' if protein_row['evaluation']=='不足' else '总蛋白质已满足，结合结构调整。'
        if '加权蛋白质密度折算' not in basis:
            message += basis + '。'
    return row,message
