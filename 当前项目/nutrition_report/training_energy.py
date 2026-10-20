"""User-supplied whole-session MET plans, not measured individual expenditure."""
import math
from collections.abc import Mapping


PLANS = {
    '足球': dict(total=[720, 720], strength=[0, 0], sport_met=[5, 8], strength_met=[3.5, 6],
               schedule='每周6次×120分钟；专项体能每周1次已包含在整堂课平均强度内，不额外叠加'),
    '篮球': dict(total=[1260, 1440], strength=[48, 180], sport_met=[5, 8], strength_met=[3.5, 6],
               schedule='周一至五每天180–210分钟、周六360–390分钟；每周2–3次力量课×24–60分钟，力量时间从总时间扣除'),
}


def interval(value, label, minimum=0, maximum=10080):
    raw = value if isinstance(value, (list, tuple)) else [value, value]
    try:
        low, high = map(float, raw)
        if not all(math.isfinite(v) for v in (low, high)) or not minimum <= low <= high <= maximum:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError(f'训练计划{label}须为{minimum}至{maximum}的有限数或有序二元区间') from None
    return [low, high]


def training_expenditure(user, resting):
    sport = str(user.get('projectType') or '').strip()
    sport = {'足球队': '足球', '女足': '足球', '男足': '足球',
             '篮球队': '篮球', '女篮': '篮球', '男篮': '篮球'}.get(sport, sport)
    result = dict(applied=False, sport=sport, source='用户提供训练课表与整堂训练平均MET假设（2026-10-20）',
                  reason='', averaging_days=7)
    if sport not in PLANS:
        result['reason'] = '体操训练方案尚未提供，未套用足球或篮球MET。' if sport == '体操' else '此项目尚无训练方案，未猜测运动消耗。'
        return result
    phase = str(user.get('trainingPhase') or '').strip()
    status = str(user.get('currentStatus') or '').strip()
    if 'trainingPhase' not in user:
        phase = 'training' if status in {'正常训练', '训练期'} else ''
    nontraining = status in {'比赛期', '赛期', '不训练', '休息期', '非训练期', '休息'}
    if phase != 'training' or nontraining or any(word in status for word in ('康复', '伤', '停训', '休训')):
        result['reason'] = '非正常训练期或处于伤病康复状态，未自动套用整队训练课表；需提供适用训练方案。'
        return result
    try:
        weight = float(user.get('weight'))
    except (TypeError, ValueError):
        weight = 0
    if not math.isfinite(weight) or weight <= 0:
        result['reason'] = '缺少有效体重，未估算运动消耗。'
        return result
    plan = user.get('trainingPlan') or {}
    if not isinstance(plan, Mapping) or set(plan) - {'weeklyMinutes', 'strengthMinutes', 'sportMET', 'strengthMET'}:
        raise ValueError('训练计划须为含weeklyMinutes/strengthMinutes/sportMET/strengthMET的对象')
    default = PLANS[sport]
    total = interval(plan.get('weeklyMinutes', default['total']), '每周总分钟')
    default_strength = [min(v, total[0]) for v in default['strength']]
    strength = interval(plan.get('strengthMinutes', default_strength), '每周力量分钟')
    if strength[1] > total[0]:
        raise ValueError('训练计划力量分钟不得超过总训练分钟下限；力量时间已包含在总时长中')
    smet = interval(plan.get('sportMET', default['sport_met']), '专项MET', 1, 30)
    lmet = interval(plan.get('strengthMET', default['strength_met']), '力量MET', 1, 30)
    factor = 3.5 * weight / 200
    def bounds(net):
        values = [factor * ((m-net)*(t-s) + (l-net)*s)
                  for t in total for s in strength for m in smet for l in lmet]
        return [round(min(values), 8), round(max(values), 8)]
    gross, net = bounds(0), bounds(1)
    result.update(total_weekly_minutes=total, strength_weekly_minutes=strength,
                  sport_weekly_minutes=[total[0]-strength[1], total[1]-strength[0]],
                  sport_met=smet, strength_met=lmet, weight_kg=weight,
                  gross_weekly_kcal=gross, net_weekly_kcal=net,
                  net_daily_kcal=[v/7 for v in net],
                  gross_formula='MET × 3.5 × 体重kg ÷ 200 × 分钟',
                  net_formula='(MET − 1) × 3.5 × 体重kg ÷ 200 × 分钟',
                  schedule='采用个人训练计划覆盖值。' if plan else default['schedule'],
                  limitation='1 MET≈3.5 mL·kg⁻¹·min⁻¹。按整堂课平均强度估算，非实测；周净消耗÷7为自然日日均，不是单个训练日；未包含日常非训练活动和食物热效应，非完整全天总消耗。课表、出勤或训练阶段变化需更新个人训练分钟。')
    if resting is None:
        result['reason'] = '未填写有效静息代谢区间：仅展示训练消耗，沿用既有EER参考，绝不在已含活动的EER上重复加运动消耗。'
        return result
    result['applied'] = True
    return result


def training_energy_note(energy):
    t = energy.get('training_expenditure') or {}
    def span(values):
        return '–'.join(f'{v:.1f}'.rstrip('0').rstrip('.') for v in values)
    if not t.get('applied'):
        return t.get('reason', '')
    return (f"{t['sport']}训练计划估算：静息代谢区间{span(energy['resting_bounds'])} kcal/天＋"
            f"运动净消耗日均{span(t['net_daily_kcal'])} kcal/天（每周净{span(t['net_weekly_kcal'])}、"
            f"总{span(t['gross_weekly_kcal'])} kcal）。{t['schedule']}。{t['limitation']}")
