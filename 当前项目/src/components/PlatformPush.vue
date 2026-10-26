<template>
  <section class="platform-push" :aria-label="`${label}平台推送`">
    <div class="platform-push-head">
      <div><strong>{{ label }} · 推送到运动员平台</strong><p>上传当前任务全部 {{ count }} 人的当前核对数据，不受搜索或分页限制。仅点击后发送；同人同日期可能更新平台记录。</p></div>
      <button class="primary-button" type="button" :disabled="blocked" @click="upload(false)">{{ busy ? '正在上传到平台…' : `${label}一键上传到平台` }}</button>
    </div>
    <p v-if="kind === 'imaging'" class="hint">仅推送姓名、性别、年龄、超声所见、超声诊断、检查时间；Excel 下载仍保留原有全部列。</p>
    <p v-if="kind === 'nutrition'" class="hint">按当前核对资料生成营养报告数据后推送（非 PDF）；保留人工评价，无法换算的人员显示原因。</p>
    <p v-if="config && !config.configured" class="error-message">{{ config.message }}</p>
    <p v-if="error" class="error-message" role="alert">{{ error }}</p>
    <div v-if="result" aria-live="polite">
      <p>{{ result.message }}</p>
      <p>成功 {{ result.counts.success }} · 已成功跳过 {{ result.counts.skipped }} · 失败 {{ result.counts.failed }} · 待核对 {{ result.counts.rejected }} · 回执不明 {{ result.counts.uncertain }} · 待发送 {{ result.counts.pending }}</p>
      <button v-if="result.counts.failed" class="secondary-button" type="button" :disabled="blocked" @click="upload(true)">重试明确失败项</button>
      <details v-if="result.records.length" :open="!!(result.counts.failed || result.counts.rejected || result.counts.uncertain)">
        <summary>查看逐人推送结果（{{ result.records.length }} 人）</summary>
        <div class="platform-push-results"><table><thead><tr><th>姓名</th><th>日期</th><th>结果</th><th>说明</th></tr></thead><tbody>
          <tr v-for="(row, index) in result.records" :key="`${row.person_id}-${index}`"><td>{{ row.name }}</td><td>{{ row.date || '待核对' }}</td><td>{{ statusLabels[row.status] || row.status }}</td><td>{{ row.message }}</td></tr>
        </tbody></table></div>
      </details>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
const props = defineProps({ kind: { type: String, required: true }, jobId: { type: String, default: '' },
  label: { type: String, required: true }, count: { type: Number, default: 0 }, disabled: Boolean,
  snapshot: { type: Function, required: true } })
const config = ref(null), result = ref(null), error = ref(''), submitting = ref(false)
const statusLabels = { success: '成功', skipped: '此前已成功', failed: '明确失败', rejected: '待核对/未发送', uncertain: '回执不明/未重发', pending: '待发送', sending: '等待回执' }
const running = computed(() => ['queued', 'preparing', 'running'].includes(result.value?.phase))
const busy = computed(() => submitting.value || running.value)
const blocked = computed(() => busy.value || props.disabled || !props.jobId || !props.count || !config.value?.configured)
let timer, generation = 0
function endpoint(jobId = props.jobId) { return `/local-api/platform-push/${props.kind}/${encodeURIComponent(jobId)}` }
async function jsonResponse(response) {
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail || '推送服务不可用，请确认本地后端已更新')
  return data
}
async function poll(epoch, jobId) {
  try {
    const data = await jsonResponse(await fetch(endpoint(jobId)))
    if (epoch !== generation) return
    result.value = data
    error.value = ''
    if (running.value) timer = window.setTimeout(() => poll(epoch, jobId), 1200)
  } catch (err) {
    if (epoch !== generation) return
    error.value = `状态读取失败：${err.message}。正在重新查询，不会重新发送。`
    timer = window.setTimeout(() => poll(epoch, jobId), 3000)
  }
}
async function upload(retryFailed) {
  if (blocked.value) return
  const epoch = generation, jobId = props.jobId
  submitting.value = true; error.value = ''; window.clearTimeout(timer)
  try {
    // Freeze edits before the first await; no save/download side effects.
    const snapshot = JSON.parse(JSON.stringify(props.snapshot()))
    snapshot.retry_failed = retryFailed
    const data = await jsonResponse(await fetch(endpoint(jobId), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(snapshot) }))
    if (epoch !== generation) return
    result.value = data
    await poll(epoch, jobId)
  } catch (err) {
    if (epoch !== generation) return
    error.value = err.message
    // A lost POST response can still mean a running upload: query, never POST again.
    try { result.value = await jsonResponse(await fetch(endpoint(jobId))) } catch (_) { /* keep original error */ }
    if (running.value) timer = window.setTimeout(() => poll(epoch, jobId), 1200)
  } finally { if (epoch === generation) submitting.value = false }
}
watch(() => props.jobId, async (jobId) => {
  const epoch = ++generation
  window.clearTimeout(timer); result.value = null; submitting.value = false; error.value = ''
  if (!jobId) return
  try {
    const data = await jsonResponse(await fetch('/local-api/platform-push/config'))
    if (epoch !== generation) return
    config.value = data
    await poll(epoch, jobId)
  } catch (err) { if (epoch === generation) error.value = err.message }
}, { immediate: true })
onBeforeUnmount(() => { ++generation; window.clearTimeout(timer) })
</script>

<style scoped>
.platform-push { margin: 16px 0; padding: 16px; border: 1px solid #b6dcd3; border-radius: 12px; background: #f5fbf9; }
.platform-push-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.platform-push p { margin: 8px 0; line-height: 1.6; }
.platform-push-head button { flex-shrink: 0; }
.platform-push-results { max-height: 320px; overflow: auto; margin-top: 12px; }
table { width: 100%; border-collapse: collapse; text-align: left; }
td, th { padding: 8px; border-bottom: 1px solid #dce8e4; vertical-align: top; }
summary { cursor: pointer; margin-top: 12px; }
@media (max-width: 760px) { .platform-push-head { align-items: stretch; flex-direction: column; } }
</style>
