"""Presentation-only union; calculation data and manual decisions stay untouched."""


def clean_display_text(text):
    for old, new in (
        ('；参数来自用户提供文档，需营养专业人员审核。', ''),
        ('，因此谷类占比上限为80%，不是必须达到80%。', '。'),
        ('；采用最低量规则，不以先前500g封顶。', '。'),
        ('；显式克数不二次折算', ''),
    ):
        text = text.replace(old, new)
    return text


def evaluation_context(data):
    # Classification thresholds and scope are internal calculation metadata.
    return ''


def evaluation_rows(data):
    rows = {}
    for section in ('athlete_evaluation', 'food_standard_evaluation'):
        for row in (data.get(section) or {}).get('rows', []):
            display = {**row, **(row.get('display') or {})}
            rows[row['key']] = {**display, 'note': clean_display_text(display.get('note', ''))}
    category_keys = {'谷类': 'grains_remainder', '薯类': 'tubers_energy',
        '蔬菜': 'vegetables', '水果': 'fruit', '畜禽肉': 'livestock_remainder',
        '水产品': 'seafood', '蛋类': 'eggs', '豆类': 'beans_energy',
        '坚果': 'nuts', '奶类': 'milk', '零食': 'snacks'}
    categories = dict(data.get('category_result') or {})
    if 'category_result' in data:
        categories.setdefault('运动营养食品', {'value': None, 'evaluation': '-'})
    for category, info in categories.items():
        key = category_keys.get(category, 'category_' + category)
        if key in rows:
            continue
        value = info.get('value')
        if not isinstance(value, (int, float)):
            value = None
        rows[key] = dict(key=key, label=category, actual=value, unit='g/天',
                         target='—', gap=None, evaluation=info.get('evaluation', '-'),
                         note=info.get('weight_note', ''))
    ordered = list(rows.values())
    keys = ('grains_remainder', 'tubers_energy', 'beans_energy')
    staples = iter(rows[k] for k in keys if k in rows)
    return [next(staples) if row['key'] in keys else row for row in ordered]


def evaluation_warnings(data):
    # Keep only factual missing-input notices, never policy or scoring prose.
    notes = []
    for section in ('athlete_evaluation', 'food_standard_evaluation'):
        for note in (data.get(section) or {}).get('warnings', []):
            if note.startswith(('缺少体重', '缺少有效体重', '缺少年龄', '缺少有效年龄')) and note not in notes:
                notes.append(note)
    return notes


def _display_warning(note):
    """Hide requested explanatory copy only; retain underlying audit messages."""
    if '工程筛查' in note:
        if '，达到参考' in note:
            return note.split('，达到参考', 1)[0] + '，请核对份量、单位及频率。'
        if note.startswith('总能量记录达到参考值的'):
            return '请核对总能量记录所用的份量、单位及频率。'
        if ' 超过单项' in note:
            return note.split(' 超过单项', 1)[0] + '，请核对份量、单位及频率。'
    if note.startswith('示例食谱脂肪'):
        return ''
    if note.startswith(('代表食物估算（需复核）：', '足球训练计划估算：', '篮球训练计划估算：')):
        return ''
    if note.startswith('既有优质蛋白至少一半约束下，示例食谱蛋白质计划点由'):
        if '仍在个人蛋白质参考范围内' in note:
            return ''
        if '已超个人蛋白质参考上限' in note:
            return '示例食谱蛋白质超出个人参考上限，现有食谱约束不相容；请核对约束。'
    return note


def report_alerts(data):
    checks = data.get('report_checks') or {}
    # Keep optional solver/policy diagnostics out of the original report copy.
    internal = {c.get('message') for c in checks.get('checks', [])
                if c.get('code') in {'target_plan_review', 'macro_energy_conflict', 'standard_pending',
                                      'machine_evaluation_corrected', 'machine_advice_corrected',
                                      'staple_mix_reallocation', 'bmr_reference_scope',
                                      'training_energy_estimate', 'training_energy_pending'}}
    notes = list(dict.fromkeys(text for note in checks.get('warnings', [])
                               if note not in internal and (text := _display_warning(note))))
    return ['；'.join(notes)] if notes else []
