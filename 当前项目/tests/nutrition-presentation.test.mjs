import test from 'node:test'
import assert from 'node:assert/strict'
import { evaluationRows, evaluationWarnings, evaluationContext, finalEvaluation, evaluationAlertClass } from '../src/nutrition-presentation.js'
import * as presentation from '../src/nutrition-presentation.js'

test('hide the requested milk conversion and vegetable explanations without changing raw warnings', () => {
  const warnings = ['奶粉、奶酪折算鲜奶等价量（按蛋白质估计）=记录克数', '蔬菜最低400g/天，原有运动分类要求更高时取更高下限。', '缺少体重']
  const data = { food_standard_evaluation: { warnings } }
  assert.deepEqual(evaluationWarnings(data), ['缺少体重'])
  assert.equal(data.food_standard_evaluation.warnings.length, 3)
})

test('hide requested report explanatory copy in preview without hiding real alerts or editing evidence', () => {
  const data = {food_standard_evaluation:{warnings:['代表食物估算（需复核）：虾、鱼']},report_checks:{warnings:[
    '足球训练计划估算：静息代谢与运动消耗；周净消耗÷7；非完整全天总消耗。',
    '篮球训练计划估算：静息代谢与运动消耗。',
    '既有优质蛋白至少一半约束下，示例食谱蛋白质计划点由128.52g/天调整为148.52g/天，仍在个人蛋白质参考范围内；个人需求上下限不变。',
    '实际摄入异常，请核对份量。',
    '体操训练方案尚未提供，未套用足球或篮球MET。',
    '既有优质蛋白至少一半约束下，示例食谱蛋白质计划点由100.00g/天调整为200.00g/天，已超个人蛋白质参考上限，现有食谱约束不相容；请核对约束，不自动倒扣肉类为0。',
  ]}}
  const before = JSON.stringify(data)
  const visible = evaluationWarnings(data).join('\n')
  for (const phrase of ['代表食物估算（需复核）','训练计划估算','周净消耗÷7','非完整全天总消耗','蛋白质计划点由']) assert.equal(visible.includes(phrase), false)
  assert.equal(visible, '') // Diagnostics remain internal; no repeated table notice.
  assert.equal(JSON.stringify(data), before)
})

test('energy preview uses short display note without changing the numeric reference or source note', () => {
  assert.equal(typeof presentation.energyDisplayNote, 'function')
  const energy = {reference_type:'bmr_plus_net',standard:'1732-2256',standard_note:'kcal/天 · 静息代谢＋日均运动净消耗（计划估算，非完整全天总消耗）'}
  const before = JSON.stringify(energy)
  assert.equal(presentation.energyDisplayNote(energy), 'kcal/天 · 静息代谢＋日均运动净消耗')
  assert.equal(JSON.stringify(energy), before)
  assert.equal(presentation.energyDisplayNote({standard_note:'BMR填写区间'}), 'BMR填写区间')
  assert.equal(presentation.energyDisplayNote(null), '请选择活动量')
})

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
  assert.deepEqual(evaluationWarnings(data), [])
  assert.equal(evaluationRows(data)[0].note, '每个鸡蛋按50g')
  assert.equal(JSON.stringify(data), before)
  assert.equal(evaluationContext(null), '')
})

test('snack advice is an alert without coloring normal or partial strings', () => {
  assert.equal(evaluationAlertClass('不足'), 'evaluation-deficit')
  assert.equal(evaluationAlertClass('严重不足'), 'evaluation-deficit')
  assert.equal(evaluationAlertClass('按照运动情况适量补充饮料'), 'evaluation-alert')
  for (const value of ['过多', '建议尽量不吃', ' 建议尽量不吃 ']) assert.equal(evaluationAlertClass(value), 'evaluation-alert')
  for (const value of ['适中', '自定义评价', '建议尽量不吃但尚待核查', null]) assert.equal(evaluationAlertClass(value), '')
})

test('staple ratings describe equivalent-weight share; manual values stay supported', () => {
  assert.equal(finalEvaluation({key:'grains_remainder',evaluation:'过多'}), '过多')
  assert.equal(finalEvaluation({key:'beans_energy',evaluation:'不足'}), '不足')
  assert.equal(finalEvaluation({key:'grains_remainder',evaluation:'过多'},{standard_grains_remainderEvaluation:'人工结论'}), '人工结论')
  assert.equal(evaluationAlertClass('能量占比偏高'), 'evaluation-alert')
  assert.equal(evaluationAlertClass('能量占比适中'), '')
})

 test('quantity-first values stay insufficient, and display projection uses grams', () => {
  const row={key:'beans_energy',actual:5,unit:'%',evaluation:'不足',evaluation_basis:'quantity_first',display:{actual:12.35,unit:'g/天',target:'≥ 15.00 g/天'}}
  assert.equal(finalEvaluation(row),'不足')
  assert.equal(evaluationRows({food_standard_evaluation:{rows:[row]}})[0].unit,'g/天')
  assert.equal(evaluationRows({food_standard_evaluation:{rows:[row]}})[0].actual,12.35)
 })

 test('confirmed snack stays visible without adding output veto copy', () => {
  assert.equal(finalEvaluation({key:'snacks',evaluation:'不建议吃零食'},{standard_snacksEvaluation:'建议吃'}),'不建议吃零食')
  assert.deepEqual(evaluationWarnings({report_status:'needs_review',report_checks:{warnings:[]}}), [])
 })
