"""Round personal gram targets for display, without rebuilding them from intake."""
import re


def attach_gram_display(report, food_db, merged_meals):
    for section in ('athlete_evaluation', 'food_standard_evaluation'):
        for row in report[section]['rows']:
            display = {key: row.get(key) for key in ('label', 'actual', 'unit', 'target', 'gap', 'note')}
            # Historical ratios without a plan cannot become gram requirements
            # by multiplying their bounds by actual intake.
            display['target'] = re.sub(r'\d+(?:\.\d+)?', lambda m: f'{float(m.group()):.2f}', str(display['target']))
            # A planned amount never becomes part of a normative target range.
            display['note'] = ''  # Keep detailed formulas in raw audit rows, not repeated in the table.
            for field in ('actual', 'gap'):
                if display.get(field) is not None:
                    display[field] = round(display[field], 2)
            row['display'] = display
