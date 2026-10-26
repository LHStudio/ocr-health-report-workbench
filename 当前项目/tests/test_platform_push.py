import importlib.util
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def image_record(identifier='a', name='测试运动员', date='2026.10.1'):
    return dict(id=identifier, fields={'病人ID': '0007', '姓名': name, '性别': '女', '年龄': '20',
                '超声所见': '合成测试所见', '超声诊断': '合成测试诊断', '检查时间': date})

def receipt(endpoint, token, payload):
    return 200, {'code': 0, 'data': {'name': payload.get('姓名', payload.get('name')),
        'analysisDate': payload.get('检查时间', payload.get('报告日期', payload.get('analysisDate'))),
        'athleteId': 'synthetic-athlete', 'analysisId': 'synthetic-analysis', 'created': True}}

class PushTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('platform_push'), 'missing platform push feature')
        import platform_push
        self.p = platform_push
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.record = image_record()
        self.state = {'kind': 'imaging', 'status': 'completed', 'records': [deepcopy(self.record)]}
        self.manager = self.p.PushManager(self.root, config=lambda: ('https://example.test/api', 'synthetic-token'))

    def run_push(self, records=None, retry=False, send=receipt):
        result = self.manager.start('imaging', 'job1', self.state,
            {'records': records or [self.record], 'retry_failed': retry}, launch=False)
        self.manager.work(result['id'], send=send)
        return self.manager.status('imaging', 'job1')

    def test_six_fields_date_normalization_and_no_source_mutation(self):
        original = deepcopy(self.state)
        calls = []
        def send(endpoint, token, payload):
            calls.append(payload); return receipt(endpoint, token, payload)
        result = self.run_push(send=send)
        self.assertEqual(result['counts']['success'], 1)
        self.assertEqual(set(calls[0]), set(self.p.clinical.IMAGING_COLUMNS))
        self.assertEqual(calls[0]['检查时间'], '2026-10-01')
        self.assertEqual(self.state, original)
        self.assertNotIn('synthetic-token', json.dumps(result))

    def test_same_payload_deduplicated_even_after_restart(self):
        self.run_push()
        self.manager = self.p.PushManager(self.root, config=lambda: ('https://example.test/api', 'synthetic-token'))
        def never(*args): raise AssertionError('duplicate send')
        self.assertEqual(self.run_push(send=never)['counts']['skipped'], 1)

    def test_edit_only_resends_changed_record(self):
        self.run_push()
        updated = deepcopy(self.record); updated['fields']['超声诊断'] = '人工修改'
        self.assertEqual(self.run_push([updated])['counts']['success'], 1)

    def test_uncertain_blocks_even_changed_payload(self):
        def timeout(*args): raise TimeoutError('synthetic-token timeout')
        self.assertEqual(self.run_push(send=timeout)['counts']['uncertain'], 1)
        updated = deepcopy(self.record); updated['fields']['超声诊断'] = '修改后'
        def never(*args): raise AssertionError('unsafe resend')
        result = self.run_push([updated], retry=True, send=never)
        self.assertEqual(result['counts']['uncertain'], 1)
        self.assertNotIn('synthetic-token', json.dumps(result))

    def test_failed_requires_explicit_retry(self):
        failed = lambda *args: (200, {'code': 1, 'message': '未匹配到运动员'})
        self.assertEqual(self.run_push(send=failed)['counts']['failed'], 1)
        self.assertEqual(self.run_push()['counts']['failed'], 1)
        self.assertEqual(self.run_push(retry=True)['counts']['success'], 1)

    def test_missing_date_is_rejected_never_defaulted(self):
        self.record['fields']['检查时间'] = ''
        result = self.run_push()
        self.assertEqual(result['counts']['rejected'], 1)
        self.assertEqual(result['counts']['success'], 0)

    def test_partial_rejection_keeps_good_rows(self):
        second = image_record('b', '缺日期测试', '')
        self.state['records'].append(second)
        result = self.run_push([self.record, second])
        self.assertEqual(result['counts']['success'], 1)
        self.assertEqual(result['counts']['rejected'], 1)

    def test_duplicate_name_date_sends_nothing(self):
        second = image_record('b')
        self.state['records'].append(second)
        result = self.run_push([self.record, second])
        self.assertEqual(result['counts']['success'], 0)
        self.assertEqual(result['counts']['rejected'], 2)

    def test_cross_job_and_incomplete_scope_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.start('imaging', 'job1', self.state, {'records': [image_record('other')]}, launch=False)
        with self.assertRaises(ValueError):
            self.manager.start('lab', 'job1', self.state, {'people': []}, launch=False)

    def test_concurrent_and_crash_lock_fail_closed(self):
        run = self.manager.start('imaging', 'job1', self.state, {'records': [self.record]}, launch=False)
        with self.assertRaises(ValueError):
            self.manager.start('imaging', 'job1', self.state, {'records': [self.record]}, launch=False)
        self.manager.work(run['id'], send=receipt)

    def test_lab_only_current_review_rows_leading_zero_preserved(self):
        values = {'姓名': '合成化验', '报告日期': '2026/10/1', '病历号': '00007', '白细胞WBC（×10^9/L）': '4.0'}
        person = dict(id='p1', row=19, review_fields=[{'header': h, 'value': values.get(h, '')}
                      for h in self.p.clinical.LAB_LABELS if h != '序号'])
        state = dict(status='completed', people=[person])
        result = self.manager.start('lab', 'job2', state, {'people': [person]}, launch=False)
        calls = []
        def send(endpoint, token, payload): calls.append(payload); return receipt(endpoint, token, payload)
        self.manager.work(result['id'], send=send)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['病历号'], '00007')
        self.assertEqual(calls[0]['WBC'], '4.0')
        self.assertEqual(calls[0]['报告日期'], '2026-10-01')

    def test_ui_three_explicit_buttons_not_ocr_hooks(self):
        for path, kind in [('src/App.vue','lab'), ('src/components/ImagingWorkspace.vue','imaging'),
                           ('src/components/NutritionWorkspace.vue','nutrition')]:
            source = (ROOT / path).read_text(encoding='utf-8')
            self.assertIn(f'kind="{kind}"', source)
            self.assertIn('PlatformPush', source)
        component = (ROOT / 'src/components/PlatformPush.vue').read_text(encoding='utf-8')
        self.assertIn('一键上传到平台', component)
        self.assertNotIn('X-Open-Token', component)
        self.assertIn('onBeforeUnmount', component)

    def test_mismatched_receipt_is_uncertain_and_stops_batch(self):
        second = image_record('b', '合成第二人')
        self.state['records'].append(second)
        def wrong(endpoint, token, payload):
            status, body = receipt(endpoint, token, payload)
            body['data']['name'] = '错误姓名'; return status, body
        result = self.run_push([self.record, second], send=wrong)
        self.assertEqual(result['counts']['uncertain'], 1)
        self.assertEqual(result['counts']['pending'], 1)

    def test_nutrition_real_report_preserves_manual_values_and_rejects_empty_food(self):
        from nutrition_report import NutritionReportService
        people = [dict(id='n1', general={'姓名': '合成营养', '体重': 65, '调查日期': '2026.10.1'},
            food_rows=[{'食物名称': '坚果', '平均每次食用量': '10g', '次数': '1', '频率周期(请核对)': '每天'}]),
            dict(id='n2', general={'姓名': '无食物测试'}, food_rows=[])]
        state = dict(kind='nutrition', status='completed', people=people)
        snapshot = {'people': people, 'profiles': {'n1': {'name': '核对后营养姓名'}},
                    'reviews': {'n1': {'standardEvaluations': {'nuts': '人工确认评价'}}}}
        before = deepcopy(snapshot)
        run = self.manager.start('nutrition', 'njob', state, snapshot, launch=False)
        calls = []
        def send(endpoint, token, payload): calls.append(payload); return receipt(endpoint, token, payload)
        with patch('nutrition_report.NutritionReportService', side_effect=lambda: NutritionReportService(prefer_cloud=False)):
            self.manager.work(run['id'], send=send)
        result = self.manager.status('nutrition', 'njob')
        self.assertEqual(result['counts']['success'], 1, result)
        self.assertEqual(result['counts']['rejected'], 1, result)
        self.assertEqual(calls[0]['name'], '核对后营养姓名')
        self.assertIn('人工确认评价', json.dumps(calls[0], ensure_ascii=False))
        self.assertEqual(snapshot, before)

    def test_imaging_empty_optional_fields_still_six_keys(self):
        for key in ('性别', '年龄', '超声所见'): self.record['fields'][key] = ''
        calls = []
        def send(endpoint, token, payload): calls.append(payload); return receipt(endpoint, token, payload)
        self.assertEqual(self.run_push(send=send)['counts']['success'], 1)
        self.assertEqual(set(calls[0]), set(self.p.clinical.IMAGING_COLUMNS))
        self.assertEqual(calls[0]['年龄'], '')

    def test_nutrition_missing_date_is_not_today(self):
        from nutrition_report import NutritionReportService
        person = dict(id='n1', general={'姓名': '合成无日期'}, food_rows=[{'食物名称': '坚果',
            '平均每次食用量': '10g', '次数': '1', '频率周期(请核对)': '每天'}])
        with patch('nutrition_report.NutritionReportService', side_effect=lambda: NutritionReportService(prefer_cloud=False)):
            items, rejected = self.p.prepare_snapshot('nutrition', {'people': [person]}, self.root / 'prepared')
        self.assertEqual(items, [])
        self.assertEqual(len(rejected), 1)
        self.assertIn('日期', rejected[0]['message'])

    def test_nutrition_generation_timestamps_do_not_defeat_dedup(self):
        person = {'id': 'n1'}
        state = dict(kind='nutrition', status='completed', people=[person])
        payload = {'name': '合成营养', 'analysisDate': '2026-10-01',
                   '个人信息': {'姓名': '合成营养', '日期': '2026-10-01', '营养库查询时间': '2026-10-26T01:00:00'},
                   '建议': [{'序号': 1, '建议内容': '人工建议'}, {'序号': '报告生成日期', '建议内容': '2026-10-26 01:00:00'}]}
        calls = []
        def send(endpoint, token, body): calls.append(body); return receipt(endpoint, token, body)
        for clock in ('01:00:00', '01:01:00'):
            payload['个人信息']['营养库查询时间'] = '2026-10-26T' + clock
            payload['建议'][1]['建议内容'] = '2026-10-26 ' + clock
            item = dict(person_id='n1', name=payload['name'], date=payload['analysisDate'], payload=payload)
            run = self.manager.start('nutrition', 'njob', state, {'people': [person]}, launch=False)
            with patch.object(self.p, 'prepare_snapshot', return_value=([deepcopy(item)], [])):
                self.manager.work(run['id'], send=send)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.manager.status('nutrition', 'njob')['counts']['skipped'], 1)
        self.assertEqual(calls[0]['建议'][1]['建议内容'], '2026-10-26 01:00:00')

    def test_api_config_no_secret_and_origin_guard(self):
        from fastapi import FastAPI
        import socket
        import threading
        import time
        import requests
        import uvicorn
        app = FastAPI()
        self.p.register_platform_push(app, lambda job: self.state if job == 'job1' else None)
        app.state.platform_push.root = self.root
        app.state.platform_push.config = self.manager.config
        sock = socket.socket(); sock.bind(('127.0.0.1', 0))
        base = f'http://127.0.0.1:{sock.getsockname()[1]}'
        server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True); thread.start()
        for _ in range(100):
            if server.started: break
            time.sleep(.03)
        class Client:
            def get(self, path): return requests.get(base + path, timeout=5)
            def post(self, path, **kw): return requests.post(base + path, timeout=5, **kw)
        client = Client()
        try:
            response = client.get('/platform-push/config')
            self.assertTrue(response.json()['configured'])
            self.assertNotIn('synthetic-token', response.text)
            response = client.post('/platform-push/imaging/job1', json={'records': [self.record]}, headers={'Origin': 'https://evil.example'})
            self.assertEqual(response.status_code, 403)
            response = client.post('/platform-push/imaging/missing', json={'records': [self.record]})
            self.assertEqual(response.status_code, 409)
            with patch.object(self.p.clinical, 'post', side_effect=receipt):
                response = client.post('/platform-push/imaging/job1', json={'records': [self.record]})
                self.assertEqual(response.status_code, 202)
                for _ in range(100):
                    result = client.get('/platform-push/imaging/job1').json()
                    if result['phase'] not in ('queued', 'preparing', 'running'): break
                    time.sleep(.03)
                self.assertEqual(result['counts']['success'], 1)
        finally:
            server.should_exit = True; thread.join(5); sock.close()

if __name__ == '__main__': unittest.main()
