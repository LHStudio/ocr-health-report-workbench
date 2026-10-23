"""Explicit, audited XLSX push for imaging/lab. No OCR auto-push hooks."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import re
import sys
import unicodedata
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import openpyxl
from openpyxl.utils.datetime import from_excel, WINDOWS_EPOCH
import requests

IMAGING_COLUMNS = ['姓名', '性别', '年龄', '超声所见', '超声诊断', '检查时间']
IMAGING_METADATA_COLUMNS = {'病人ID', '文件名', '需核对字段'}
LAB_KEYS = ['序号','姓名','年龄','性别','病历号','报告日期','TRF','VD','IGF1','hGH','FT3','FT4','TSH','P','T','FSH','androstenedione','AMH','ovarianScore','reserveDeclineAge','menopauseAge','LH','E2','PRL','ovarianGrade','WBC','RBC','HGB','HCT','MCV','MCH','MCHC','PLT','lymphPercent','eoPercent','basoPercent']
LAB_LABELS = ['序号','姓名','年龄','性别','病历号','报告日期','转铁蛋白TRF（mg/dL）','25-羟维生素DVD（ng/mL）','类胰岛素样生长因子IGF1（ng/mL）','生长激素hGH（ng/mL）','游离三碘甲状腺原氨酸FT3（pg/mL）','游离甲状腺素FT4（ng/dL）','促甲状腺素TSH（uIU/mL）','孕酮P（nmol/L）','睾酮T（nmol/L）','卵泡生成素FSH（mIU/mL）','雄烯二酮（nmol/L）','抗缪勒管激素AMH（ng/mL）','卵巢储备评估得分','推测卵巢储备减退年龄（岁）','推测围绝经期开始年龄（岁）','促黄体生成素LH（mIU/mL）','雌二醇E2（pmol/L）','垂体泌乳素PRL（ng/mL）','卵巢功能等级','白细胞WBC（×10^9/L）','红细胞RBC（×10^12/L）','血红蛋白HGB（g/L）','红细胞压积HCT','平均红细胞体积MCV（fL）','平均血红蛋白含量MCH（pg）','平均血红蛋白浓度MCHC（g/L）','血小板PLT（×10^9/L）','淋巴细胞百分数LYMPH%（%）','嗜酸性粒细胞百分数EO%（%）','嗜碱性粒细胞百分数BASO%（%）']

def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf-8')

def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()

def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
    tmp.replace(path)

def report_date(value,epoch=WINDOWS_EPOCH):
    if isinstance(value,(date,datetime)):return value.strftime('%Y-%m-%d')
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        if not math.isfinite(value):raise ValueError('非有限日期')
        converted=from_excel(value,epoch)
        if not isinstance(converted,(date,datetime)):raise ValueError('日期仅含时间，无年月日')
        return report_date(converted)
    text=re.sub(r'\s+','',unicodedata.normalize('NFKC',str(value or '')))
    match=re.fullmatch(r'(\d{4})(?:年|[-./])(\d{1,2})(?:(?:月|[-./])(\d{1,2})日?|月)?((?:T?\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?)',text)
    if not match:raise ValueError('报告日期缺失或无法识别：'+text)
    y,m,d,clock=match.groups()
    if d is None or int(d)==0:raise ValueError('无法确定具体日，请核对原报告：'+text)
    normalized=date(int(y),int(m),int(d)).isoformat()
    if clock:datetime.fromisoformat(normalized+'T'+clock.lstrip('T').replace('Z','+00:00'))
    return normalized

def endpoint_url(base,kind):
    if kind not in ('imaging','lab'):raise ValueError('未知报告类型')
    parts=urlsplit(base.strip())
    allowed=('', '/api', '/open/'+kind, '/api/open/'+kind)
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path.rstrip('/') not in allowed:
        raise ValueError('需使用已确认的HTTPS根地址或/api前缀，不允许凭证、查询参数或其他路径')
    return urlunsplit((parts.scheme,parts.netloc,('/api' if parts.path.rstrip('/').startswith('/api') else '')+'/open/'+kind,'',''))

def cell_value(value,key):
    if isinstance(value,str) and value.startswith('='):
        match=re.fullmatch(r'="([^"]*)"',value)
        if key=='病历号' and match:return match.group(1)
        raise ValueError('不接受未计算的公式：'+key)
    if isinstance(value,float) and not math.isfinite(value):raise ValueError('非有限数值：'+key)
    if isinstance(value,(date,datetime)):return value.strftime('%Y-%m-%d')
    return value

def prepare(path,kind):
    if kind not in ('imaging','lab'):raise ValueError('未知报告类型')
    path=Path(path);wb=openpyxl.load_workbook(path,read_only=True,data_only=False)
    items=[];rejected=[];identities=set()
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        if len(wb.sheetnames)!=1:raise ValueError('要求单表输入，避免误推其他工作表')
        rows=list(wb.active.values);header_index=0 if kind=='imaging' else 1
        if len(rows)<=header_index:raise ValueError('缺少表头')
        raw=[re.sub(r'\s+','',str(v or '')) for v in rows[header_index]]
        if kind=='imaging':
            allowed=set(IMAGING_COLUMNS)|IMAGING_METADATA_COLUMNS
            if len(raw)!=len(set(raw)) or not set(IMAGING_COLUMNS)<=set(raw) or not set(raw)<=allowed:
                raise ValueError('影像表头缺失、重复或存在未知字段：'+repr(raw))
            selected=[(k,raw.index(k)) for k in IMAGING_COLUMNS]
            name_index=raw.index('姓名')
        else:
            if raw!=LAB_LABELS:raise ValueError('表头不符合已核对的接口契约：'+repr(raw))
            selected=[(k,i) for i,k in enumerate(LAB_KEYS) if k!='序号']
            name_index=LAB_KEYS.index('姓名')
        for row_number,row in enumerate(rows[header_index+1:],header_index+2):
            # Blank preallocated lab rows contain only a sequence number.
            if not any(v not in (None,'') for v in (row[1:] if kind=='lab' else row)):continue
            try:
                payload={k:cell_value(row[i],k) for k,i in selected if row[i] not in (None,'')}
                name=str(payload.get('姓名') or '').strip()
                if not name:raise ValueError('姓名缺失')
                payload['姓名']=name
                date_key='检查时间' if kind=='imaging' else '报告日期'
                normalized=report_date(payload.get(date_key),wb.epoch)
                if kind=='imaging' and not any(str(payload.get(k) or '').strip() for k in ('超声所见','超声诊断')):raise ValueError('超声所见和超声诊断均为空')
                if kind=='lab' and not any(k in payload for k in LAB_KEYS[6:]):raise ValueError('无检验结果')
                identity=(name,normalized)
                if identity in identities:raise ValueError('同一姓名同一报告日期重复，禁止静默覆盖')
                identities.add(identity)
                # Normalize only the outgoing payload; never rewrite workbook columns/cells.
                payload[date_key]=normalized
                encoded(payload)
                items.append(dict(source=str(path.resolve()),source_sha256=sha,row=row_number,name=name,analysisDate=normalized,payload=payload))
            except (ValueError,TypeError,OverflowError) as exc:
                rejected.append({'row':row_number,'name':str(row[name_index] or ''),'error':str(exc)})
        if any('重复' in r['error'] for r in rejected):raise ValueError('批次包含重复人员/日期，请先核对')
        return items,rejected
    finally:wb.close()

def valid_receipt(body,item):
    if not isinstance(body,dict) or type(body.get('code')) is not int or body['code']!=0:return False
    d=body.get('data')
    return isinstance(d,dict) and isinstance(d.get('athleteId'),str) and bool(d['athleteId']) and isinstance(d.get('analysisId'),str) and bool(d['analysisId']) and d.get('name')==item['name'] and d.get('analysisDate')==item['analysisDate'] and type(d.get('created')) is bool

def post(endpoint,token,payload):
    r=requests.post(endpoint,headers={'X-Open-Token':token,'Content-Type':'application/json'},data=encoded(payload),timeout=(10,45),allow_redirects=False)
    try:body=r.json()
    except ValueError:body={'invalid_json':True,'body_preview':r.text[:500]}
    return r.status_code,body

def execute(items,endpoint,token,audit_dir,*,send=post):
    kind=endpoint.rsplit('/',1)[-1];endpoint=endpoint_url(endpoint,kind)
    if not token or '\n' in token or '\r' in token:raise ValueError('请设置有效SURVEY_OPEN_TOKEN')
    directory=Path(audit_dir);directory.mkdir(parents=True,exist_ok=True)
    lock=directory/'push.lock';handle=lock.open('x')
    try:
        handle.write(str(os.getpid()));handle.close()
        path=directory/'checkpoint.json';batch=digest({'endpoint':endpoint,'items':items})
        state=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'batch':batch,'endpoint':endpoint,'records':{}}
        if state['batch']!=batch:raise ValueError('目标或输入变化，不得复用此检查点')
        for item in items:
            key=digest(item)
            if key in state['records']:continue
            rec={k:v for k,v in item.items() if k!='payload'};rec.update(status='sending',payload_sha256=digest(item['payload']))
            state['records'][key]=rec
            write_json(directory/'payloads'/f'{key}.json',item['payload']);write_json(path,state)
            try:
                status,body=send(endpoint,token,item['payload'])
                body=json.loads(json.dumps(body,ensure_ascii=False).replace(token,'[REDACTED]'))
                rec.update(http_status=status,response=body)
                if status==200 and valid_receipt(body,item):rec['status']='success'
                elif status==401 or (status==200 and isinstance(body,dict) and type(body.get('code')) is int and body['code']==1):rec['status']='failed'
                else:rec['status']='uncertain'
            except Exception as exc:rec.update(status='uncertain',error=str(exc).replace(token,'[REDACTED]'),error_type=type(exc).__name__)
            write_json(path,state)
            print(json.dumps({'row':item['row'],'status':rec['status'],'http_status':rec.get('http_status')},ensure_ascii=False),flush=True)
            if rec.get('http_status')==401 or rec['status']=='uncertain':break
        counts=Counter(r['status'] for r in state['records'].values())
        result={'total':len(items),'success':counts['success'],'failed':counts['failed'],'uncertain':counts['uncertain']+counts['sending'],'pending':len(items)-len(state['records']),'endpoint':endpoint}
        write_json(directory/'summary.json',result);return result
    finally:
        if not handle.closed:handle.close()
        lock.unlink()

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',type=Path,required=True);ap.add_argument('--kind',choices=['imaging','lab'],required=True)
    ap.add_argument('--base-url',default=os.environ.get('SURVEY_BASE_URL',''));ap.add_argument('--audit-dir',type=Path,required=True)
    ap.add_argument('--commit',action='store_true');args=ap.parse_args()
    try:
        endpoint=endpoint_url(args.base_url,args.kind);items,rejected=prepare(args.input,args.kind)
        write_json(args.audit_dir/'preflight.json',{'endpoint':endpoint,'items':items,'rejected':rejected})
        write_json(args.audit_dir/'rejected.json',rejected)
        if not items:raise ValueError(f'没有可推送记录，异常{len(rejected)}条')
        result=execute(items,endpoint,os.environ.get('SURVEY_OPEN_TOKEN',''),args.audit_dir) if args.commit else {'mode':'dry-run','total':len(items),'rejected':len(rejected),'endpoint':endpoint}
        result['rejected']=len(rejected)
        if args.commit:write_json(args.audit_dir/'summary.json',result)
        print(json.dumps(result,ensure_ascii=False));return 0 if not rejected and (not args.commit or result['success']==result['total']) else 2
    except (ValueError,OSError,KeyError) as exc:print('ERROR: '+str(exc),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
