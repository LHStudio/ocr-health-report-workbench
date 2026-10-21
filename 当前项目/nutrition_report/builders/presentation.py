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
    parts = [(data.get('athlete_evaluation') or {}).get('athlete_label', '')]
    for section in ('athlete_evaluation', 'food_standard_evaluation'):
        for note in (data.get(section) or {}).get('warnings', []):
            note = clean_display_text(note)
            if note in ('仅训练期', '60-70kg标准', '基础膳食参考标准') and note not in parts:
                parts.append(note)
    return ' · '.join(p for p in parts if p)


def evaluation_rows(data):
    rows = {}
    for section in ('athlete_evaluation', 'food_standard_evaluation'):
        for row in (data.get(section) or {}).get('rows', []):
            display = {**row, **(row.get('display') or {})}
            rows[row['key']] = {**display, 'note': clean_display_text(display.get('note', ''))}
    return list(rows.values())


def evaluation_warnings(data):
    if data.get('report_status') == 'needs_review':
        return ['最终校验未通过：本页仅为原记录与原规则核查，非已批准的营养建议；完整原因见最后一页。']
    notes = []
    for section in ('athlete_evaluation', 'food_standard_evaluation'):
        for note in (data.get(section) or {}).get('warnings', []):
            note = _display_warning(note)
            if not note:
                continue
            if note.startswith(('奶粉、奶酪折算鲜奶等价量', '蔬菜最低400g/天')):
                continue
            if '%' in note or '优质蛋白=' in note or '水产品占比' in note:
                continue
            if not any(text in note for text in ('原文未明确年龄分界', '每项定量规则达标')) and note not in notes:
                note = clean_display_text(note)
                if note not in ('仅训练期', '60-70kg标准', '基础膳食参考标准') and note not in notes:
                    notes.append(note)
    for note in report_alerts(data):
        if note not in notes:
            notes.append('自动核查提醒：' + note)
    return notes


def _display_warning(note):
    """Hide requested explanatory copy only; retain underlying audit messages."""
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
    notes = [text for note in checks.get('warnings', []) if (text := _display_warning(note))]
    # Filtering explanatory copy must NEVER erase an export blocker.
    notes += [('训练能量只是计划估算，不能确认全天总消耗；完整参数保留在核查证据。'
               if c.get('code') == 'training_energy_estimate' else c['message']) for c in checks.get('checks', [])
              if c.get('severity') == 'blocking' and c.get('message')]
    if data.get('report_status') == 'needs_review' or checks.get('status') == 'review':
        notes.insert(0, '最终校验未通过／待确认：本报告不输出增减或配餐建议。')
    return list(dict.fromkeys(notes))
