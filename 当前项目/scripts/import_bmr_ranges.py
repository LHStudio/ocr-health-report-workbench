"""Import an XLSX BMR table to a COPY of a saved questionnaire job.

Only unique exact names match. All rows remain in a private registry, including
unmatched rows. No personal data is bundled with this source script.
"""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nutrition_report.energy_reference import bmr_bounds


def read_ranges(path):
    w = load_workbook(path, data_only=True, read_only=True)
    try:
        rows = iter(w.active.values)
        headers = next(rows)
        if not (str(headers[0]).endswith('Name') and 'Lower Limit' in str(headers[1]) and 'Upper Limit' in str(headers[2])):
            raise ValueError('BMR表头不匹配')
        result = {}
        for row in rows:
            if not any(v is not None for v in row):
                continue
            name = str(row[0] or '').strip()
            if not name or name in result:
                raise ValueError('BMR姓名缺失或重复，停止导入')
            result[name] = bmr_bounds(dict(bmrMin=row[1], bmrMax=row[2]))
            if result[name] is None:
                raise ValueError('BMR表格存在空区间')
        return result
    finally:
        w.close()


def merge_ranges(people, ranges):
    result = deepcopy(people)
    counts = Counter(str((p.get('general') or {}).get('姓名') or '').strip() for p in people)
    matched = []
    for p in result:
        g = p.setdefault('general', {})
        name = str(g.get('姓名') or '').strip()
        if name not in ranges or counts[name] != 1:
            continue
        low, high = ranges[name]
        for key, value in [('BMR最低值',low),('BMR最高值',high)]:
            previous = g.get(key)
            if previous not in (None, '') and float(previous) != value:
                raise ValueError(f'{name}已有BMR与表格冲突，停止导入')
            g[key] = value
        matched.append(dict(person_id=p['id'], name=name, bmr_min=low, bmr_max=high))
    audit = dict(source_rows=len(ranges), matched_count=len(matched), matched=matched,
                 unmatched_names=[n for n in ranges if counts[n] == 0],
                 ambiguous_names=[n for n in ranges if counts[n] > 1])
    return result, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xlsx', required=True)
    parser.add_argument('--state', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--registry', required=True)
    args = parser.parse_args()
    source = Path(args.state).resolve(); output = Path(args.output).resolve()
    registry = Path(args.registry).resolve()
    if source == output or output.exists() or registry.exists():
        raise ValueError('输出须为不存在的新文件，不覆盖原始记录')
    ranges = read_ranges(args.xlsx)
    state = json.loads(source.read_text(encoding='utf-8'))
    state['people'], audit = merge_ranges(state['people'], ranges)
    output.parent.mkdir(parents=True, exist_ok=True)
    registry.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    registry.write_text(json.dumps(dict(ranges={n:dict(bmr_min=v[0],bmr_max=v[1]) for n,v in ranges.items()},audit=audit),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(audit,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
