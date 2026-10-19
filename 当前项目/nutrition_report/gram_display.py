"""Round personal gram targets for display, without rebuilding them from intake."""
import re


def attach_gram_display(report, food_db, merged_meals):
    for section in ('athlete_evaluation', 'food_standard_evaluation'):
        for row in report[section]['rows']:
            display = {key: row.get(key) for key in ('label', 'actual', 'unit', 'target', 'gap', 'note')}
            # Historical ratios without a plan cannot become gram requirements
            # by multiplying their bounds by actual intake.
            if row.get('unit') == '%':
                display.update(unit='g/天', target='暂无法折算', gap=None,
                               note='缺少个人计划目标，不以实际摄入反推目标克数。')
            else:
                display['target'] = re.sub(r'\d+(?:\.\d+)?', lambda m: f'{float(m.group()):.2f}', str(display['target']))
                display['note'] = ''
            for field in ('actual', 'gap'):
                if display.get(field) is not None:
                    display[field] = round(display[field], 2)
            row['display'] = display
