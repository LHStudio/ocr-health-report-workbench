"""Persisted, identity-bound examination results; never infer missing measurements."""
import json
import os
import math
from copy import deepcopy
from pathlib import Path

BODY_FIELDS = (
    ('height', '身高', 'cm'), ('date_of_birth', '出生日期', ''),
    ('age', '年龄', '岁'), ('weight', '体重', 'kg'),
    ('bfm', '体脂肪量（BFM）', 'kg'), ('ffm', '去脂体重（FFM）', 'kg'),
    ('bmi', '身体质量指数（BMI）', 'kg/m²'), ('pbf', '体脂率（PBF）', '%'),
    ('vfl', '内脏脂肪等级（VFL）', '级'), ('vfa', '内脏脂肪面积（VFA）', 'cm²'),
    ('asmi', '四肢骨骼肌指数（ASMI）', 'kg/m²'),
)
METABOLIC_FIELDS = (
    ('REE', '静息能量消耗（REE）', 'kcal/天'),
    ('FAT%', '脂肪消耗占比（FAT%）', '%'),
    ('CHO%', '碳水化合物消耗占比（CHO%）', '%'),
    ('PRO%', '蛋白质消耗占比（PRO%）', '%'),
)


def load_person_measurements(person, path=None):
    """Match both saved person id and exact name, not filename or fuzzy name."""
    path = Path(path or os.environ.get('NUTRITION_MEASUREMENTS_PATH') or
                Path(__file__).resolve().parents[1] / 'data' / 'imported_measurements.json')
    if not path.exists():
        return {}
    registry = json.loads(path.read_text(encoding='utf-8'))
    general = person.get('general') or {}
    name = str(general.get('姓名') or '').strip()
    person_id = str(person.get('id') or '').strip()
    subject_id = str(general.get('受试者编号') or '').strip()
    matches = [record for record in registry.get('records', [])
               if record['name'] == name and record['person_id'] == person_id
               and (not subject_id or not record.get('subject_id')
                    or subject_id == record['subject_id'])]
    if len(matches) > 1:
        raise ValueError('体成分/静息代谢存档存在重复身份，请核对')
    return matches[0] if matches else {}


def body_composition_rows(data):
    record = data.get('body_composition') or {}
    values = record.get('values') or {}
    return [(label + ('（估算）' if key in record.get('estimated_fields', {}) else ''), values.get(key), unit) for key, label, unit in BODY_FIELDS]


def resting_metabolism_rows(data):
    record = data.get('resting_metabolism') or {}
    if not record:
        return []
    values = record.get('values') or {}
    return [(label + ('（估算）' if key in record.get('estimated_fields', {}) else ''), values.get(key), unit) for key, label, unit in METABOLIC_FIELDS]


def apply_approved_estimates(person, measurements, user, path=None):
    """Apply only explicitly approved identity-bound estimates; retain real data."""
    path = Path(path or os.environ.get('NUTRITION_ESTIMATES_PATH') or
                Path(__file__).resolve().parents[1] / 'data' / 'nutrition_measurement_estimates.json')
    result, user = deepcopy(measurements), dict(user)
    if not path.exists():
        return result, user
    general = person.get('general') or {}
    matches = [r for r in json.loads(path.read_text('utf-8')).get('records', [])
               if r.get('approved') is True and r.get('person_id') == str(person.get('id') or '').strip()
               and r.get('name') == str(general.get('姓名') or '').strip()
               and r.get('project_type') == user.get('projectType') and r.get('gender') == user.get('gender')]
    if len(matches) > 1:
        raise ValueError('估算存档存在重复身份，请核对')
    if not matches:
        return result, user
    estimate = matches[0]
    for field, section in [('ffm', 'body_composition'), ('REE', 'resting_metabolism')]:
        value = estimate.get('values', {}).get(field)
        existing = (result.get(section) or {}).get('values') or {}
        if value is None or existing.get(field) not in (None, ''):
            continue
        if field == 'ffm' and user.get('fatFreeMass') not in (None, ''):
            continue
        if field == 'REE' and any(user.get(k) not in (None, '') for k in ['restingMeasuredRee', 'bmrMin', 'bmrMax']):
            continue
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError('批准估算值须为有限正数')
        if field == 'ffm' and user.get('weight') not in (None, '') and value >= float(user['weight']):
            raise ValueError('估算去脂体重须小于体重')
        record = deepcopy(result.get(section) or {})
        record.setdefault('values', {})[field] = value
        record.setdefault('estimated_fields', {})[field] = {
            'method': estimate.get('method'), 'sample_count': estimate.get('sample_counts', {}).get(field),
            'sources': estimate.get('sources', {}).get(field, []), 'approved_date': estimate.get('approved_date')}
        result[section] = record
        if field == 'ffm':
            user.update(fatFreeMass=value, fatFreeMassEstimated=True)
    return result, user


def measurement_text(value, unit=''):
    if value is None or value == '':
        return ''
    text = f'{value:g}' if isinstance(value, (float, int)) else str(value)
    return text + (' ' + unit if unit else '')
