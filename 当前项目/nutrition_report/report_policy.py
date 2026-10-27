"""Shared report rules confirmed on 2026-10-27; no changes to source records."""
import math

DEFICIT = {'不足', '严重不足', '过少'}
EXCESS = {'偏多', '过多'}
NORMAL = {'适中', '适宜', '占比适中', '能量占比适中'}
HYDRATION = ('注重补液及时补水。重视补液，遵循少量多次原则；'
             '运动中每隔15-20分钟补充150-200mL；运动后补液量应为体重丢失的150%。')


def finite(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def amount_status(actual, low=None, high=None, adequate='适中'):
    actual, low, high = finite(actual), finite(low), finite(high)
    if actual is None or actual < 0 or (low is None and high is None):
        return '-'
    if low is not None and actual < low - 1e-8:
        return '严重不足' if low > 0 and actual <= low * .5 + 1e-8 else '不足'
    if high is not None and actual > high + 1e-8:
        return '偏多'
    return adequate


def attach_energy_availability(report):
    energy = report['nutrition']['energy']
    ffm = finite(report.get('user', {}).get('fatFreeMass'))
    ei = finite(energy.get('exact_value', energy.get('value')))
    training = energy.get('training_expenditure') or {}
    eee = training.get('net_daily_kcal')
    ea = dict(formula='EA = (EI - EEE) / FFM', unit='kcal/kg FFM/天', threshold=30,
              ei_kcal=ei, ffm_kg=ffm, eee_daily_kcal=eee,
              basis='训练计划日均运动净消耗（周净消耗÷7），估算', status='missing')
    if report.get('assessment_status') == 'needs_review':
        ea['text'] = '能量可用性（EA）：暂无法计算（摄入记录不完整）'
    elif ffm is None or ffm <= 0:
        ea['text'] = '能量可用性（EA）：暂无法计算（缺少有效去脂体重FFM）'
    elif not eee or len(eee) != 2 or any(finite(v) is None or float(v) < 0 for v in eee):
        ea['text'] = '能量可用性（EA）：暂无法计算（缺少有效运动消耗EEE）'
    elif ei is None or ei < 0:
        ea['text'] = '能量可用性（EA）：暂无法计算（缺少有效能量摄入EI）'
    else:
        low, high = (ei - max(eee)) / ffm, (ei - min(eee)) / ffm
        # Compare unrounded values; an interval crossing 30 is not a definite LEA result.
        status = 'risk' if high < 30 else 'possible_risk' if low < 30 else 'above_threshold'
        label = {'risk': 'LEA风险', 'possible_risk': '部分估算区间低于30，存在LEA风险',
                 'above_threshold': '未低于30阈值'}[status]
        value = f'{low:.2f}' if abs(high-low) < 1e-8 else f'{low:.2f} 至 {high:.2f}'
        ea.update(status=status, min=low, max=high, evaluation=label,
                  text=f'能量可用性（EA）：{value} kcal/kg FFM/天（估算）；{label}')
    energy['availability'] = ea


def interpretation_lines(report):
    nutrition = report.get('nutrition') or {}
    status = (nutrition.get('energy') or {}).get('evaluation')
    status = {'过少': '不足', '过多': '偏多', '适中': '适宜'}.get(status, status)
    first = f'总能量摄入量{status}。' if status and status != '-' else '总能量摄入量暂无法评价。'
    share = report.get('snack_energy_percent')
    if share is not None and share > 30:
        first += f'零食供能占比{share:.1f}%，零食摄入过多。'
    rows = {r['key']: r for r in (report.get('athlete_evaluation') or {}).get('rows', [])}
    # Judge the recorded macro proportions against the existing personal ranges.
    values = [finite(nutrition.get(k)) for k in ('protein', 'fat', 'carbohydrate')]
    total = sum(v*f for v, f in zip(values, (4, 9, 4))) if all(v is not None for v in values) else 0
    energy = nutrition.get('energy') or {}
    from .energy_reference import accepted_energy_bounds
    low, high = accepted_energy_bounds(energy)
    bounds = [(rows.get(k, {}).get('target_min'), rows.get(k, {}).get('target_max'), f)
              for k, f in (('protein',4), ('fat',9), ('carbohydrate',4))]
    known = total > 0 and low and high and all(a is not None for a, _, _ in bounds)
    if known:
        shares = [v*f/total for v, f in zip(values, (4,9,4))]
        balanced = all(s >= a*f/high-1e-8 and (b is None or s <= b*f/low+1e-8)
                       for s, (a,b,f) in zip(shares,bounds))
        if balanced:
            second = '三大营养素供能比适宜。'
        else:
            # Explain the existing finding with the same personal-target
            # evaluations shown in the report; do not introduce new cutoffs.
            details = []
            for key, label in (('protein', '蛋白质'), ('fat', '脂肪'), ('carbohydrate', '碳水化合物')):
                state = rows.get(key, {}).get('evaluation')
                state = {'过少': '不足', '过多': '偏多'}.get(state, state)
                if state in DEFICIT | EXCESS:
                    details.append(label + state)
            if not details:
                for label, share, (a, b, factor) in zip(('蛋白质', '脂肪', '碳水化合物'), shares, bounds):
                    if share < a * factor / high - 1e-8:
                        details.append(label + '供能占比不足')
                    elif b is not None and share > b * factor / low + 1e-8:
                        details.append(label + '供能占比偏多')
            second = '三大营养素供能比略有失衡：' + '、'.join(details) + '。'
    else:
        second = '三大营养素供能比暂无法评价。'
    ca = (nutrition.get('calcium') or {}).get('evaluation')
    third = f'膳食中的钙摄入量{ca}。' if ca and ca != '-' else '膳食中的钙摄入量暂无法评价。'
    return [first, second, third]


def finalize_report_copy(report):
    attach_energy_availability(report)
    energy = report['nutrition']['energy'].get('exact_value', report['nutrition']['energy']['value'])
    snack = sum(f.get('exact_energy', f['nutrition']['energy']) for f in report['foods'] if f['category']=='零食')
    report['snack_energy_percent'] = snack/energy*100 if energy > 0 and report.get('assessment_status') != 'needs_review' else None
    report['interpretation_lines'] = interpretation_lines(report)
    report['energy_guidance'] = '\n'.join(f'{i}. {s}' for i,s in enumerate(report['interpretation_lines'],1))
