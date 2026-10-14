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
            if note in ('仅训练期', '60-70kg标准') and note not in parts:
                parts.append(note)
    return ' · '.join(p for p in parts if p)


def evaluation_rows(data):
    rows = {}
    for section in ('athlete_evaluation', 'food_standard_evaluation'):
        for row in (data.get(section) or {}).get('rows', []):
            rows[row['key']] = {**row, 'note': clean_display_text(row.get('note', ''))}
    for row in rows.values():
        if row['key'] in {'beans_energy', 'tubers_energy', 'grains_remainder'}:
            row['evaluation'] = {'不足': '能量占比偏低', '过多': '能量占比偏高', '适中': '能量占比适中'}.get(row.get('evaluation'), row.get('evaluation'))
    return list(rows.values())


def evaluation_warnings(data):
    notes = []
    for section in ('athlete_evaluation', 'food_standard_evaluation'):
        for note in (data.get(section) or {}).get('warnings', []):
            if not any(text in note for text in ('原文未明确年龄分界', '每项定量规则达标')) and note not in notes:
                note = clean_display_text(note)
                if note not in ('仅训练期', '60-70kg标准') and note not in notes:
                    notes.append(note)
    return notes
