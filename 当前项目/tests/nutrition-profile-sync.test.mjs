import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
const profile = await import('../src/nutrition-profile.js').catch(() => ({}))
const { buildBatchPayload } = await import('../src/nutrition-batch.js')

test('outward sport choices are only football basketball gymnastics', () => {
  assert.deepEqual(profile.SPORT_OPTIONS, ['足球', '篮球', '体操'])
  assert.equal(profile.profileFromGeneral({ 项目种类: '足球' }).athleteType, 'team')
  assert.equal(profile.profileFromGeneral({ 项目种类: '篮球' }).athleteType, 'team')
  assert.equal(profile.profileFromGeneral({ 项目种类: '体操' }).athleteType, 'strength')
})

test('questionnaire values beat stale report profile and preserve deliberate blanks', () => {
  const result = profile.profileFromGeneral({ 姓名: '甲', 项目种类: '体操', 体重: '50', 训练年限: '' },
    { name: '旧姓名', projectType: '足球', athleteType: 'team', weight: 65, trainingYears: '8年', foodTargetScale: '1.2' })
  assert.equal(result.name, '甲')
  assert.equal(result.projectType, '体操')
  assert.equal(result.athleteType, 'strength')
  assert.equal(result.weight, '50')
  assert.equal(result.trainingYears, '')
  assert.equal(result.foodTargetScale, '1.2')
})

test('report edits round trip into questionnaire without changing unrelated data', () => {
  const general = { 姓名: '甲', 性别: '女性', 项目种类: '足球', 体重: '50', 人工备注: '保留', BMR最低值: 1200 }
  const current = profile.profileFromGeneral(general)
  current.projectType = '篮球'
  current.weight = '52'
  current.trainingYears = '6年'
  profile.syncProfileToGeneral(current, general)
  assert.equal(general['项目种类'], '篮球')
  assert.equal(general['体重'], '52')
  assert.equal(general['训练年限'], '6年')
  assert.equal(general['性别'], '女性')
  assert.equal(general['人工备注'], '保留')
  assert.equal(general['BMR最低值'], 1200)
  assert.equal(profile.profileFromGeneral(general).projectType, '篮球')
})

test('batch profiles use the current questionnaire sport for every person', () => {
  const people = [{ id: '1', general: { 项目种类: '篮球', 体重: '66' } }, { id: '2', general: { 项目种类: '体操' } }]
  const payload = buildBatchPayload(people, 'pdf', { '1': { projectType: '足球', athleteType: 'endurance', weight: '12' } }, {})
  assert.equal(payload.profiles['1'].projectType, '篮球')
  assert.equal(payload.profiles['1'].athleteType, 'team')
  assert.equal(payload.profiles['1'].weight, '66')
  assert.equal(payload.profiles['2'].projectType, '体操')
  assert.equal(payload.profiles['2'].athleteType, 'strength')
})

test('visible nutrition form does not disclose classification or calculation rules', () => {
  const vue = readFileSync(new URL('../src/components/NutritionWorkspace.vue', import.meta.url), 'utf8')
  const template = vue.split('<script setup>')[0]
  for (const text of ['BMR上下限须同时填写', '足球默认6次', '周净消耗除以7', '留空采用项目课表', '力量为主', '团体（有氧+力量）', '有氧为主', '运动员膳食干预参数V2.0', '超过70kg的食物摄入倍率', 'unifiedEvaluationContext', 'unifiedEvaluationWarnings']) {
    assert.ok(!template.includes(text), text)
  }
  assert.match(template, /v-model="reportProfile.projectType"[^>]*>/)
  assert.match(template, /v-model="selected.general\['项目种类'\]"/)
  assert.ok(vue.includes('syncProfileToGeneral'))
  assert.ok(vue.includes('profileFromGeneral'))
})
