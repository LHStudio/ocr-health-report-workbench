"""Explicit cooked/raw weight conversion; database nutrient values are unchanged."""
from .report_policy import finite


# Edible product grams per gram of dry-bean equivalent, supplied by the user.
SOY_PRODUCT_RATIOS = {'豆腐': 5.2, '豆腐丝/千张/豆腐干': 1.9, '豆浆': 14.6,
                      '黑豆': 1.0, '大豆': 1.0}


def soy_equivalent_grams(name, grams):
    grams = finite(grams)
    ratio = SOY_PRODUCT_RATIOS.get(name)
    if grams is None or grams < 0 or ratio is None:
        return None
    return grams / ratio


def staple_equivalent_grams(name, grams, category):
    """Input is database weight after normalize_meals, never recorded cooked weight."""
    grams = finite(grams)
    if grams is None or grams < 0:
        return None
    if category == '豆类':
        return soy_equivalent_grams(name, grams)
    if category == '谷类':
        return grams / 2 if name == '米饭' else grams / 1.5 if name == '馒头' else grams
    if category == '薯类':
        return grams
    return None


def staple_equivalents(payload, food_db):
    totals = {c: 0.0 for c in ('谷类', '薯类', '豆类')}
    unknown = set()
    for meal in payload.get('meals') or []:
        name = meal.get('name')
        category = food_db.get(name, {}).get('category')
        if category not in totals:
            continue
        grams = staple_equivalent_grams(name, meal.get('amount'), category)
        if grams is None:
            unknown.add(category)
        else:
            totals[category] += grams
    return {c: None if c in unknown else value for c, value in totals.items()}


def bean_equivalent(payload, food_db):
    total, recorded, complete, items = 0.0, 0.0, True, []
    for meal in payload.get('meals') or []:
        name = meal.get('name')
        if food_db.get(name, {}).get('category') != '豆类':
            continue
        grams = finite(meal.get('amount'))
        equivalent = soy_equivalent_grams(name, grams)
        if equivalent is None:
            complete = False
        else:
            total += equivalent
            recorded += grams
        items.append(dict(food=name, recorded_grams=grams,
                          product_per_soy_gram=SOY_PRODUCT_RATIOS.get(name),
                          soy_equivalent_grams=equivalent))
    return dict(value=total if complete else None, unit='g/天', basis='大豆等价量',
                recorded_grams=recorded if complete else None, items=items,
                note='豆腐÷5.2；豆腐丝/千张/豆腐干÷1.9；豆浆÷14.6；原豆按原重。营养素仍按实际食品计算。')


def normalize_meals(payload):
    meals = []
    for original in payload.get('meals') or []:
        meal = dict(original)
        name = str(meal.get('name', '')).strip()
        amount = finite(meal.get('amount'))
        # OCR adapter has already applied this conversion exactly once.
        if 'conversion_factor' not in meal and amount is not None and amount >= 0:
            if name == '馒头':
                meal.update(name='小麦面粉', amount=amount/1.5, recorded_amount=amount,
                            recorded_food=name, conversion_factor=1/1.5,
                            conversion_basis='面粉:馒头=1:1.5')
            elif name in {'大米','生米'}:
                meal.update(name='米饭', amount=amount*2, recorded_amount=amount,
                            recorded_food=name, conversion_factor=2,
                            conversion_basis='生米:熟米饭=1:2')
            elif name == '米饭':
                meal.update(recorded_amount=amount, recorded_food=name, conversion_factor=1,
                            conversion_basis='生米:熟米饭=1:2；米饭库为熟重，不重复折算')
        meals.append(meal)
    return {**payload, 'meals': meals}


def attach_conversion_display(report, payload, food_db):
    recorded = {}
    trace = []
    raw = {'生米': 0.0, '面粉': 0.0}
    for meal in payload.get('meals') or []:
        name = meal.get('name')
        food = food_db.get(name)
        if not food:
            continue
        amount = finite(meal.get('amount'))
        original = finite(meal.get('recorded_amount', amount))
        if amount is None or original is None:
            continue
        category = food.get('category')
        recorded[category] = recorded.get(category, 0) + original
        if meal.get('conversion_basis'):
            trace.append(dict(food=meal.get('recorded_food',name), recorded_grams=original,
                              database_food=name, database_grams=amount,
                              basis=meal['conversion_basis']))
            if name == '米饭': raw['生米'] += amount/2
            elif name == '小麦面粉': raw['面粉'] += amount
    for category, value in recorded.items():
        info = report['category_result'].get(category)
        if info is not None:
            info['database_weight_g'] = info['value']
            info['value'] = round(value, 2)
    beans = bean_equivalent(payload, food_db)
    report['bean_equivalent'] = beans
    if '豆类' in report['category_result']:
        info = report['category_result']['豆类']
        info['recorded_weight_g'] = beans['recorded_grams']
        info['value'] = round(beans['value'], 2) if beans['value'] is not None else None
        info['weight_basis'] = '大豆等价量'
        info['weight_note'] = '大豆等价量' if beans['value'] is not None else '大豆等价量待确认'
    report['weight_conversions'] = trace
    equivalents = staple_equivalents(payload, food_db)
    report['staple_equivalents'] = equivalents
    for category in ('谷类', '薯类'):
        info = report['category_result'].get(category)
        if info is not None:
            info['recorded_weight_g'] = recorded.get(category, 0)
            info['value'] = round(equivalents[category], 2) if equivalents[category] is not None else None
            info['weight_basis'] = '原粮等价量' if category == '谷类' else '记录重量'
    # Export direct-JSON conversions as well as OCR conversion records.
    warnings = list(report.get('conversion_warnings') or [])
    if beans['items'] and not any(w.get('code') == 'soy_equivalent_conversion' for w in warnings):
        warnings.append(dict(severity='info', code='soy_equivalent_conversion', food='豆类',
                             message=beans['note']))
    for item in trace:
        if not any(w.get('code') == 'cooked_weight_conversion' and w.get('food') == item['food'] for w in warnings):
            warnings.append(dict(severity='info', code='cooked_weight_conversion', food=item['food'],
                message=f"{item['food']}记录{item['recorded_grams']:g}g/天；{item['basis']}；数据库{item['database_food']}计算量{item['database_grams']:g}g/天"))
    report['conversion_warnings'] = warnings
    if trace and '谷类' in report['category_result']:
        report['category_result']['谷类']['weight_note'] = '；'.join(
            f'{name}折算{value:.1f}g' for name,value in raw.items() if value > 0)
