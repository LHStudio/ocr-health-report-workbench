"""Fail closed on unresolved standards, questionable densities or report checks.

No new medical standard is chosen and no source/intake value is changed.
Suppressed legacy computations remain in explicit audit fields.
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
                                    severity='blocking', message=item['message']))
    for i, message in enumerate(data_issues):
        checks['checks'].append(dict(code='density_review', key=str(i), severity='blocking', message=message))
    blockers = [c for c in checks['checks'] if c.get('severity', 'blocking') == 'blocking']
    report['recommendation_issues'] = list(dict.fromkeys(
        list(report.get('recommendation_issues', [])) + report.get('assessment_issues', []) +
        [c['message'] for c in blockers]))
    plan = report.get('personal_targets') or {}
    passed = (report.get('assessment_status') == 'ready' and plan.get('status') == 'validated'
              and plan.get('validation', {}).get('passed') is True and not blockers)
    report['recommendation_status'] = 'validated' if passed else 'blocked'
    report['report_status'] = 'ready' if passed else 'needs_review'
    checks['status'] = 'passed' if passed else 'review'
    checks['warnings'] = list(dict.fromkeys(checks.get('warnings', []) + report['recommendation_issues']))
    report['publication_gate'] = dict(status='passed' if passed else 'blocked',
        requirements='体重项目→能量相容→分项规则→密度→全部食物复验→建议',
        blocking_codes=list(dict.fromkeys(c['code'] for c in blockers)))
    if passed:
        return
    if not report.get('autoEvaluation', True) and report.get('suggestions'):
        report['withheld_manual_suggestions'] = list(report['suggestions'])
    if report.get('interpretation'):
        report['withheld_interpretation'] = report.pop('interpretation')
    report['suggestions'] = []
    report['suggestion_items'] = []
    report['joint_plan_summary'] = '最终校验未通过。保留现有记录、已确认标准与复算数值；具体未通过项见核查提醒，不输出可执行食谱或增减建议。'
    report['energy_guidance'] = '能量及脂肪按已选定目标核算；配餐复验未通过，暂不输出食物增减或配餐建议。'
    pending_keys = {p['key'] for p in pending}
    if 'energy_scope' in pending_keys:
        energy = report['nutrition']['energy']
        energy['unconfirmed_comparison'] = energy.get('evaluation')
        energy['evaluation'] = '待确认'
    for row in report['athlete_evaluation']['rows']:
        if row['key'] == 'fat' and 'fat_basis' in pending_keys:
            row['unconfirmed_comparison'] = {k: row.get(k) for k in ('target', 'evaluation', 'machine_evaluation', 'gap')}
            row.update(evaluation='待确认', machine_evaluation='待确认', gap=None)
            row['display'].update(target='评价口径待确认', gap=None, evaluation='待确认')
    if plan.get('status') == 'validated':
        plan['numerical_status'] = 'validated'
        plan['status'] = 'review'
        plan['publication_status'] = 'blocked'
    for row in report['food_standard_evaluation']['rows']:
        for key in ('joint_plan_amount', 'plan_representative', 'plan_note'):
            if key in row:
                row.setdefault('withheld_plan_reference', {})[key] = row.pop(key)
