import test from 'node:test'
import assert from 'node:assert/strict'
import { evaluationRows, evaluationWarnings, evaluationContext, finalEvaluation, evaluationAlertClass } from '../src/nutrition-presentation.js'

test('merge by key, standard wins, no mutation or duplicate vegetables', () => {
  const data = { athlete_evaluation: { rows: [{ key: 'protein', evaluation: '不足' }, { key: 'vegetables', evaluation: 'old' }], warnings: ['原文未明确年龄分界，需业务确认。', '缺少体重'] }, food_standard_evaluation: { rows: [{ key: 'vegetables', evaluation: '' }, { key: 'nuts', evaluation: '适中' }], warnings: ['缺少体重'] } }
  const before = JSON.stringify(data)
  assert.deepEqual(evaluationRows(data).map(r => r.key), ['protein', 'vegetables', 'nuts'])
  assert.equal(evaluationRows(data)[1].evaluation, '')
  assert.deepEqual(evaluationWarnings(data), ['缺少体重'])
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

test('remove requested wording and move scope into one context line without changing source', () => {
  const data = { athlete_evaluation: { athlete_label: '力量为主', rows: [], warnings: ['仅训练期；参数来自用户提供文档，需营养专业人员审核。'] }, food_standard_evaluation: { rows: [{ key: 'eggs', note: '每个鸡蛋按50g；显式克数不二次折算' }], warnings: ['60-70kg标准', '主食能量=谷类+豆类+薯类；豆类至少5%、薯类至少15%，因此谷类占比上限为80%，不是必须达到80%。', '蔬菜最低400g/天，原有运动分类要求更高时取更高下限；采用最低量规则，不以先前500g封顶。'] } }
  const before = JSON.stringify(data)
  assert.equal(evaluationContext(data), '力量为主 · 仅训练期 · 60-70kg标准')
  assert.deepEqual(evaluationWarnings(data), ['主食能量=谷类+豆类+薯类；豆类至少5%、薯类至少15%。', '蔬菜最低400g/天，原有运动分类要求更高时取更高下限。'])
  assert.equal(evaluationRows(data)[0].note, '每个鸡蛋按50g')
  assert.equal(JSON.stringify(data), before)
  assert.equal(evaluationContext(null), '')
})

test('snack advice is an alert without coloring normal or partial strings', () => {
  for (const value of ['不足', '过多', '建议尽量不吃', ' 建议尽量不吃 ']) assert.equal(evaluationAlertClass(value), 'evaluation-alert')
  for (const value of ['适中', '自定义评价', '建议尽量不吃但尚待核查', null]) assert.equal(evaluationAlertClass(value), '')
})

test('staple ratings describe energy share, not food grams; manual values stay supported', () => {
  assert.equal(finalEvaluation({key:'grains_remainder',evaluation:'过多'}), '能量占比偏高')
  assert.equal(finalEvaluation({key:'beans_energy',evaluation:'不足'}), '能量占比偏低')
  assert.equal(finalEvaluation({key:'grains_remainder',evaluation:'过多'},{standard_grains_remainderEvaluation:'人工结论'}), '人工结论')
  assert.equal(evaluationAlertClass('能量占比偏高'), 'evaluation-alert')
  assert.equal(evaluationAlertClass('能量占比适中'), '')
})
