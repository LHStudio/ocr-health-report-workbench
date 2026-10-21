"""Retain diagnostic evidence without vetoing or rewriting report output.

Report availability is not a claim of nutritional or solver validation.
No source/intake value, manual text, or mathematical result is changed.
"""
import math

# API composition values remain user-owned; only structural validity is gated.


def density_review(food_db, names):
    issues = []
    for name in sorted(set(names)):
        food = food_db.get(name, {})
        try:
            e, p, c, f, ca = (float(food[k]) for k in
                              ('energy', 'protein', 'carbohydrate', 'fat', 'calcium'))
        except (KeyError, TypeError, ValueError):
            issues.append(f'{name}营养参数缺失或无效，不能通过营养密度核验。')
            continue
        if not all(math.isfinite(v) and v >= 0 for v in (e, p, c, f, ca)):
            issues.append(f'{name}营养参数存在非有限值或负值，不能通过营养密度核验。')
        elif e == p == c == f == ca == 0:
            issues.append(f'{name}全部营养参数为0，需确认是否缺失占位，不能认定为零营养。')
        elif name == '薯条' and e > 0 and p == c == f == 0:
            issues.append(f'{name}能量非零但三大营养素全部为0，成分或单位待核对；保留API原值，不据此认定营养核验通过。')
    return issues


def apply_release_gate(report, policy, food_db):
    pending = [dict(x) for x in policy.get('pending', [])]
    if policy.get('status') != 'confirmed' and not pending:
        pending.append(dict(key='policy_approval', message='标准配置未明确确认，不能因待确认清单为空而默认通过。'))
    user = report.get('user') or {}
    if user.get('projectType') == '体操':
        pending.append(dict(key='gymnastics_mapping', message='体操项目归类待确认：不得把导出器的strength默认值当作用户确认的项目标准。'))
    report['standards_review'] = dict(version=policy.get('version'), pending=pending,
                                    status='pending' if pending else 'confirmed')
    names = [f['name'] for f in report.get('foods', []) if f.get('amount', 0) > 0]
    data_issues = density_review(food_db, names)
    report['density_review'] = dict(status='review' if data_issues else 'screening_passed',
                                   issues=data_issues, note='数值筛查通过不等于已认证营养成分或生熟口径。')
    checks = report['report_checks']
    for item in pending:
        checks['checks'].append(dict(code='standard_pending', key=item['key'],
                                    severity='info', message=item['message']))
    for i, message in enumerate(data_issues):
        checks['checks'].append(dict(code='density_review', key=str(i), severity='info', message=message))
    diagnostics = list(checks['checks'])
    report['recommendation_issues'] = list(dict.fromkeys(
        list(report.get('recommendation_issues', [])) + report.get('assessment_issues', []) +
        [c['message'] for c in diagnostics if c.get('message')]))
    # Never clear manual/automatic copy or mark an infeasible plan as validated.
    report['recommendation_status'] = 'available'
    report['report_status'] = 'ready'
    checks['status'] = 'review' if any(c.get('severity') == 'blocking' for c in diagnostics) else 'passed'
    report['publication_gate'] = dict(status='not_enforced', blocking_codes=[],
        diagnostic_codes=list(dict.fromkeys(c['code'] for c in diagnostics)))
