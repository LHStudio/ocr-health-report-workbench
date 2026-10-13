"""Presentation-only union; calculation data and manual decisions stay untouched."""


def evaluation_rows(data):
    rows = {}
    for section in ('athlete_evaluation', 'food_standard_evaluation'):
        for row in (data.get(section) or {}).get('rows', []):
            rows[row['key']] = row
    return list(rows.values())


def evaluation_warnings(data):
    notes = []
    for section in ('athlete_evaluation', 'food_standard_evaluation'):
        for note in (data.get(section) or {}).get('warnings', []):
            if not any(text in note for text in ('原文未明确年龄分界', '每项定量规则达标')) and note not in notes:
                notes.append(note)
    return notes
