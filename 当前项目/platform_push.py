"""Explicit UI pushes, private durable receipts, no hooks on OCR completion."""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from collections import Counter
from copy import deepcopy
from pathlib import Path

from fastapi import HTTPException, Request
from openpyxl import Workbook
from scripts import push_clinical_reports as clinical
from scripts import push_nutrition_reports as nutrition


def private_root():
    # Never use the publicly served JOB_ROOT or the Git checkout for secrets.
    return Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.local' / 'share') / 'OCRHealthWorkbench' / 'platform-push'


def load_config():
    path = private_root() / 'config.json'
    settings = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    base = os.environ.get('SURVEY_BASE_URL') or settings.get('base_url', 'https://athlete.f8q8.com/api')
    token = os.environ.get('SURVEY_OPEN_TOKEN') or settings.get('token', '')
    if not isinstance(token, str) or not token.strip() or '\r' in token or '\n' in token:
        raise ValueError('尚未配置平台推送密钥，请在后端配置 SURVEY_OPEN_TOKEN（见 docs/platform-push-ui.md）')
    # Validate all three routes before enabling the UI.
    clinical.endpoint_url(base, 'imaging'); clinical.endpoint_url(base, 'lab'); nutrition.endpoint_url(base)
    return base, token


def validate_snapshot(kind, state, payload):
    if kind not in ('imaging', 'lab', 'nutrition'):
        raise ValueError('未知推送类型')
    if not state or state.get('status') != 'completed':
        raise ValueError('识别任务尚未完成')
    if (kind == 'lab' and state.get('kind') not in (None, 'medical', 'lab')) or (kind != 'lab' and state.get('kind') != kind):
        raise ValueError('任务与推送类型不符')
    key = 'records' if kind == 'imaging' else 'people'
    rows = payload.get(key)
    expected = state.get(key, [])
    if not isinstance(rows, list) or not rows or any(not isinstance(r, dict) for r in rows):
        raise ValueError('请提供当前任务全部核对记录')
    ids = [r.get('id') for r in rows]
    expected_ids = [r.get('id') for r in expected]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids) or sorted(ids) != sorted(expected_ids):
        raise ValueError('必须包含当前任务全部人员，不能使用重复或其他任务的标识')
    if type(payload.get('retry_failed', False)) is not bool:
        raise ValueError('重试开关必须为布尔值')
    if kind == 'lab':
        by_id = {p['id']: p for p in expected}
        for row in rows:
            if row.get('row') != by_id[row['id']].get('row'):
                raise ValueError('化验行标识已变化，请重新核对任务')
    if kind == 'nutrition':
        for name in ('profiles', 'reviews'):
            mapping = payload.get(name, {})
            if not isinstance(mapping, dict) or set(mapping) - set(ids) or any(not isinstance(v, dict) for v in mapping.values()):
                raise ValueError(name + '必须按当前任务人员标识填写对象')
    return deepcopy(payload)


