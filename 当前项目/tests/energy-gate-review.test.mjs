import test from 'node:test'
import assert from 'node:assert/strict'
import * as presentation from '../src/nutrition-presentation.js'
import fs from 'node:fs'
import vm from 'node:vm'
import {buildBatchPayload} from '../src/nutrition-batch.js'

const preview = {category_result:{谷类:{value:100,evaluation:'能量占比偏高'},薯类:{value:20,evaluation:'能量占比偏低'},奶类:{value:100,evaluation:'不足'},饮料:{value:0,evaluation:'-'}},food_standard_evaluation:{rows:[{key:'grains_remainder',label:'谷类'},{key:'tubers_energy',label:'薯类'},{key:'milk',label:'奶类鲜奶等价量'}]}}
test('duplicate review categories are suppressed by stable identity, not display label',()=>{
  assert.deepEqual(presentation.reviewCategoryRows(preview).map(r=>r.key),['饮料'])
  assert.equal(presentation.reviewCategoryRows({category_result:preview.category_result}).length,4)
})
test('a historical category-only manual value including blank migrates to retained control',()=>{
  for(const value of ['人工谷类','']){
    const review={machineSeeded:true,categoryEvaluations:{谷类:value},standard_grains_remainderEvaluation:'旧机器',lastMachine:{categoryEvaluations:{谷类:'旧机器'},standard_grains_remainderEvaluation:'旧机器'}}
    const snapshot=structuredClone(review)
    const merged=presentation.coalesceReviewAliases(review,preview)
    assert.equal(merged.standard_grains_remainderEvaluation,value)
    assert.deepEqual(review,snapshot)
  }
})
test('conflicting historical edits retain existing standard precedence and remain visible for review',()=>{
  const result=presentation.coalesceReviewAliases({machineSeeded:true,categoryEvaluations:{谷类:'分类人工'},standard_grains_remainderEvaluation:'专项人工',lastMachine:{categoryEvaluations:{谷类:'机器'},standard_grains_remainderEvaluation:'机器'}},preview)
  assert.equal(result.standard_grains_remainderEvaluation,'专项人工')
  assert.equal(result.categoryEvaluations.谷类,'分类人工')
  assert.deepEqual(result.aliasConflicts,['谷类'])
})
test('energy priority labels are never retranslated to ratio labels in the preview',()=>{
  assert.equal(presentation.finalEvaluation({key:'grains_remainder',evaluation:'过多',evaluation_basis:'energy_excess'}),'过多')
  assert.equal(presentation.finalEvaluation({key:'grains_remainder',evaluation:'不足',evaluation_basis:'ratio'}),'不足')
})

function componentFunction(name, context) {
  const source=fs.readFileSync(new URL('../src/components/NutritionWorkspace.vue',import.meta.url),'utf8')
  const start=source.indexOf(`function ${name}(`),end=source.indexOf('\nfunction ',start+1)
  assert.ok(start>=0 && end>start)
  return vm.runInNewContext(source.slice(start,end)+`;${name}`,context)
}
test('actual Vue reseeding retains migrated blank/custom edits and exports the unique standard key',()=>{
  for(const value of ['', '已复核谷类']){
    const reportReview={value:{machineSeeded:true,categoryEvaluations:{谷类:value},standard_grains_remainderEvaluation:'旧机器',manualEntryFields:{},lastMachine:{categoryEvaluations:{谷类:'旧机器'},standard_grains_remainderEvaluation:'旧机器'}}}
    const data={...preview,nutrition:{energy:{evaluation:'适宜'},calcium:{evaluation:'适中'}},food_standard_evaluation:{rows:preview.food_standard_evaluation.rows.map(r=>({...r,machine_evaluation:'新机器'}))}}
    const seed=componentFunction('seedReportReviewFromPreview',{reportReview,nutritionPreview:{value:data},selected:{value:{id:'synthetic'}},reportReviews:{value:{}},coalesceReviewAliases:presentation.coalesceReviewAliases,machineEvaluationText:v=>String(v??'').trim(),machineInterpretation:()=>'',copyReportReview:structuredClone})
    seed();seed()
    assert.equal(reportReview.value.standard_grains_remainderEvaluation,value)
    const payload=buildBatchPayload([{id:'synthetic'}],'pdf',{}, {synthetic:reportReview.value})
    assert.equal(payload.reviews.synthetic.standardEvaluations.grains_remainder,value)
  }
})
test('uniform low-energy food rating is a normal selector value, not an accidental manual entry',()=>{
  const select=componentFunction('evaluationSelection',{reportReview:{value:{manualEntryFields:{}}}})
  assert.equal(select('过少','nutrition:standard_grains_remainderEvaluation'),'过少')
  assert.equal(select('不足','nutrition:calciumEvaluation'),'不足')
})
