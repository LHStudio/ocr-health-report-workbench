import test from 'node:test'
import assert from 'node:assert/strict'
import {evaluationWarnings, finalEvaluation} from '../src/nutrition-presentation.js'

test('pre-export data quality warnings remain visible in browser review', () => {
  const warning='个人目标核查：BMR与宏量供能不一致（脂肪20%）。'
  assert.ok(evaluationWarnings({report_checks:{warnings:[warning]}}).includes(warning))
})

test('personal gram comparisons do not revert to energy-ratio wording', () => {
  assert.equal(finalEvaluation({key:'grains_remainder',evaluation:'不足',evaluation_basis:'personal_target'}), '不足')
})
