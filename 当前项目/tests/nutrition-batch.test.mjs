import assert from 'node:assert/strict'
import { test } from 'node:test'
const module = await import('../src/nutrition-batch.js').catch(() => ({}))

test('batch includes entire task; reviews only contain human changes, not stale machine text', () => {
  assert.equal(typeof module.buildBatchPayload, 'function')
  const people = Array.from({ length: 23 }, (_, i) => ({ id: `p/${i}` }))
  const result = module.buildBatchPayload(people, 'both', { 'p/0': { weight: 65 } }, {
    'p/0': { machineSeeded: true, categoryEvaluations: { 坚果: '偏少' },
      standard_nutsEvaluation: '人工修改', overallSuggestions: '旧机器建议',
      lastMachine: { categoryEvaluations: { 坚果: '偏少' }, standard_nutsEvaluation: '不足', overallSuggestions: '旧机器建议' } },
    'p/1': { machineSeeded: false },
  })
  assert.equal(result.people.length, 23)
  assert.deepEqual(result.reviews, { 'p/0': { standardEvaluations: { nuts: '人工修改' } } })
  assert.equal(result.profiles['p/0'].weight, 65)
  assert.equal(result.format, 'both')
})

test('explicit blank manual evaluation is retained, missing machine fields are not invented', () => {
  assert.equal(typeof module.buildBatchPayload, 'function')
  const result = module.buildBatchPayload([{ id: 'p' }], 'pdf', {}, { p: {
    machineSeeded: true, categoryEvaluations: { 蛋类: '' }, proteinEvaluation: '',
    lastMachine: { categoryEvaluations: { 蛋类: '达标' }, proteinEvaluation: '不足' },
  } })
  assert.deepEqual(result.reviews.p, { categoryEvaluations: { 蛋类: '' }, proteinEvaluation: '' })
})
