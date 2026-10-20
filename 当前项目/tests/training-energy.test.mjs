import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
const source=readFileSync(new URL('../src/components/NutritionWorkspace.vue',import.meta.url),'utf8')
test('profile initialization preserves saved phase and defaults only absent phase/status',()=>{
  const body=source.match(/function trainingPhaseForReport\(general\) \{([\s\S]*?)\n\}/)?.[1]
  assert.ok(body,'actual phase initializer exists')
  const phase=new Function('general',body)
  assert.equal(phase({'训练阶段':'competition'}),'competition')
  assert.equal(phase({'训练阶段':''}),'')
  assert.equal(phase({'当前状态':'比赛期'}),'competition')
  assert.equal(phase({'当前状态':'康复期'}),'')
  assert.equal(phase({}),'training')
  assert.match(source,/trainingPhase: trainingPhaseForReport\(person.general\)/)
})
