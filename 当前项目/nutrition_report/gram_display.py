"""专项页的对外克数投影；内部百分比、边界与判断精度保持不变。"""
import re
from collections import defaultdict


def attach_gram_display(report, food_db, merged_meals):
    totals = defaultdict(lambda: defaultdict(float))
    for name, amount in merged_meals.items():
        info = food_db.get(name)
        if not info:
            continue
        bucket = totals[info.get('category', '')]
        bucket['grams'] += amount
        for key in ('energy', 'protein'):
            bucket[key] += float(info.get(key) or 0)*amount/100
    def total(groups, key='grams'):
        return sum(totals[group][key] for group in groups)
    def fmt(value):
        return f'{value:.2f}'
    def target_text(low, high, unit, original=''):
        if low is not None and high is not None and low != high:
            return f'{fmt(low)}–{fmt(high)} {unit}'
        if low is not None:
            return f'{"约" if original.startswith("约") else "≥"} {fmt(low)} {unit}'
        if high is not None:
            return f'≤ {fmt(high)} {unit}'
        return '暂无法折算'
    def gap(actual, low, high, basis):
        if actual is None or basis in {'quantity_first', 'quantity_unknown'}:
            return None
        return actual-low if low is not None and actual<low else actual-high if high is not None and actual>high else 0

    complete = report['food_standard_evaluation']['nutrient_record_complete']
    staple_energy = sum(f['nutrition']['energy'] for f in report['foods'] if f['category'] in {'谷类', '豆类', '薯类'})
    nutrition = report['nutrition']
    macro_energy = nutrition['protein']*4 + nutrition['carbohydrate']*4 + nutrition['fat']*9
    for section in ('athlete_evaluation', 'food_standard_evaluation'):
        for row in report[section]['rows']:
            key = row['key']
            display = {k:row.get(k) for k in ('label','actual','unit','target','gap','note')}
            display['note'] = display['note'] or ''
            if row['unit']=='%':
                low, high = row.get('target_min'), row.get('target_max')
                note = ''
                if key in {'beans_energy', 'tubers_energy', 'grains_remainder'}:
                    category, representative = {'beans_energy':('豆类','豆腐'), 'tubers_energy':('薯类','土豆'), 'grains_remainder':('谷类','米饭')}[key]
                    actual = total({category}) if complete else None
                    density = total({category}, 'energy')/actual if actual else None
                    if density:
                        note = '参考克数按当前该类食物加权能量密度折算。'
                    else:
                        info = food_db.get(representative)
                        if not info:
                            representative, info = next(((n, f) for n,f in food_db.items() if f.get('category')==category and f.get('energy',0)>0), ('',{}))
                        density = float(info.get('energy') or 0)/100 or None
                        note = f'无当前食物密度，参考克数以{representative}估算，变更食物后需复核。' if density else '缺少有效食物能量密度，暂无法折算目标克数。'
                    factor = staple_energy/100/density if density and complete else None
                    display['label'] = category
                elif key=='seafood':
                    actual = total({'水产品'}) if complete else None
                    factor = total({'畜禽肉','水产品'})/100 if complete else None
                    display['label'] = '水产品'
                    note = '参考克数按当前肉类总重量换算。'
                elif key=='quality_protein':
                    actual = total({'畜禽肉','水产品','蛋类','奶类'}, 'protein') if complete else None
                    factor = nutrition['protein']/100 if complete else None
                    display['label'] = '肉蛋奶优质蛋白'
                    note = '实际值为肉蛋奶提供的蛋白质克数，不是食物重量；参考克数按总蛋白质换算。'
                elif key=='fat':
                    actual = nutrition['fat'] if complete else None
                    factor = macro_energy/100/9 if complete else None
                    display['label'] = '脂肪'
                    note = '参考克数按记录饮食的三大营养素供能合计换算。'
                else:
                    continue
                lo = low*factor if low is not None and factor is not None else None
                hi = high*factor if high is not None and factor is not None else None
                display.update(actual=actual,unit='g/天',target=target_text(lo,hi,'g/天'),
                    gap=gap(actual,lo,hi,row.get('evaluation_basis')),note=note)
                if row.get('evaluation_basis')=='quantity_first':
                    display['note'] += '先补足总量；此结构参考不作为当前减量依据。'
                elif row.get('evaluation_basis')=='quantity_unknown':
                    display['note'] += '总量是否满足尚未确认，暂不评价结构。'
            elif key=='meat':
                display['actual'] = total({'畜禽肉','水产品'}) if complete else None
                value = row.get('target_grams')
                display['target'] = f'约 {fmt(value)} g/天' if value is not None else '暂无法折算'
                display['note'] = (row.get('note') or '').replace('−','-')
            else:
                # Round only the display string, never the internal comparison boundary.
                display['target'] = re.sub(r'\d+(?:\.\d+)?', lambda m:fmt(float(m.group())), str(display['target']))
            for field in ('actual', 'gap'):
                if display.get(field) is not None:
                    display[field] = round(display[field], 2)
            display['note'] = re.sub(r'\d+\.\d{3,}',lambda m:fmt(float(m.group())),display['note'])
            # Keep conversion provenance in the raw row, not in the outward report.
            if key in {'fat', 'vegetables', 'beans_energy', 'tubers_energy', 'grains_remainder',
                       'seafood', 'quality_protein', 'milk', 'eggs', 'livestock_remainder'}:
                display['note'] = ('缺少有效食物能量密度，暂无法折算目标克数。'
                                   if '缺少有效食物能量密度' in display['note'] else '')
            elif key == 'meat':
                display['note'] = display['note'].replace('按当前肉类（含水产品）加权蛋白质密度折算。', '')
            row['display'] = display
