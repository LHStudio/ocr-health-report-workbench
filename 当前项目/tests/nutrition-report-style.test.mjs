import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { computed, ref } from 'vue'
import { buildBatchPayload } from '../src/nutrition-batch.js'
import * as presentation from '../src/nutrition-presentation.js'

const source = await readFile(new URL('../src/components/NutritionWorkspace.vue', import.meta.url), 'utf8')
const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')

// Exercise the component's real settings and export functions. Only network,
// downloads and unrelated preview lifecycle hooks are isolated from these tests.
function workspace(saved = {}) {
  const stored = new Map(Object.entries(saved))
  const requests = []
  const dependencies = {
    computed, ref, watch: () => {}, onMounted: () => {},
    localStorage: { getItem: key => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, String(value)) },
    storedOcrApiUrl: () => stored.get('medical-ocr-api-url') || '',
    buildBatchPayload, ...presentation,
    fetch: async (url, options) => {
      requests.push({ url, body: JSON.parse(options.body) })
      return { ok: true, blob: async () => new Blob(), headers: { get: () => null } }
    },
    URL: { createObjectURL: () => 'blob:synthetic-test', revokeObjectURL: () => {} },
    document: { body: { appendChild: () => {} }, createElement: () => ({ click() {}, remove() {} }) },
    window: { setTimeout: () => {} },
  }
  const state = new Function(...Object.keys(dependencies), `${script}\nreturn {
    reportStyle: typeof reportStyle === 'undefined' ? undefined : reportStyle,
    includeQualityPage, nutritionSettingsOpen, openNutritionSettings, closeNutritionSettings,
    saveNutritionSettings, generateReport, generateAllReports, people, selectedId, jobId,
    batchFormat, reportProfile, reportReview, reportErrorMessage, batchError,
  }`)(...Object.values(dependencies))
  state.people.value = [{ id: 'synthetic-01', general: { 姓名: '合成样例', 调查日期: '2026-10-15' }, food_rows: [], ocr_files: [] }]
  state.selectedId.value = 'synthetic-01'
  state.jobId.value = 'synthetic-job'
  return { ...state, stored, requests }
}

test('fourth settings section offers clearly labelled modern and legacy reports', () => {
  assert.match(source, /<span>4<\/span>[\s\S]*?<h3>报告样式<\/h3>/)
  assert.match(source, /aria-label="营养 PDF 报告样式"/)
  assert.match(source, /<option value="modern">新版报告<\/option>/)
  assert.match(source, /<option value="legacy">原版报告<\/option>/)
})

test('new browser defaults to modern; valid stored choices persist and invalid values fall back', () => {
  assert.equal(workspace().reportStyle?.value, 'modern')
  assert.equal(workspace({ 'nutrition-report-style': 'legacy' }).reportStyle?.value, 'legacy')
  assert.equal(workspace({ 'nutrition-report-style': 'modern' }).reportStyle?.value, 'modern')
  assert.equal(workspace({ 'nutrition-report-style': 'unsupported' }).reportStyle?.value, 'modern')
})

test('saving persists style; cancel and close restore saved style and quality-page option', () => {
  const state = workspace()
  assert.ok(state.reportStyle, 'report style state exists')
  state.openNutritionSettings()
  state.reportStyle.value = 'legacy'
  state.includeQualityPage.value = true
  state.saveNutritionSettings()
  assert.equal(state.nutritionSettingsOpen.value, false)
  assert.equal(state.stored.get('nutrition-report-style'), 'legacy')
  assert.equal(state.stored.get('nutrition-include-quality-page'), 'true')
  state.openNutritionSettings()
  state.reportStyle.value = 'modern'
  state.includeQualityPage.value = false
  state.closeNutritionSettings()
  assert.equal(state.reportStyle.value, 'legacy')
  assert.equal(state.includeQualityPage.value, true)
  assert.equal(state.stored.get('nutrition-report-style'), 'legacy')
  assert.equal(workspace(Object.fromEntries(state.stored)).reportStyle.value, 'legacy')
})

test('single PDF and PDF-inclusive batch exports use the selected style without changing manual values', async () => {
  for (const style of ['modern', 'legacy']) {
    const state = workspace({ 'nutrition-report-style': style })
    state.reportProfile.value = { name: '合成样例', weight: 70, height: 175, trainingPhase: 'training' }
    state.reportReview.value = { machineSeeded: true, categoryEvaluations: {}, proteinEvaluation: '人工结论', lastMachine: { categoryEvaluations: {}, proteinEvaluation: '不足' } }
    await state.generateReport('pdf')
    assert.equal(state.reportErrorMessage.value, '')
    assert.equal(state.requests[0].body.report_style, style)
    assert.equal(state.requests[0].body.manual_evaluations.proteinEvaluation, '人工结论')
    assert.equal(state.requests[0].body.user_overrides.weight, 70)
    for (const format of ['pdf', 'both']) {
      state.batchFormat.value = format
      await state.generateAllReports()
      assert.equal(state.batchError.value, '')
      const request = state.requests.at(-1)
      assert.equal(request.body.report_style, style)
      assert.equal(request.body.format, format)
      assert.equal(request.body.reviews['synthetic-01'].proteinEvaluation, '人工结论')
      assert.equal(request.body.profiles['synthetic-01'].weight, 70)
    }
  }
})

test('Excel-only single and batch payloads are identical across PDF style choices', async () => {
  const requestsByStyle = []
  for (const style of ['modern', 'legacy']) {
    const state = workspace({ 'nutrition-report-style': style })
    await state.generateReport('excel')
    state.batchFormat.value = 'excel'
    await state.generateAllReports()
    assert.equal(state.reportErrorMessage.value, '')
    assert.equal(state.batchError.value, '')
    assert.equal(Object.hasOwn(state.requests[0].body, 'report_style'), false)
    assert.equal(Object.hasOwn(state.requests[1].body, 'report_style'), false)
    requestsByStyle.push(state.requests)
  }
  assert.deepEqual(requestsByStyle[0], requestsByStyle[1])
})
