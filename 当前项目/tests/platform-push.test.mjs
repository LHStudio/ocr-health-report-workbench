import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
const source = fs.readFileSync(new URL('../src/components/PlatformPush.vue', import.meta.url), 'utf8')
function setup() {
  const calls = [], timers = []
  const props = { kind: 'imaging', jobId: 'fixture', count: 2, disabled: false,
    snapshot: () => ({ records: [{ id: 'all-1' }, { id: 'all-2' }] }) }
  const context = vm.createContext({ defineProps: () => props,
    ref: (value) => ({ value }), computed: (fn) => ({ get value() { return fn() } }),
    watch() {}, onBeforeUnmount() {}, window: { clearTimeout() {}, setTimeout(fn) { timers.push(fn) } },
    fetch: async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => ({ phase: 'completed', records: [], counts: {} }) } },
  })
  vm.runInContext(source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '') +
    '\nthis.api={upload,poll,config,result,submitting,blocked}', context)
  context.api.config.value = { configured: true }
  return { ...context.api, calls, timers, props, context }
}
test('no POST until explicit click, full snapshot not pagination, retry flag explicit', async () => {
  const api = setup()
  assert.equal(api.calls.length, 0)
  await api.upload(false)
  const posts = api.calls.filter(c => c.options?.method === 'POST')
  assert.equal(posts.length, 1)
  assert.equal(JSON.parse(posts[0].options.body).records.length, 2)
  assert.equal(JSON.parse(posts[0].options.body).retry_failed, false)
  await api.upload(true)
  assert.equal(JSON.parse(api.calls.filter(c => c.options?.method === 'POST')[1].options.body).retry_failed, true)
})
test('busy and unconfigured buttons do not POST', async () => {
  const api = setup()
  api.submitting.value = true
  await api.upload(false)
  api.submitting.value = false; api.config.value = { configured: false }
  await api.upload(false)
  assert.equal(api.calls.length, 0)
})
test('lost POST response queries status without retrying POST', async () => {
  const api = setup(), methods = []
  api.context.fetch = async (url, options) => {
    methods.push(options?.method || 'GET')
    if (options) throw new Error('connection lost')
    return { ok: true, json: async () => ({ phase: 'running', records: [], counts: {} }) }
  }
  await api.upload(false)
  assert.deepEqual(methods, ['POST', 'GET'])
  assert.equal(api.blocked.value, true)
  assert.equal(api.timers.length, 1)
})
test('result names and platform messages are text, no token storage', () => {
  assert.doesNotMatch(source, /v-html|localStorage|X-Open-Token|SURVEY_OPEN_TOKEN/)
  assert.match(source, /\{\{ row.message \}\}/)
})
