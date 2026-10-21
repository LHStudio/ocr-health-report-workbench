import test from 'node:test'
import assert from 'node:assert/strict'
import {evaluationWarnings, finalEvaluation} from '../src/nutrition-presentation.js'

test('internal data quality warnings are not repeated below evaluation table', () => {
  const warning='个人目标核查：BMR与宏量供能不一致（脂肪20%）。'
  const data={report_checks:{warnings:[warning]}}
  assert.deepEqual(evaluationWarnings(data),[])
  assert.deepEqual(data.report_checks.warnings,[warning])
})

test('personal gram comparisons do not revert to energy-ratio wording', () => {
  assert.equal(finalEvaluation({key:'grains_remainder',evaluation:'不足',evaluation_basis:'personal_target'}), '不足')
})


test('obsolete conversion-menu fat gaps do not reappear from saved reports', () => {
  const hidden = '示例食谱脂肪46.81g/天，尚有脂肪缺口';
  const actual = '实际脂肪摄入不足，请核对';
  assert.deepEqual(evaluationWarnings({report_checks:{warnings:[hidden,actual]}}), []);
});
