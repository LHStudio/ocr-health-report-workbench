"""Export a roster through the same adapter/service as the existing web app.

The roster export keeps the source workbook and questionnaire cache unchanged.
For this batch, common OCR shorthand is normalized to a practical serving size
before the normal report calculation so every exported PDF follows the same
complete-report layout. Food data remains cloud-first.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import openpyxl
from nutrition_report.service import NutritionReportService


SHRIMP_GRAMS_PER_PIECE = 15
EGG_WHITE_GRAMS_PER_PIECE = 30
MILK_POWDER_GRAMS_PER_SPOON = 10
DRINK_DEFAULT_ML = 500
COFFEE_DEFAULT_ML = 350


def archive_filename(result_count):
    return f'全部运动员营养报告_{result_count}人.zip'


def _number_range(text):
    numbers = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(text or ""))]
    if not numbers:
        return None
    if len(numbers) >= 2 and re.search(r"[-~～至/]", str(text)):
        return (numbers[0] + numbers[1]) / 2
    return numbers[0]


def apply_export_estimates(person):
    """Write fixed serving estimates into an export-only person copy.

    These are intentionally limited to the 17 OCR forms seen in this roster:
    medium shrimp are 15 g each, milk powder is 10 g per spoon, a standard
    packaged drink is 500 ml, coffee is 350 ml, and an 80/100 g dumpling range
    uses its midpoint. Existing numeric gram/ml values are preserved.
    """
    person = copy.deepcopy(person)
    for row in person.get('food_rows') or []:
        food = str(row.get('食物名称') or '').strip()
        raw = str(row.get('平均每次食用量') or '').strip()
        if not raw:
            continue
        if food == '虾' and re.search(r'(?:个|只)', raw):
            count = _number_range(raw)
            if count is not None:
                row['平均每次食用量'] = f'{round(count * SHRIMP_GRAMS_PER_PIECE):g}g'
        elif food == '蛋类' and re.search(r'蛋白|蛋清', raw):
            count = _number_range(raw)
            if count is not None:
                row['平均每次食用量'] = f'{round(count * EGG_WHITE_GRAMS_PER_PIECE):g}g'
        elif food == '奶粉' and '勺' in raw:
            count = _number_range(raw)
            if count is not None and count > 0:
                row['平均每次食用量'] = f'{round(count * MILK_POWDER_GRAMS_PER_SPOON):g}g'
        elif food == '包子/饺子' and re.search(r'\d+\s*/\s*\d+\s*\.?\s*g', raw, re.I):
            amount = _number_range(raw)
            if amount is not None:
                row['平均每次食用量'] = f'{round(amount):g}g'
        elif food in {'果汁饮料', '茶/茶饮料', '其他饮料', '咖啡'}:
            repaired = re.sub(r'^(\d+)\.\s*(毫升|ml|升|l|克|g|kg)$', r'\1\2', raw, flags=re.I)
            if repaired != raw:
                row['平均每次食用量'] = repaired
            elif not re.search(r'\d+(?:\.\d+)?\s*(?:毫升|ml|升|l|克|g|kg)', raw, re.I):
                amount = COFFEE_DEFAULT_ML if food == '咖啡' else DRINK_DEFAULT_ML
                row['平均每次食用量'] = f'{amount}ml'
    return person

def dump(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def export_roster(roster_path, state_path, output_dir, *, aliases=None, service=None, audit_dir=None):
    roster_path,state_path,output_dir=map(Path,(roster_path,state_path,output_dir))
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (roster_path,state_path)}
    cache=json.loads(state_path.read_text(encoding='utf-8'));people=cache['people']
    aliases=aliases or {};index={}
    for p in people:
        name=aliases.get(p['general'].get('姓名'),p['general'].get('姓名'))
        if name in index:raise ValueError(f'缓存存在重复姓名，需要按人员ID核对：{name}')
        index[name]=p
    service=service or NutritionReportService()
    output_dir.mkdir(parents=True,exist_ok=True)
    if audit_dir:Path(audit_dir).mkdir(parents=True,exist_ok=True)
    manifest={'roster':str(roster_path.resolve()),'source':str(state_path.resolve()),'results':[],'missing':[],
              'food_data_source':service.nutrition_service.food_data_source,'name_aliases':aliases}
    team='';modified=copy.deepcopy(cache);modified['people']=[]
    wb=openpyxl.load_workbook(roster_path,data_only=True,read_only=True)
    try:
        rows=list(wb.active.iter_rows(min_row=2,values_only=True))
    finally:wb.close()
    for raw_team,raw_name in rows:
        if raw_team:team=str(raw_team).strip()
        if not raw_name:continue
        name=re.sub(r'（.*?）|\(.*?\)','',str(raw_name)).strip()
        if name not in index:
            manifest['missing'].append({'name':name,'team':team,'reason':'无对应营养问卷缓存'});continue
        if team not in {'篮球队','足球队','体操队'}:raise ValueError(f'未配置队伍：{team}')
        person=copy.deepcopy(index[name]);sport=team.removesuffix('队')
        person=apply_export_estimates(person)
        person['general'].update({'姓名':name,'项目种类':sport,'运动类型':'strength' if sport=='体操' else 'team','运动量':'3'})
        adapted=service.adapt_ocr_person(person,include_quality_page=False)
        if not adapted.usable_food_count:raise ValueError(f'{name}没有可换算食物，不能导出零摄入报告')
        data=service.build_report_data({**adapted.payload,'report_style':'modern'})
        ready=data.get('report_status',data['assessment_status'])=='ready'
        folder=output_dir/team if ready else output_dir/'待核对'/team
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/(name+('_营养报告.pdf' if ready else '_待核对营养报告.pdf'))
        service.pdf_builder.build(data,path)
        person['general']['训练阶段']=data['user']['trainingPhase']
        modified['people'].append(person)
        a={r['key']:r for r in data['athlete_evaluation']['rows']}
        manifest['results'].append({'name':name,'team':team,'person_id':person['id'],'file':str(path.resolve()),
            'status':data.get('report_status',data['assessment_status']),'issues':data['assessment_issues']+data.get('recommendation_issues',[]),'energy':data['nutrition']['energy'],
            'protein':a['protein'],'carbohydrate':a['carbohydrate'],'fat':a['fat'],
            'report_checks':data.get('report_checks',{}),
            'personal_targets':data.get('food_standard_evaluation',{}).get('personal_targets',{}),
            'athlete_type':data['user']['athleteType'],
            'training_phase':data['user']['trainingPhase'],'activity_level':data['user']['activityLevel'],
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        if audit_dir:dump(Path(audit_dir)/(name+'_report_data.json'),data)
        print(name,data['assessment_status'],flush=True)
    manifest['counts']=dict(Counter(r['status'] for r in manifest['results']))
    manifest['roster_count']=len(manifest['results'])+len(manifest['missing'])
    manifest['archive']=archive_filename(len(manifest['results']))
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    manifest['source_hashes_unchanged']=hashes
    dump(output_dir/'导出清单.json',manifest)
    lines=[f"名单{manifest['roster_count']}人；已导出营养报告{manifest['counts'].get('ready',0)}份；待核对{manifest['counts'].get('needs_review',0)}份；无问卷缓存{len(manifest['missing'])}人。",
        '篮球、足球：团体（有氧+力量）；体操：力量为主；活动量高。训练阶段沿用项目默认训练期，显式选择优先。',
        '对虾、奶粉、包装饮料及区间份量采用统一常用份量估算后纳入计算。',
        '营养数据来源：'+str(manifest['food_data_source'].get('label'))]
    lines += ['', '缺少营养问卷：']+[r['name'] for r in manifest['missing']]
    (output_dir/'导出清单.txt').write_text('\n'.join(lines),encoding='utf-8-sig')
    if audit_dir:dump(Path(audit_dir)/'MODIFIED_FILE.json',modified)
    archive=output_dir/manifest['archive']
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for r in manifest['results']:z.write(r['file'],str(Path(r['file']).relative_to(output_dir)))
        for f in ('导出清单.json','导出清单.txt'):z.write(output_dir/f,f)
    with zipfile.ZipFile(archive) as z:assert z.testzip() is None
    return manifest

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roster',required=True);parser.add_argument('--state',required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--audit-dir')
    parser.add_argument('--name-alias',action='append',default=[],help='已确认的缓存姓名=名单姓名')
    args=parser.parse_args();aliases=dict(x.split('=',1) for x in args.name_alias)
    result=export_roster(args.roster,args.state,args.output,aliases=aliases,audit_dir=args.audit_dir)
    print(json.dumps({'counts':result['counts'],'missing':result['missing']},ensure_ascii=False))
if __name__=='__main__':main()
