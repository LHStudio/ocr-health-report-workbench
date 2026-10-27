"""Validate pristine resting bounds; render either resting or net-added reference."""
import math


def accepted_energy_bounds(energy):
    """One legacy comparison band; release approval separately checks its scope."""
    try:
        if energy.get('reference_type') in {'bmr', 'bmr_plus_net'}:
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
    if energy.get('reference_type') in {'bmr', 'bmr_plus_net'}:
        return f"{energy['standard_min']:g}-{energy['standard_max']:g}"
    value = energy.get('standard')
    return str(value) if value not in (None, '') else '-'


def energy_calculation_lines(energy):
    """Expand the same correlated MET endpoints used for the reference interval."""
    training = energy.get('training_expenditure') or {}
    resting = energy.get('resting_bounds')
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
