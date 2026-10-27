"""Persisted, identity-bound examination results; never infer missing measurements."""
import json
import os
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
    values = (data.get('body_composition') or {}).get('values') or {}
    return [(label, values.get(key), unit) for key, label, unit in BODY_FIELDS]


def resting_metabolism_rows(data):
    record = data.get('resting_metabolism') or {}
    if not record:
        return []
    values = record.get('values') or {}
    return [(label, values.get(key), unit) for key, label, unit in METABOLIC_FIELDS]


def measurement_text(value, unit=''):
    if value is None or value == '':
        return ''
    text = f'{value:g}' if isinstance(value, (float, int)) else str(value)
    return text + (' ' + unit if unit else '')
