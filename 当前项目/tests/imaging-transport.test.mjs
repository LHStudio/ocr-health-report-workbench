import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

const source = fs.readFileSync(new URL('../src/components/ImagingWorkspace.vue', import.meta.url), 'utf8')
function workspace(data) {
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
  const context = vm.createContext({
    ref: (value) => ({ value }), computed: (getter) => ({ get value() { return getter() } }),
    watch() {}, storedOcrApiUrl: () => 'https://ocr.example', localStorage: { getItem: () => '', setItem() {} },
    window: { setTimeout() {} }, fetch: async () => ({ ok: true, json: async () => data }),
  })
  vm.runInContext(script + '\nthis.api = {pollJob, clearAll, records, errorMessage, successMessage, processing, progress, fileErrors: typeof fileErrors === "undefined" ? undefined : fileErrors}', context)
  return context.api
}

test('partial batch retains successful records and exposes failed file details', async () => {
  const data = { status: 'completed', records: [{ id: 'imaging-001', filename: 'first.pdf' }], file_errors: [{ filename: 'second.pdf', message: 'HTTP 404' }], completed_files: 2, total_files: 2, message: '1 份成功，1 份失败' }
  const api = workspace(data)
  await api.pollJob('fixture')
  assert.equal(api.records.value.length, 1)
  assert.equal(api.fileErrors?.value[0]?.filename, 'second.pdf')
  assert.equal(api.progress.value.completed, 2)
  assert.equal(api.processing.value, false)
})

test('all-failed batch keeps structured errors visible while reporting failure', async () => {
  const api = workspace({ status: 'failed', records: [], file_errors: [{ filename: 'first.pdf', message: 'HTTP 404' }], message: '全部失败' })
  await assert.rejects(() => api.pollJob('fixture'), /全部失败/)
  assert.equal(api.fileErrors?.value[0]?.message, 'HTTP 404')
  assert.equal(api.records.value.length, 0)
})

test('clear resets previous failed file list', () => {
  const api = workspace({})
  assert.ok(api.fileErrors)
  api.fileErrors.value = [{ filename: 'previous.pdf' }]
  api.clearAll()
  assert.equal(api.fileErrors.value.length, 0)
})

test('failed file details are rendered as text, not injected HTML', () => {
  assert.match(source, /v-for="[^\"]*fileErrors[^\"]*"/)
  assert.match(source, /\{\{\s*[^}]*\.filename\s*\}\}/)
  assert.match(source, /\{\{\s*[^}]*\.message\s*\}\}/)
  assert.doesNotMatch(source, /v-html/)
})

test('retry notice tells users to export successes before starting a new batch', () => {
  assert.match(source, /先导出并保存本批成功结果/)
  assert.match(source, /重新选择失败文件创建新任务/)
  assert.doesNotMatch(source, /请仅重新选择失败文件重试/)
})