def prepare_snapshot(kind, snapshot, directory):
    """Use existing workbook adapters while leaving the job/export untouched."""
    directory.mkdir(parents=True, exist_ok=True)
    rejected, items = [], []
    if kind in ('imaging', 'lab'):
        key = 'records' if kind == 'imaging' else 'people'
        for index, row in enumerate(snapshot[key]):
            name = row.get('fields', {}).get('姓名', '') if kind == 'imaging' else row['id']
            try:
                wb = Workbook(); ws = wb.active
                if kind == 'imaging':
                    fields = row.get('fields', {})
                    ws.append(clinical.IMAGING_COLUMNS)
                    ws.append([fields.get(k) for k in clinical.IMAGING_COLUMNS])
                else:
                    fields = row.get('review_fields', [])
                    if not isinstance(fields, list) or any(not isinstance(f, dict) for f in fields):
                        raise ValueError('化验核对字段无效')
                    labels = [f.get('header') for f in fields]
                    if len(set(labels)) != len(labels) or set(labels) != set(clinical.LAB_LABELS[1:]):
                        raise ValueError('化验模板字段与平台标准不一致，请使用标准检验结果录入模板')
                    values = {f['header']: f.get('value') for f in fields}
                    name = values.get('姓名') or row['id']
                    ws.append(['平台推送临时快照']); ws.append(clinical.LAB_LABELS)
                    ws.append([index + 1] + [values.get(h) for h in clinical.LAB_LABELS[1:]])
                path = directory / f'{index}.xlsx'
                wb.save(path); wb.close()
                good, bad = clinical.prepare(path, kind)
                for entry in good:
                    if kind == 'imaging':
                        entry['payload'] = {key: entry['payload'].get(key, '') for key in clinical.IMAGING_COLUMNS}
                    items.append(dict(person_id=row['id'], name=entry['name'], date=entry['analysisDate'], payload=entry['payload']))
                for entry in bad:
                    rejected.append(dict(person_id=row['id'], name=entry['name'] or str(name), status='rejected', message=entry['error']))
                if not good and not bad:
                    raise ValueError('没有可推送的识别结果')
            except (ValueError, TypeError, KeyError) as error:
                rejected.append(dict(person_id=row['id'], name=str(name), status='rejected', message=str(error)))
    else:
        from nutrition_report import NutritionReportService
        service = NutritionReportService()
        for index, person in enumerate(snapshot['people']):
            name = (person.get('general') or {}).get('姓名') or person['id']
            try:
                review = snapshot.get('reviews', {}).get(person['id'])
                report_date = clinical.report_date((person.get('general') or {}).get('调查日期'))
                adapted = service.adapt_ocr_person(person, user_overrides=snapshot.get('profiles', {}).get(person['id']),
                    report_date=report_date, auto_evaluation=not bool(review), manual_evaluations=review, include_quality_page=False)
                if not adapted.usable_food_count:
                    raise ValueError('无可换算食物，请先核对营养问卷')
                data = service.build_report_data(adapted.payload)
                path = directory / f'{index}.xlsx'
                service.excel_builder.build(data, path)
                payload = nutrition.read_report(path)
                items.append(dict(person_id=person['id'], name=payload['name'], date=payload['analysisDate'], payload=payload))
            except Exception as error:
                rejected.append(dict(person_id=person['id'], name=str(name), status='rejected', message=str(error)))
    # Refuse ALL colliding rows, not just the second row, before any HTTP request.
    counts = Counter((item['name'], item['date']) for item in items)
    unique = []
    for item in items:
        if counts[(item['name'], item['date'])] > 1:
            rejected.append(dict(person_id=item['person_id'], name=item['name'], date=item['date'], status='rejected',
                                 message='同一姓名同一日期重复，请先核对，未发送'))
        else:
            unique.append(item)
    return unique, rejected


def content_digest(kind, payload):
    """Ignore generated timestamps for dedup only; transmit the full report unchanged."""
    content = deepcopy(payload)
    if kind == 'nutrition':
        content.get('个人信息', {}).pop('营养库查询时间', None)
        content['建议'] = [row for row in content.get('建议', []) if row.get('序号') != '报告生成日期']
    return clinical.digest(content)


