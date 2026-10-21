"""Requirements -> energy compatibility -> rules -> API densities -> joint verification.

No added foods, oil, nutrient target relaxation, or independent per-category extrema.
0.01 g is output precision, not a dietary tolerance. Every published portion is
recomputed from that exact quantity, including energy, fat, calcium and ratios.
"""
import math
from .personal_targets import REPRESENTATIVES, energy_bounds
from .energy_reference import accepted_energy_bounds
from .release_gate import density_review

NUTRIENTS = ('energy', 'protein', 'carbohydrate', 'fat', 'calcium')
KEYS = tuple(REPRESENTATIVES)
EPS = 1e-6  # floating arithmetic only; never a nutritional allowance


def _num(value):
    try:
        n = float(value)
        return n if math.isfinite(n) and n >= 0 else None
    except (TypeError, ValueError):
        return None


def build_joint_plan(athlete, standard, food_db, energy, config):
    rows = {r['key']: r for r in athlete['rows']}
    rules = {r['key']: r for r in standard['rows']}
    macro = {k: dict(min=rows[k].get('target_min'), max=rows[k].get('target_max'),
                    planning=rows[k].get('target_planning', rows[k].get('target_min')))
             for k in ('protein','carbohydrate','fat')}
    result = dict(status='blocked', macro_targets=macro, food_targets={}, planned_nutrients={},
                  contributions=[], plan_warnings=[], validation={'passed':False,'checks':[]},
                  stages=[], assumptions=[
                      '营养需求沿用体重和项目标准；能量沿用当前个人参考；不以实际摄入反推需求。',
                      '谷类至多80%、豆类至少5%、薯类至少15%；水产品至少30%、畜禽肉至多70%，均为不等式，不强制分配端点。',
                      '只使用已确认默认食物和营养库密度；不加入烹调油、补充剂或其他食物。',
                      '按能量、蛋白质、碳水及分项规则求一个可行组合，脂肪仅汇总复验，不驱动小类食物分配。'])
    def fail(code, message):
        result.update(status='blocked',failure_code=code,food_targets={},planned_nutrients={},contributions=[])
        result['plan_warnings'].append(message)
        return result
    if not athlete.get('targets_applicable'):
        return fail('requirements_missing','体重、项目或训练阶段不完整，不能通过个人需求校验；暂不输出配餐建议。')
    for k, r in macro.items():
        lo,hi=_num(r['min']),_num(r['max'])
        if lo is None or (r['max'] is not None and (hi is None or hi < lo)):
            return fail('requirements_invalid',f'{k}个人需求范围无效；暂不输出配餐建议。')
    elo,ehi=energy_bounds(energy)
    if elo is None or ehi is None or elo>ehi:
        return fail('energy_missing','个人能量参考缺失或无效；暂不输出配餐建议。')
    need_low,need_high=elo,ehi
    # Match the existing actual-intake evaluator: BMR intervals are inclusive;
    # EER remains the original +/-10% band, not an exact-point food constraint.
    elo,ehi=accepted_energy_bounds(energy)
    result['energy_reference']=dict(min=elo,max=ehi,need_min=need_low,need_max=need_high,source=energy.get('standard_source'),scope=energy.get('standard_note'))
    result['stages'].append(dict(stage='personal_requirements',passed=True))
    mlo=sum(macro[k]['min']*factor for k,factor in [('protein',4),('carbohydrate',4),('fat',9)])
    mhi=(sum(macro[k]['max']*factor for k,factor in [('protein',4),('carbohydrate',4),('fat',9)])
         if all(macro[k]['max'] is not None for k in macro) else None)
    percentages=config.get('fat_energy_percent',[20,30])
    if not isinstance(percentages,(list,tuple)) or len(percentages)!=2 or any(_num(v) is None for v in percentages) or not 0<=percentages[0]<=percentages[1]<100:
        return fail('rules_invalid','脂肪供能规则缺失或无效；暂不输出配餐建议。')
    compatibility=mlo<=ehi+EPS and (mhi is None or mhi>=elo-EPS)
    result['stages'].append(dict(stage='requirements_energy',passed=compatibility,macro_energy_min=mlo,macro_energy_max=mhi,energy_min=elo,energy_max=ehi))
    if not compatibility:
        return fail('requirements_energy_incompatible',f'个人营养需求供能范围与能量参考不相容：三大营养素最低供能{mlo:.2f} kcal/天，个人能量参考{elo:.2f}–{ehi:.2f} kcal/天；保留原标准，暂停配餐建议。')
    # Take all rule bounds from the existing rule rows, not duplicated constants.
    fixed=('milk','eggs','vegetables','fruit','nuts')
    required=(*fixed,'beans_energy','tubers_energy','grains_remainder','seafood','livestock_remainder','quality_protein')
    if any(k not in rules for k in required):
        return fail('rules_missing','食物分项规则缺失；暂不输出配餐建议。')
    for k in required:
        r=rules[k];lo,hi=_num(r.get('target_min')),_num(r.get('target_max'))
        if (r.get('target_min') is not None and lo is None) or (r.get('target_max') is not None and hi is None) or (lo is not None and hi is not None and lo>hi):
            return fail('rules_invalid',f'{k}分项规则无效；暂不输出配餐建议。')
    for k in (*fixed,'beans_energy','tubers_energy','seafood','quality_protein'):
        if _num(rules[k].get('target_min')) is None:
            return fail('rules_missing',f'{k}规则下限缺失；暂不输出配餐建议。')
    for k in ('grains_remainder','livestock_remainder'):
        if _num(rules[k].get('target_max')) is None:
            return fail('rules_missing',f'{k}规则上限缺失；暂不输出配餐建议。')
    calcium=_num(rows.get('calcium',{}).get('target_min'))
    percentages=config.get('fat_energy_percent',[20,30])
    percentages=[_num(v) for v in percentages] if isinstance(percentages,(list,tuple)) else []
    if calcium is None or len(percentages)!=2 or any(_num(v) is None for v in percentages) or not 0<=percentages[0]<=percentages[1]<=100:
        return fail('rules_invalid','钙或脂肪供能规则缺失/无效；暂不输出配餐建议。')
    result['stages'].append(dict(stage='category_rules',passed=True))
    issues=density_review(food_db,[name for _,name in REPRESENTATIVES.values()])
    if issues:
        return fail('density_review_required','；'.join(issues))
    density={n:[] for n in NUTRIENTS}
    for k in KEYS:
        category,name=REPRESENTATIVES[k];food=food_db.get(name,{})
        if food.get('category')!=category or any(_num(food.get(n)) is None for n in NUTRIENTS):
            return fail('density_invalid',f'{name}缺少有效营养库参数；不替换默认食物，暂不输出配餐建议。')
        if food['energy']<=0 or (k in ('grains_remainder','beans_energy','tubers_energy') and food['carbohydrate']<=0) or (k in ('seafood','livestock_remainder') and food['protein']<=0):
            return fail('density_invalid',f'{name}必要营养密度为零；暂不输出配餐建议。')
        for n in NUTRIENTS:density[n].append(float(food[n])/100)
    result['density_per_gram']={k:{n:density[n][i] for n in NUTRIENTS} for i,k in enumerate(KEYS)}
    result['stages'].append(dict(stage='api_densities',passed=True))
    constraints=[]
    def bound(name,vec,lo=None,hi=None):
        constraints.append(dict(name=name,coefficients=list(vec),min=lo,max=hi))
    def unit(k):return [float(j==k) for j in KEYS]
    for n in ('protein', 'carbohydrate'):bound(n,density[n],macro[n]['min'],macro[n]['max'])
    bound('api_energy',density['energy'],elo,ehi)
    macro_e=[4*p+4*c+9*f for p,c,f in zip(density['protein'],density['carbohydrate'],density['fat'])]
    bound('calcium',density['calcium'],calcium,None)
    for k in fixed:bound(k,unit(k),rules[k]['target_min'],rules[k]['target_max'])
    staple=[e if k in ('grains_remainder','beans_energy','tubers_energy') else 0 for k,e in zip(KEYS,density['energy'])]
    for k in ('beans_energy','tubers_energy','grains_remainder'):
        r=rules[k];own=[e if j==k else 0 for j,e in zip(KEYS,density['energy'])]
        if r['target_min'] is not None:bound(k+'_share_min',[a-r['target_min']/100*b for a,b in zip(own,staple)],0,None)
        if r['target_max'] is not None:bound(k+'_share_max',[a-r['target_max']/100*b for a,b in zip(own,staple)],None,0)
    meat=[float(k in ('seafood','livestock_remainder')) for k in KEYS]
    for k in ('seafood','livestock_remainder'):
        r=rules[k];own=unit(k)
        if r['target_min'] is not None:bound(k+'_share_min',[a-r['target_min']/100*b for a,b in zip(own,meat)],0,None)
        if r['target_max'] is not None:bound(k+'_share_max',[a-r['target_max']/100*b for a,b in zip(own,meat)],None,0)
    animal=[p if k in ('seafood','livestock_remainder','milk','eggs') else 0 for k,p in zip(KEYS,density['protein'])]
    quality=rules['quality_protein']['target_min']/100
    bound('quality_protein_share',[a-quality*p for a,p in zip(animal,density['protein'])],0,None)
    # Fat is assessed after aggregation, never used to allocate small food classes.
    result['constraint_spec']=constraints
    try:
        import numpy as np
        from scipy.optimize import linprog, milp, LinearConstraint, Bounds
    except ImportError:
        return fail('solver_unavailable','联合约束求解器未安装；暂停建议，不回退到旧换算。')
    # First verify continuous feasibility. Then solve at the actually displayed
    # 0.01 g precision, so rounding cannot create an invalid published plan.
    aub,bub=[],[]
    for r in constraints:
        if r['max'] is not None:aub.append(r['coefficients']);bub.append(r['max'])
        if r['min'] is not None:aub.append([-v for v in r['coefficients']]);bub.append(-r['min'])
    feasible=linprog(np.zeros(len(KEYS)),A_ub=aub,b_ub=bub,bounds=(0,None),method='highs')
    if not feasible.success:
        result['solver_status']=int(feasible.status)
        return fail('joint_constraints_infeasible','个人需求与当前默认食物及分项规则没有联合可行解；未放宽能量、营养或比例标准，暂停配餐建议。')
    matrix=np.array([r['coefficients'] for r in constraints])*.01
    lower=np.array([r['min'] if r['min'] is not None else -np.inf for r in constraints])
    upper=np.array([r['max'] if r['max'] is not None else np.inf for r in constraints])
    solution=milp(np.zeros(len(KEYS)),integrality=np.ones(len(KEYS)),bounds=Bounds(0,np.inf),
                  constraints=LinearConstraint(matrix,lower,upper),options={'time_limit':10.0,'mip_rel_gap':1e-6})
    result['solver_status']=int(solution.status)
    if not solution.success:
        return fail('joint_solver_not_verified','联合求解未完成可行性验证；暂停配餐建议，不输出未经复核的中间结果。')
    amounts=[int(round(v))*.01 for v in solution.x]
    totals={n:sum(g*v for g,v in zip(amounts,density[n])) for n in NUTRIENTS}
    # Recompute independently of solver status from exact displayed portions.
    checks=[]
    for r in constraints:
        actual=sum(g*v for g,v in zip(amounts,r['coefficients']))
        ok=(r['min'] is None or actual>=r['min']-EPS) and (r['max'] is None or actual<=r['max']+EPS)
        checks.append(dict(name=r['name'],actual=actual,min=r['min'],max=r['max'],passed=ok))
    for name,vec in [('staple_denominator',staple),('meat_denominator',meat),('protein_denominator',density['protein'])]:
        value=sum(g*v for g,v in zip(amounts,vec));checks.append(dict(name=name,actual=value,passed=value>EPS))
    # One fat gram standard from target energy; no actual-energy share grading.
    fat=totals['fat'];lo=macro['fat']['min'];hi=macro['fat']['max']
    checks.append(dict(name='fat',actual=fat,min=lo,max=hi,
                       passed=fat>=lo-EPS and (hi is None or fat<=hi+EPS),scope='overall_only'))
    result['allocation_nutrients']=totals
    result['validation']=dict(passed=all(x['passed'] for x in checks),rounded_passed=all(x['passed'] for x in checks),checks=checks,precision_g=.01,arithmetic_epsilon=EPS)
    if not result['validation']['passed']:
        return fail('reaggregation_failed','食物量重新汇总后有约束未通过；暂停配餐建议。')
    result.update(status='validated',planned_nutrients=totals,
                  representatives={k:REPRESENTATIVES[k][1] for k in KEYS},
                  selection_policy='按能量、蛋白质、碳水及分项规则求可行组合；脂肪仅汇总校验，不反向调整小类。')
    for i,k in enumerate(KEYS):
        category,name=REPRESENTATIVES[k];g=amounts[i]
        result['food_targets'][k]=dict(min=g,max=g,planning=g,representative=name,category=category,
            note='与其他类别共同通过能量、三大营养素、钙及所有分项规则；必须整组使用，不是独立医学上下限。')
        result['contributions'].append(dict(key=k,food=name,grams=g,**{n:g*density[n][i] for n in NUTRIENTS}))
    qp=sum(g*v for g,v in zip(amounts,animal))
    result['food_targets']['quality_protein']=dict(min=macro['protein']['min']*quality,max=macro['protein']['max'],planning=qp,representative='肉蛋奶提供的蛋白质',category='肉蛋奶优质蛋白',note='现有肉蛋奶优质蛋白至少一半规则，使用同一配餐总蛋白质校验。')
    result['protein_conversion']=dict(requested=macro['protein']['planning'],value=totals['protein'],within_personal_range=True)
    result['conversion_solutions']=[{n:totals[n] for n in NUTRIENTS}]
    result['stages'].append(dict(stage='joint_solution_and_reaggregation',passed=True))
    return result
