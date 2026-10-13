import test from 'node:test'
import assert from 'node:assert/strict'
import { evaluationRows, evaluationWarnings, finalEvaluation } from '../src/nutrition-presentation.js'

test('merge by key, standard wins, no mutation or duplicate vegetables', () => {
  const data = { athlete_evaluation: { rows: [{ key: 'protein', evaluation: '不足' }, { key: 'vegetables', evaluation: 'old' }], warnings: ['原文未明确年龄分界，需业务确认。', '缺少体重'] }, food_standard_evaluation: { rows: [{ key: 'vegetables', evaluation: '' }, { key: 'nuts', evaluation: '适中' }], warnings: ['缺少体重', '60-70kg标准'] } }
  const before = JSON.stringify(data)
  assert.deepEqual(evaluationRows(data).map(r => r.key), ['protein', 'vegetables', 'nuts'])
  assert.equal(evaluationRows(data)[1].evaluation, '')
  assert.deepEqual(evaluationWarnings(data), ['缺少体重', '60-70kg标准'])
  assert.equal(JSON.stringify(data), before)
  assert.deepEqual(evaluationRows(null), [])
})

test('preview uses manual final values including explicit blanks and calcium mapping', () => {
  const review = { proteinEvaluation: '人工结论', standard_nutsEvaluation: '', calciumEvaluation: '过多' }
  assert.equal(finalEvaluation({ key: 'protein', evaluation: '不足' }, review), '人工结论')
  assert.equal(finalEvaluation({ key: 'nuts', evaluation: '不足' }, review), '')
  assert.equal(finalEvaluation({ key: 'calcium', evaluation: '不足' }, review), '过多')
  assert.equal(finalEvaluation({ key: 'fat', evaluation: '适中' }, review), '适中')
})
