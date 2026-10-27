"""Display quantities in grams; retain percentage rules and scores internally."""
import math
import re
from collections import defaultdict
from .personal_targets import REPRESENTATIVES
from .food_conversion import staple_equivalent_grams


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError):
        return None


def _target(low, high):
    if low is None and high is None:
        return '—'
    if low is None:
        return f'≤ {high:.2f} g/天'
    if high is None:
        return f'≥ {low:.2f} g/天'
    return f'{low:.2f}–{high:.2f} g/天'


def attach_gram_display(report, food_db, merged_meals, *, recorded_meals=None):
    totals = defaultdict(lambda: {'grams': 0.0, 'energy': 0.0, 'energy_known': True, 'grams_known': True})
    for name, amount in merged_meals.items():
        info = food_db.get(name)
        amount = _number(amount)
        if not info or amount is None:
            continue
        total = totals[info.get('category')]
        recorded = _number((recorded_meals or {}).get(name, amount))
        shown_grams = recorded if recorded is not None else amount
        if info.get('category') in {'谷类', '薯类', '豆类'}:
            shown_grams = staple_equivalent_grams(name, amount, info['category'])
        if shown_grams is None:
            total['grams_known'] = False
        else:
            total['grams'] += shown_grams
        energy = _number(info.get('energy'))
        if amount and energy is None:
            total['energy_known'] = False
        elif energy is not None:
            total['energy'] += amount * energy / 100
    staples = ('谷类', '豆类', '薯类')
    staple_weight = sum(totals[k]['grams'] for k in staples)
    staple_known = all(totals[k]['grams_known'] for k in staples)
    meat_grams = totals['畜禽肉']['grams'] + totals['水产品']['grams']
    ratio_keys = {'beans_energy', 'tubers_energy', 'grains_remainder', 'seafood', 'livestock_remainder'}
    for section in ('athlete_evaluation', 'food_standard_evaluation'):
        for row in report[section]['rows']:
            display = {key: row.get(key) for key in ('label', 'actual', 'unit', 'target', 'gap', 'note')}
            if row['key'] in ratio_keys and row.get('unit') == '%':
                category, representative = REPRESENTATIVES[row['key']]
                total = totals[category]
                factor = None
                if category in staples and staple_known and staple_weight > 0:
                    factor = staple_weight / 100
                elif category not in staples and meat_grams > 0:
                    factor = meat_grams / 100
                # Convert the existing internal ratio bounds at the same recorded
                # denominator. This is display conversion, not a new dietary rule.
                known = row.get('actual') is not None and total['grams_known']
                low = row.get('target_min')
                high = row.get('target_max')
                low = low * factor if low is not None and factor is not None and known else None
                high = high * factor if high is not None and factor is not None and known else None
                actual = total['grams'] if known else None
                gap = None
                if actual is not None and factor is not None and row.get('gap') is not None:
                    gap = actual-low if low is not None and actual < low else actual-high if high is not None and actual > high else 0.0
                display.update(label=category, actual=actual, unit='g/天', target=_target(low, high), gap=gap)
            elif row.get('unit') == 'mg/天':
                display['unit'] = 'mg/天'
                display['target'] = row['target']
            else:
                display['target'] = re.sub(r'\d+(?:\.\d+)?', lambda m: f'{float(m.group()):.2f}', str(display['target']))
            if row.get('evaluation_basis') == 'energy_priority':
                display.update(target='先补足主食，再调整谷豆薯比例', gap=None)
            if row['key'] == 'beans_energy':
                display['label'] = '豆类（大豆等价量）'
            if row['key'] == 'milk':
                display['label'] = '奶类'
            elif row['key'] == 'quality_protein':
                display['label'] = '肉蛋奶\n优质蛋白占比'
            display['note'] = ''
            if row.get('ratio_basis') == 'equivalent_weight' and row.get('evaluation_basis') != 'energy_priority':
                display['note'] = row['note']
            for field in ('actual', 'gap'):
                if display.get(field) is not None:
                    display[field] = round(display[field], 2)
            row['display'] = display
