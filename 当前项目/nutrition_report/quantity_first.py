"""Keep requirement evaluation separate from one jointly validated allocation."""
from .report_policy import amount_status, DEFICIT
from .food_standards import number
from .personal_targets import build_personal_targets, REPRESENTATIVES

STAPLE_RATIOS = {'beans_energy', 'tubers_energy', 'grains_remainder'}
PROTEIN_RATIOS = {'seafood', 'quality_protein', 'livestock_remainder'}

def target_text(low, high, planning=None):
    if low is None:return '暂无法折算'
    if high is None:return f'≥ {low:.2f} g/天'
    if abs(high-low)<1e-8:return f'约 {low:.2f} g/天'
    return f'{low:.2f}–{high:.2f} g/天'

def comparison(actual, low, high):
    if actual is None or low is None:return '-',None,None
    status=amount_status(actual, low, high)
    if status in DEFICIT:return status,0,actual-low
    if status=='偏多':return status,0,actual-high
    return '适中',1,0

def apply_quantity_priority(nutrition, athlete, standard, foods, food_db, categories, config, merged_meals=None):
    standard['energy_gate']=({'适宜':'adequate','适中':'adequate','偏多':'excess','过多':'excess','过少':'deficit','不足':'deficit','严重不足':'deficit'}.get(nutrition['energy'].get('evaluation'),'unknown') if standard['nutrient_record_complete'] else 'unknown')
    plan=build_personal_targets(athlete,standard,food_db,nutrition['energy'],config)
    standard['personal_targets']=plan  # Solver diagnostics do not change report copy.
    for row in standard['rows']:
        key=row['key'];target=plan['food_targets'].get(key)
        # Original user rule and score remain authoritative. A solver-chosen
        # point is not a new physiological minimum or maximum.
        row['original_rule']={k:row.get(k) for k in ('label','actual','unit','target','target_min','target_max','evaluation','score','gap')}
        row['evaluation_basis']='ratio' if key in STAPLE_RATIOS|PROTEIN_RATIOS else 'original_rule'
        if key in STAPLE_RATIOS and standard['energy_gate'] == 'deficit':
            # User-requested energy priority; retain ratio facts and original score.
            row['evaluation_basis'] = 'energy_priority'
            row['energy_priority_status'] = nutrition['energy']['evaluation']
            row['evaluation'] = row['evaluation'] if row['evaluation'] in DEFICIT else nutrition['energy']['evaluation']
            row['machine_evaluation'] = row['evaluation']
        if not target:continue
        row.update(joint_plan_amount=target['planning'],
                   plan_representative=target['representative'],plan_note=target['note'])
        if key not in STAPLE_RATIOS|{'seafood','livestock_remainder'}:continue
        category,representative=REPRESENTATIVES[key]
        nutrient='carbohydrate' if key in STAPLE_RATIOS else 'protein'
        if merged_meals is not None:
            relevant=[(amount,food_db[name]) for name,amount in merged_meals.items() if name in food_db and food_db[name].get('category')==category]
            values=[number(info.get(nutrient)) for _,info in relevant]
            nutrient_actual=sum(g*v/100 for (g,_),v in zip(relevant,values)) if row['actual'] is not None and all(v is not None for v in values) else None
            recorded=sum(g for g,_ in relevant) if row['actual'] is not None else None
        else:
            relevant=[f for f in foods if f['category']==category]
            nutrient_actual=sum(f['nutrition'][nutrient] for f in relevant) if row['actual'] is not None else None
            recorded=sum(f['amount'] for f in relevant) if row['actual'] is not None else None
        density=food_db[representative][nutrient]/100
        equivalent=nutrient_actual/density if nutrient_actual is not None else None
        # Keep actual %, ratio bounds, score and units authoritative and visible.
        # Equivalent grams are audit information, NOT a replacement standard.
        row['actual_equivalent']=dict(value=equivalent,unit='g/天',
            representative=representative,recorded_actual_g=recorded,
            actual_nutrient_g=nutrient_actual,conversion_basis=nutrient,
            density_per_100g=density*100)
    return [],None
