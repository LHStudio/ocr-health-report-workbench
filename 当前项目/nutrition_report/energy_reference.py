"""Validate pristine resting bounds; render either resting or net-added reference."""
import math
import re


def energy_display_text(text):
    """Expand abbreviations only in the energy presentation, not report data."""
    text = str(text)
    for abbr, chinese in [('FFM', '去脂体重'), ('EEE', '运动消耗'), ('EI', '能量摄入'),
                          ('LEA', '低能量可用性'), ('REE', '静息能量消耗'),
                          ('BMR', '基础代谢率')]:
        text = re.sub(rf'(?:{chinese})?(?<![A-Za-z]){abbr}(?![A-Za-z])',
                      f'{chinese}（{abbr}）', text)
    return text


def energy_summary_lines(energy):
    """Show existing results without calculation steps or endpoint expansion."""
    kind = energy.get('reference_type')
    if kind in {'tdee', 'tdee_pending'}:
        lines = []
        if kind == 'tdee':
            lines.append(f"推荐能量（TDEE）：{energy_reference_text(energy)} kcal/天")
        if energy.get('neat_kcal') is not None:
            lines.append(f"非运动性活动产热（NEAT）：{energy['neat_kcal']:.2f} kcal/天")
        tef = energy.get('tef_kcal')
        if tef:
            value = f'{tef[0]:.2f}' if tef[0] == tef[1] else f'{tef[0]:.2f}–{tef[1]:.2f}'
            lines.append(f'食物热效应（TEF）：{value} kcal/天')
        if kind == 'tdee_pending':
            reason = energy_display_text(energy.get('tdee_pending_reason', '缺少计算数据'))
            lines.append(reason + '；推荐能量（TDEE）与食物热效应（TEF）暂无法计算。')
        return lines
    if kind in {'bmr', 'bmr_plus_net'} or energy.get('standard') not in (None, ''):
        return [f'推荐能量：{energy_reference_text(energy)} kcal/天']
    return ['推荐能量：缺少有效参考数据，暂无法计算。']


def accepted_energy_bounds(energy):
    """One legacy comparison band; release approval separately checks its scope."""
    try:
        if energy.get('reference_type') in {'bmr', 'bmr_plus_net', 'tdee'}:
            low, high = float(energy['standard_min']), float(energy['standard_max'])
        else:
            value = float(energy['standard'])
            low, high = value * .9, value * 1.1
        if math.isfinite(low) and math.isfinite(high) and 0 < low <= high:
            return low, high
    except (KeyError, TypeError, ValueError):
        pass
    return None, None


def bmr_bounds(user):
    measured = user.get('restingMeasuredRee')
    if measured is not None:
        try:
            measured = float(measured)
        except (TypeError, ValueError):
            measured = None
        if measured is not None and math.isfinite(measured) and measured > 0:
            return measured, measured
    raw = [user.get('bmrMin'), user.get('bmrMax')]
    if all(v is None or str(v).strip() == '' for v in raw):
        return None
    try:
        low, high = map(float, raw)
    except (TypeError, ValueError) as error:
        raise ValueError('BMR最低值和最高值须同时填写有效正数') from error
    if not (math.isfinite(low) and math.isfinite(high) and 0 < low <= high):
        raise ValueError('BMR区间须为有限正数，且最低值不得超过最高值')
    return low, high


def energy_reference_text(energy):
    if energy.get('reference_type') in {'bmr', 'bmr_plus_net', 'tdee'}:
        return f"{energy['standard_min']:g}-{energy['standard_max']:g}"
    value = energy.get('standard')
    return str(value) if value not in (None, '') else '-'


def energy_calculation_lines(energy):
    """Expand the same correlated MET endpoints used for the reference interval."""
    training = energy.get('training_expenditure') or {}
    resting = energy.get('resting_bounds')
    if energy.get('reference_type') == 'tdee_pending':
        return [f"NEAT＝10.5×体重＝{energy['neat_kcal']:.2f} kcal/天",
                energy.get('tdee_pending_reason', '缺少计算数据')+'；TDEE与TEF暂无法计算。',
                'TDEE＝(静息代谢＋EEE日均＋NEAT)÷0.91；TEF＝TDEE×9%。']
    if energy.get('reference_type') == 'tdee' and training.get('applied') and resting:
        neat = energy['neat_kcal']
        lines = ['推荐能量TDEE＝(静息代谢＋EEE日均＋NEAT)÷0.91',
                 f"NEAT＝10.5×{training['weight_kg']:g} kg＝{neat:.2f} kcal/天"]
        for i, label in enumerate(('下限', '上限')):
            total = energy['standard_min' if i == 0 else 'standard_max']
            eee = training['net_daily_kcal'][i]
            lines.append(f'{label}：({resting[i]:g}＋{eee:.2f}＋{neat:.2f})÷0.91＝{total:.2f}')
        lines.append(f"TEF＝TDEE×9%＝{energy['tef_kcal'][0]:.2f}–{energy['tef_kcal'][1]:.2f} kcal/天")
        source = 'REE实测' if energy.get('resting_source') == '个人REE实测' else 'BMR区间'
        lines.append(f'静息代谢采用{source}；EEE＝周净消耗÷7（估算）。')
        return lines
    if energy.get('reference_type') == 'bmr_plus_net' and training.get('applied') and resting:
        factor = 3.5 * training['weight_kg'] / 200 / 7
        combinations = [(factor * (met-1) * (total-strength), factor * (lift-1) * strength)
                        for total in training['total_weekly_minutes']
                        for strength in training['strength_weekly_minutes']
                        for met in training['sport_met'] for lift in training['strength_met']]
        endpoints = (min(combinations, key=sum), max(combinations, key=sum))
        lines = ['推荐能量＝静息代谢参考值＋专项净消耗＋力量净消耗']
        for i, label in enumerate(('下限', '上限')):
            sport, strength = endpoints[i]
            total = resting[i] + sport + strength
            lines.append(f'{label}：{resting[i]:g}＋{sport:.2f}＋{strength:.2f} ≈ {total:.2f} kcal/天')
        lines.append('日均净消耗＝(MET-1)×3.5×体重(kg)÷200×每周分钟÷7；专项时间不重复计入力量时间。')
        lines.append('按训练计划估算，不含日常非训练活动与食物热效应。')
        return lines
    if energy.get('standard') not in (None, ''):
        return [f"推荐能量＝{energy_reference_text(energy)} kcal/天（{energy.get('standard_source') or '现有参考标准'}）",
                '按现有参考标准取值，未另加运动消耗。']
    return ['推荐能量：缺少有效参考数据，暂无法展开计算。']