class PushManager:
    def __init__(self, root=None, config=load_config):
        self.root = Path(root) if root is not None else private_root()
        self.config = config
        self.active = set()

    def _path(self, run_id):
        if not re.fullmatch(r'[a-f0-9]{32}', run_id): raise ValueError('无效推送编号')
        return self.root / 'runs' / run_id / 'status.json'

    def _index(self, kind, job_id):
        return self.root / 'jobs' / (clinical.digest([kind, job_id]) + '.json')

    def start(self, kind, job_id, state, payload, *, launch=True):
        snapshot = validate_snapshot(kind, state, payload)
        base, _ = self.config()
        endpoint = nutrition.endpoint_url(base) if kind == 'nutrition' else clinical.endpoint_url(base, kind)
        self.root.mkdir(parents=True, exist_ok=True)
        lock = self.root / 'push.lock'
        run_id = uuid.uuid4().hex
        try:
            with lock.open('x', encoding='utf-8') as stream:
                stream.write(run_id); stream.flush(); os.fsync(stream.fileno())
        except FileExistsError:
            raise ValueError('另一个推送正在运行，或上次异常中断尚待核对；请查看推送状态，不要重复上传') from None
        try:
            run = dict(id=run_id, kind=kind, job_id=job_id, phase='queued', endpoint=endpoint, records=[], message='已排队，正在准备当前核对数据')
            clinical.write_json(self._path(run_id).parent / 'snapshot.json', snapshot)
            clinical.write_json(self._path(run_id), run)
            clinical.write_json(self._index(kind, job_id), {'id': run_id})
            self.active.add(run_id)
            if launch:
                threading.Thread(target=self.work, args=(run_id,), daemon=True, name='platform-push').start()
            return self.public(run)
        except Exception:
            self.active.discard(run_id); lock.unlink(missing_ok=True)
            raise

    def public(self, run):
        safe = {key: deepcopy(run[key]) for key in ('id', 'kind', 'phase', 'message', 'records')}
        safe['counts'] = {key: 0 for key in ('success', 'skipped', 'failed', 'uncertain', 'rejected', 'pending', 'sending')}
        safe['counts'].update(Counter(r['status'] for r in run['records']))
        safe['total'] = len(run['records'])
        return safe

    def status(self, kind, job_id):
        index = self._index(kind, job_id)
        if not index.exists(): return None
        run = json.loads(self._path(json.loads(index.read_text(encoding='utf-8'))['id']).read_text(encoding='utf-8'))
        if run['phase'] in ('queued', 'preparing', 'running') and run['id'] not in self.active:
            run['phase'] = 'interrupted'
            run['message'] = '上次服务中断，请核对平台记录和私有回执；不会自动重发'
            for record in run['records']:
                if record['status'] == 'sending': record['status'] = 'uncertain'
        return self.public(run)

    def work(self, run_id, *, send=None):
        path = self._path(run_id)
        run = json.loads(path.read_text(encoding='utf-8'))
        token = ''
        try:
            base, token = self.config()
            kind = run['kind']
            endpoint = nutrition.endpoint_url(base) if kind == 'nutrition' else clinical.endpoint_url(base, kind)
            if endpoint != run['endpoint']: raise ValueError('平台配置在排队后变化，未发送')
            snapshot = json.loads((path.parent / 'snapshot.json').read_text(encoding='utf-8'))
            run.update(phase='preparing', message='正在校验并生成推送快照'); clinical.write_json(path, run)
            items, rejected = prepare_snapshot(kind, snapshot, path.parent / 'prepared')
            run['records'] = rejected + [{k: v for k, v in item.items() if k != 'payload'} | {'status': 'pending', 'message': ''} for item in items]
            run.update(phase='running', message='正在上传；请勿重复点击'); clinical.write_json(path, run)
            registry_path = self.root / 'registry.json'
            registry = json.loads(registry_path.read_text(encoding='utf-8')) if registry_path.exists() else {}
            sender = send or (nutrition.post if kind == 'nutrition' else clinical.post)
            for item, record in zip(items, run['records'][len(rejected):]):
                key = clinical.digest([endpoint, item['name'], item['date']])
                payload_hash = clinical.digest(item['payload'])
                fingerprint = content_digest(kind, item['payload'])
                previous = registry.get(key)
                if previous and previous['status'] in ('uncertain', 'sending'):
                    record.update(status='uncertain', message='此前同一人员/日期回执不明确，须人工核对，未重发')
                elif previous and previous.get('content_sha256', previous['payload_sha256']) == fingerprint and previous['status'] == 'success':
                    record.update(status='skipped', message='相同数据此前已成功上传，本次未重复发送')
                elif previous and previous.get('content_sha256', previous['payload_sha256']) == fingerprint and previous['status'] == 'failed' and not snapshot.get('retry_failed'):
                    record.update(status='failed', message=previous.get('message') or '上次明确失败；修正后可点击重试明确失败项')
                else:
                    record.update(status='sending', message='正在等待平台回执')
                    registry[key] = dict(status='sending', payload_sha256=payload_hash, content_sha256=fingerprint, run_id=run_id)
                    clinical.write_json(path.parent / f'payload-{key}.json', item['payload'])
                    clinical.write_json(registry_path, registry); clinical.write_json(path, run)
                    http_status = None
                    try:
                        http_status, body = sender(endpoint, token, item['payload'])
                        body = json.loads(json.dumps(body, ensure_ascii=False).replace(token, '[REDACTED]'))
                        valid = nutrition.valid_receipt(body, item['payload']) if kind == 'nutrition' else clinical.valid_receipt(body, {'name': item['name'], 'analysisDate': item['date']})
                        if http_status == 200 and valid:
                            record.update(status='success', message='平台已确认接收')
                        elif http_status == 401 or (http_status == 200 and isinstance(body, dict) and type(body.get('code')) is int and body['code'] == 1):
                            record.update(status='failed', message=str(body.get('message') or '平台拒绝，请核对配置/人员资料') if isinstance(body, dict) else '平台拒绝授权')
                        else:
                            record.update(status='uncertain', message='回执不符合接口契约，须人工核对平台，未自动重试')
                        registry[key].update(http_status=http_status, response=body)
                    except Exception as error:
                        record.update(status='uncertain', message='网络或回执异常，须人工核对平台，未自动重试')
                        registry[key]['error'] = str(error).replace(token, '[REDACTED]')
                    registry[key].update(status=record['status'], message=record['message'])
                    clinical.write_json(registry_path, registry)
                    clinical.write_json(path, run)
                    if record['status'] == 'uncertain' or http_status == 401: break
                clinical.write_json(path, run)
            run.update(phase='completed', message='本次处理结束；请查看逐人结果，待核对项未上传')
        except Exception as error:
            run.update(phase='error', message=str(error).replace(token, '[REDACTED]') if token else str(error))
        finally:
            # Redact any exception/report diagnostic that might have echoed the credential.
            if token: run = json.loads(json.dumps(run, ensure_ascii=False).replace(token, '[REDACTED]'))
            clinical.write_json(path, run)
            self.active.discard(run_id)
            lock = self.root / 'push.lock'
            if lock.exists() and lock.read_text(encoding='utf-8') == run_id: lock.unlink()


def register_platform_push(app, get_job):
    manager = PushManager()
    app.state.platform_push = manager

    def guard(request):
        origin = request.headers.get('origin')
        if origin and origin not in ('http://127.0.0.1:5173', 'http://localhost:5173', 'http://127.0.0.1:8000', 'http://localhost:8000'):
            raise HTTPException(403, '不允许跨站调用平台推送')

    @app.get('/platform-push/config')
    def config_status():
        try:
            base, _ = manager.config()
            return {'configured': True, 'platform': base}
        except (ValueError, OSError):
            return {'configured': False, 'message': '后端尚未配置平台密钥，请参阅 docs/platform-push-ui.md'}

    @app.post('/platform-push/{kind}/{job_id}', status_code=202)
    def start(kind: str, job_id: str, payload: dict, request: Request):
        guard(request)
        try:
            return manager.start(kind, job_id, get_job(job_id), payload)
        except (ValueError, OSError) as error:
            # No token/config file contents in error responses.
            raise HTTPException(409, str(error) if isinstance(error, ValueError) else '私有推送目录不可用') from None

    @app.get('/platform-push/{kind}/{job_id}')
    def status(kind: str, job_id: str):
        return manager.status(kind, job_id)
