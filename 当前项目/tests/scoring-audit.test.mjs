import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import { evaluationAlertClass, evaluationContext, evaluationWarnings } from '../src/nutrition-presentation.js'

test('energy-specific low label stays red while adequate stays neutral', () => {
  assert.equal(evaluationAlertClass('过少'), 'evaluation-alert')
  assert.equal(evaluationAlertClass('适宜'), '')
  assert.equal(evaluationAlertClass('人工认为过少'), '')
})

test('base food reference replaces misleading weight applicability without duplicate warnings', () => {
  const data = {food_standard_evaluation:{warnings:['基础膳食参考标准']}}
  assert.equal(evaluationContext(data), '基础膳食参考标准')
  assert.deepEqual(evaluationWarnings(data), [])
})

function componentFunction(name, context = {}) {
  const source=fs.readFileSync(new URL('../src/components/NutritionWorkspace.vue',import.meta.url),'utf8')
  const start=source.indexOf(`function ${name}(`)
  const end=source.indexOf('\nfunction ',start+1)
  assert.ok(start>=0 && end>start)
  return vm.runInNewContext(source.slice(start,end)+`;${name}`,context)
}

test('energy selector recognizes machine labels without replacing manual legacy values', () => {
  const reportReview={value:{manualEntryFields:{}}}
  const select=componentFunction('evaluationSelection',{reportReview})
  assert.equal(select('适宜','nutrition:energyEvaluation'),'适宜')
  assert.equal(select('过少','nutrition:energyEvaluation'),'过少')
  assert.equal(select('不足','nutrition:energyEvaluation'),'other')
  assert.equal(select('不足','nutrition:calciumEvaluation'),'不足')
  reportReview.value.manualEntryFields['nutrition:energyEvaluation']=true
  assert.equal(select('适宜','nutrition:energyEvaluation'),'other')
})

test('energy interpretation includes a deficit only for low energy and preserves other warnings', () => {
  const interpret=componentFunction('machineInterpretation')
  assert.match(interpret({nutrition:{energy:{evaluation:'过少'}}}),/总能量摄入不足/)
  assert.doesNotMatch(interpret({nutrition:{energy:{evaluation:'适宜'}}}),/总能量摄入不足/)
})
