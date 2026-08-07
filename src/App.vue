<template>
  <main class="page-shell">
    <nav class="workspace-tabs" aria-label="工作台切换"><button :class="{ active: activeWorkspace === 'medical' }" @click="activeWorkspace = 'medical'">体检报告回写</button><button :class="{ active: activeWorkspace === 'nutrition' }" @click="activeWorkspace = 'nutrition'">食物频率调查</button><button :class="{ active: activeWorkspace === 'imaging' }" @click="activeWorkspace = 'imaging'">影像识别</button><button :class="{ active: activeWorkspace === 'general' }" @click="activeWorkspace = 'general'">通用识别</button></nav>

    <template v-if="activeWorkspace === 'medical'">
    <header class="workspace-workbar">
      <div class="workspace-workbar-context"><strong>体检报告回写</strong><span>{{ people.length ? `${people.length} 名受检者 · 可逐项核对并修正回写结果` : '上传体检 PDF，自动识别并回写 Excel' }}</span></div>
      <div class="workspace-workbar-actions"><button v-if="people.length" class="primary-button" type="button" :disabled="savingReview" @click="saveReview">{{ savingReview ? '正在保存…' : '保存修改并下载 Excel' }}</button><button :class="['workspace-settings-button', { 'needs-attention': !serverUrl }]" type="button" aria-label="打开体检报告设置" title="OCR 服务、模板与正常范围设置" @click="openMedicalSettings"><span aria-hidden="true">⚙</span><span class="settings-button-label">设置</span></button></div>
    </header>

    <div v-if="medicalSettingsOpen" class="settings-backdrop workspace-settings-backdrop" @click.self="closeMedicalSettings">
      <section class="settings-dialog workspace-settings-dialog" role="dialog" aria-modal="true" aria-labelledby="medical-settings-title">
        <div class="settings-head"><div><h2 id="medical-settings-title">体检报告设置</h2><p>配置 OCR 服务、识别方式、Excel 汇总模板和指标正常范围。</p></div><button class="dialog-close" type="button" aria-label="关闭体检报告设置" @click="closeMedicalSettings">×</button></div>
        <div class="nutrition-settings-content">
          <section class="nutrition-settings-group"><div class="settings-group-title"><span>1</span><div><h3>云端 OCR 服务</h3><p>用于识别体检报告中的文字和表格。</p></div></div><div class="input-row"><input v-model.trim="serverUrl" class="text-input" placeholder="https://your-host:8443 或完整 /parse-file 地址" /><button type="button" class="secondary-button" :disabled="checkingServer || !serverUrl" @click="testOcr">{{ checkingServer ? '检查中…' : '测试连接' }}</button></div><div class="recognition-options"><label class="parse-mode">识别结果解析来源 <select v-model="parseMode"><option value="markdown">Markdown（推荐：保留表格列）</option><option value="excel">Excel</option></select></label><label class="parse-mode">识别速度 <select v-model="processingMode"><option value="fast">快速模式（推荐）</option><option value="accurate">精确模式（较慢）</option></select></label></div><p class="mode-help">快速模式保留每页主 OCR，并只在每名受检者的第一页缺姓名时补识别；精确模式会对更多缺姓名页面补识别。</p><p v-if="serverMessage" :class="['server-state', serverOk ? 'ok' : 'error']">{{ serverMessage }}</p></section>
          <section class="nutrition-settings-group"><div class="settings-group-title"><span>2</span><div><h3>汇总模板与正常范围</h3><p>模板用于回写字段，正常范围用于标记异常结果。</p></div></div><label class="settings-file-picker"><input type="file" accept=".xlsx,.xlsm" @change="selectTemplate" /><strong>选择 Excel 汇总模板</strong><span>{{ templateFile ? templateFile.name : (lastTemplate.exists ? `沿用：${lastTemplate.filename}` : '尚未选择模板') }}</span></label><div class="medical-settings-links"><span v-if="lastTemplate.exists">已保存于本机：{{ lastTemplate.path }}</span><button class="secondary-button mini-button" type="button" @click="openNormalRangeSettings">编辑指标正常范围</button></div></section>
        </div>
        <div class="settings-actions"><button class="secondary-button" type="button" @click="closeMedicalSettings">取消</button><button class="primary-button" type="button" @click="saveMedicalSettings">保存设置</button></div>
      </section>
    </div>

    <div v-if="normalRangeSettingsOpen" class="settings-backdrop normal-range-settings-backdrop" @click.self="closeNormalRangeSettings">
      <section class="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="normal-range-title">
        <div class="settings-head"><div><h2 id="normal-range-title">体检指标正常范围</h2><p>这里只保存默认参考范围，后续批次直接使用，不再从每份报告 OCR 读取参考值。留空的项目不判断异常。</p></div><button class="text-button" type="button" @click="closeNormalRangeSettings">关闭</button></div>
        <div class="normal-range-wrap"><table class="normal-range-table"><thead><tr><th>指标</th><th>正常下限</th><th>正常上限</th></tr></thead><tbody><tr v-for="item in normalRangeDraft" :key="item.key"><td>{{ item.label }}</td><td><input v-model="item.min" inputmode="decimal" type="number" step="any" placeholder="不设下限" /></td><td><input v-model="item.max" inputmode="decimal" type="number" step="any" placeholder="不设上限" /></td></tr></tbody></table></div>
        <p class="hint">适用于当前报告体系的稳定范围已预填；性激素等受周期影响的项目默认留空，请按实际项目口径填写。</p>
        <p v-if="normalRangeError" class="error-message">{{ normalRangeError }}</p>
        <div class="settings-actions"><button class="secondary-button" type="button" @click="closeNormalRangeSettings">取消</button><button class="primary-button" type="button" :disabled="savingNormalRanges" @click="saveNormalRanges">{{ savingNormalRanges ? '保存中…' : '保存默认范围' }}</button></div>
      </section>
    </div>

    <section class="card">
      <div class="section-title"><div><span class="step">1</span><h2>选择批次文件</h2></div></div>
      <p class="hint">选择 PDF 或包含人员子文件夹的根目录。OCR 服务、Excel 模板和正常范围可从顶部栏右侧设置。</p>
      <div class="upload-actions">
        <label class="drop-zone compact" :class="{ ready: pdfFiles.length && inputMode === 'files' }"><input type="file" accept=".pdf,application/pdf" multiple @change="selectPdfFiles" /><strong>直接选择 PDF</strong><span>{{ inputMode === 'files' && pdfFiles.length ? `已选 ${pdfFiles.length} 份，每份单独处理` : '支持单个或多个 PDF' }}</span></label>
        <label class="drop-zone compact" :class="{ ready: pdfFiles.length && inputMode === 'folder' }"><input type="file" accept=".pdf,application/pdf" multiple webkitdirectory directory @change="selectReportRoot" /><strong>选择报告文件夹</strong><span>{{ inputMode === 'folder' && pdfFiles.length ? `已读取 ${pdfFiles.length} 份 PDF` : '自动按子文件夹归为人员' }}</span></label>
      </div>
      <div v-if="pdfFiles.length" class="batch-summary"><span>将处理 <b>{{ peopleFolders.length }}</b> 名受检者 / <b>{{ pdfFiles.length }}</b> 个 PDF</span><span v-for="folder in peopleFolders.slice(0, 6)" :key="folder">{{ folder }}</span><span v-if="peopleFolders.length > 6">…</span></div>
      <div class="action-row"><button class="primary-button" :disabled="!canProcess" @click="processBatch">开始自动识别并回写</button><button class="secondary-button" type="button" :disabled="processing" @click="clearBatch">清空</button></div>
      <div v-if="processing" class="progress-panel"><div class="progress-label"><strong>{{ progressText }}</strong><span>{{ progress.completed }}/{{ progress.total }}</span></div><div class="progress-track"><div class="progress-bar" :style="{ width: progressPercent + '%' }"></div></div><p>{{ progress.currentFile || '正在准备任务…' }}</p></div>
      <p v-if="processError" class="error-message">{{ processError }}</p><p v-if="processMessage" class="success-message">{{ processMessage }}</p>
    </section>

    <section v-if="people.length" class="card people-card">
      <div class="section-title"><div><span class="step">2</span><h2>逐人核对与人工修正</h2></div></div>
      <p class="hint">所有模板字段均可编辑；自动未匹配字段保持空白，人工填写后点击保存。每页云端返回的 OCR Excel 已留存在本机。</p>
      <div class="review-layout">
        <aside class="person-list"><button v-for="person in people" :key="person.id" type="button" :class="['person-item', { active: selectedPersonId === person.id, 'has-abnormal-items': abnormalCount(person) }]" @click="selectedPersonId = person.id"><strong>{{ person.id }}</strong><span>第 {{ person.row }} 行 · {{ person.page_count }} 页 · {{ matchedCount(person) }}/{{ person.review_fields.length }} 项自动填写</span><span v-if="abnormalCount(person)" class="person-abnormal-count">{{ abnormalCount(person) }} 项超出范围</span></button></aside>
        <div v-if="selectedPerson" class="person-detail">
          <div class="detail-head"><div><h3>{{ selectedPerson.id }}</h3><p>写入汇总表第 {{ selectedPerson.row }} 行。可直接编辑任意单元格的值；超出已设置范围的项目会标红。</p></div><span class="match-badge">{{ matchedCount(selectedPerson) }} 项自动填写</span></div>
          <div class="ocr-downloads"><span>OCR 原始结果：</span><a v-for="(file, index) in selectedPerson.ocr_files" :key="file" :href="file" download>第 {{ index + 1 }} 页 Excel</a><a v-for="(file, index) in selectedPerson.markdown_files || []" :key="file" :href="file" download>第 {{ index + 1 }} 页 Markdown</a></div>
          <div class="mapping-wrap"><table class="mapping-table review-table"><thead><tr><th>汇总表字段</th><th>自动匹配来源</th><th>正常范围</th><th>状态</th><th>填写值（可修改）</th></tr></thead><tbody><tr v-for="field in selectedPerson.review_fields" :key="field.header" :class="{ 'not-matched': !field.source, 'abnormal-row': isFieldAbnormal(field) }"><td>{{ field.header }}</td><td>{{ field.source || '未自动匹配' }}</td><td>{{ fieldNormalRange(field) || '未设置' }}</td><td><span v-if="isFieldAbnormal(field)" class="abnormal-badge">{{ fieldAbnormalReason(field) }}</span><span v-else class="normal-state">{{ fieldNormalRange(field) ? '正常' : '未判断' }}</span></td><td><input v-model="field.value" class="value-input" :placeholder="field.source ? '' : '保持空白或人工填写'" /></td></tr></tbody></table></div>
        </div>
      </div>
    </section>
    </template>
    <NutritionWorkspace v-else-if="activeWorkspace === 'nutrition'" />
    <ImagingWorkspace v-else-if="activeWorkspace === 'imaging'" />
    <GeneralOcrWorkspace v-else />
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import NutritionWorkspace from './components/NutritionWorkspace.vue'
import ImagingWorkspace from './components/ImagingWorkspace.vue'
import GeneralOcrWorkspace from './components/GeneralOcrWorkspace.vue'

const storageKey = 'medical-ocr-api-url'
const activeWorkspace = ref('medical')
const serverUrl = ref(localStorage.getItem(storageKey) || '')
const parseMode = ref(localStorage.getItem('ocr-parse-mode') || 'markdown')
const processingMode = ref(localStorage.getItem('ocr-processing-mode') || 'fast')
const serverMessage = ref(''); const serverOk = ref(false); const checkingServer = ref(false)
const templateFile = ref(null); const pdfFiles = ref([]); const inputMode = ref('folder')
const lastTemplate = ref({ exists: false, filename: '', saved_at: '', path: '' })
const processing = ref(false); const savingReview = ref(false); const processError = ref(''); const processMessage = ref('')
const progress = ref({ completed: 0, total: 0, currentFile: '', message: '' })
const people = ref([]); const selectedPersonId = ref(''); const outputUrl = ref('')
const normalRangeItems = ref([]); const normalRangeDraft = ref([]); const normalRangeSettingsOpen = ref(false)
const savingNormalRanges = ref(false); const normalRangeError = ref('')
const medicalSettingsOpen = ref(false); const medicalSettingsSnapshot = ref(null)

const canProcess = computed(() => !!(serverUrl.value && (templateFile.value || lastTemplate.value.exists) && pdfFiles.value.length && !processing.value))
const peopleFolders = computed(() => [...new Set(pdfFiles.value.map(personFolder))].sort((a, b) => a.localeCompare(b, 'zh-CN')))
const selectedPerson = computed(() => people.value.find((person) => person.id === selectedPersonId.value) || people.value[0])
const progressPercent = computed(() => progress.value.total ? Math.round((progress.value.completed / progress.value.total) * 100) : 0)
const progressText = computed(() => progress.value.total ? `正在处理第 ${Math.min(progress.value.completed + 1, progress.value.total)}/${progress.value.total} 个 PDF` : '正在准备上传文件')

function personFolder(file) {
  if (inputMode.value === 'files') return file.name.replace(/\.pdf$/i, '')
  const parts = (file.webkitRelativePath || file.name).split('/').filter(Boolean)
  return parts.length > 1 ? parts.slice(0, -1).join('/') : file.name.replace(/\.pdf$/i, '')
}
function matchedCount(person) { return person.review_fields.filter((field) => field.source && field.value).length }
function rangeForField(field) { return normalRangeItems.value.find((item) => item.key === field.range_key) || null }
function numberOrNull(value) { if (value === '' || value === null || value === undefined) return null; const number = Number(value); return Number.isFinite(number) ? number : null }
function formatNumber(value) { return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 12 }) }
function formatNormalRange(range) { if (!range) return ''; const min = numberOrNull(range.min); const max = numberOrNull(range.max); if (min !== null && max !== null) return `${formatNumber(min)}–${formatNumber(max)}`; if (min !== null) return `≥ ${formatNumber(min)}`; if (max !== null) return `≤ ${formatNumber(max)}`; return '' }
function fieldAssessment(field) {
  const range = rangeForField(field); const min = numberOrNull(range?.min); const max = numberOrNull(range?.max)
  const match = String(field.value ?? '').trim().match(/^(<=|>=|<|>|≤|≥)?\s*(\d+(?:\.\d+)?)\s*%?\s*$/)
  if ((!range || (min === null && max === null)) || !match) return { abnormal: false, reason: '' }
  const operator = match[1] || ''; const value = Number(match[2])
  const below = min !== null && (operator === '' || operator === '<=') ? value < min : min !== null && operator === '<' ? value <= min : false
  const above = max !== null && (operator === '' || operator === '>=') ? value > max : max !== null && operator === '>' ? value >= max : false
  return below ? { abnormal: true, reason: '低于正常范围' } : above ? { abnormal: true, reason: '高于正常范围' } : { abnormal: false, reason: '' }
}
function fieldNormalRange(field) { const range = rangeForField(field); return range ? formatNormalRange(range) : field.normal_range || '' }
function isFieldAbnormal(field) { return fieldAssessment(field).abnormal }
function fieldAbnormalReason(field) { return fieldAssessment(field).reason || field.abnormal_reason || '超出正常范围' }
function abnormalCount(person) { return person.review_fields.filter(isFieldAbnormal).length }
function saveServerUrl() { localStorage.setItem(storageKey, serverUrl.value.trim()); serverOk.value = true; serverMessage.value = '云端地址已保存到当前浏览器。' }
function saveParseMode() { localStorage.setItem('ocr-parse-mode', parseMode.value) }
function saveProcessingMode() { localStorage.setItem('ocr-processing-mode', processingMode.value) }
function openMedicalSettings() { medicalSettingsSnapshot.value = { serverUrl: serverUrl.value, parseMode: parseMode.value, processingMode: processingMode.value, templateFile: templateFile.value }; medicalSettingsOpen.value = true }
function closeMedicalSettings() { const snapshot = medicalSettingsSnapshot.value; if (snapshot) { serverUrl.value = snapshot.serverUrl; parseMode.value = snapshot.parseMode; processingMode.value = snapshot.processingMode; templateFile.value = snapshot.templateFile }; medicalSettingsSnapshot.value = null; medicalSettingsOpen.value = false }
function saveMedicalSettings() { saveServerUrl(); saveParseMode(); saveProcessingMode(); medicalSettingsSnapshot.value = null; medicalSettingsOpen.value = false }
function selectTemplate(event) { templateFile.value = event.target.files?.[0] || null }
function setFiles(files, mode) { inputMode.value = mode; pdfFiles.value = Array.from(files || []).filter((file) => /\.pdf$/i.test(file.name)); processError.value = ''; processMessage.value = '' }
function selectPdfFiles(event) { setFiles(event.target.files, 'files') }
function selectReportRoot(event) { setFiles(event.target.files, 'folder') }
function clearBatch() { templateFile.value = null; pdfFiles.value = []; people.value = []; selectedPersonId.value = ''; outputUrl.value = ''; processMessage.value = ''; processError.value = ''; progress.value = { completed: 0, total: 0, currentFile: '', message: '' } }
async function testOcr() {
  checkingServer.value = true; serverMessage.value = ''
  try { const body = new FormData(); body.append('ocr_url', serverUrl.value); const response = await fetch('/local-api/test-ocr', { method: 'POST', body }); const data = await response.json(); if (!response.ok) throw new Error(data.detail || '服务不可用'); serverOk.value = true; serverMessage.value = data.message }
  catch (error) { serverOk.value = false; serverMessage.value = `连接失败：${error.message}` } finally { checkingServer.value = false }
}
async function processBatch() {
  processing.value = true; processError.value = ''; processMessage.value = ''; people.value = []; progress.value = { completed: 0, total: pdfFiles.value.length, currentFile: '', message: '' }
  try {
    saveServerUrl(); saveProcessingMode(); const body = new FormData(); body.append('ocr_url', serverUrl.value); if (templateFile.value) body.append('template', templateFile.value); body.append('parse_mode', parseMode.value); body.append('processing_mode', processingMode.value)
    pdfFiles.value.forEach((file) => { body.append('files', file); body.append('relative_paths', inputMode.value === 'folder' ? (file.webkitRelativePath || file.name) : file.name) })
    const response = await fetch('/local-api/process', { method: 'POST', body }); const data = await response.json(); if (!response.ok || !data.success) throw new Error(data.detail || '任务创建失败'); lastJobId.value = data.job_id
    await pollJob(data.job_id)
  } catch (error) { processError.value = error.message || '批量处理失败'; processing.value = false }
}
async function pollJob(jobId) {
  const response = await fetch(`/local-api/jobs/${jobId}`); const data = await response.json(); if (!response.ok) throw new Error(data.detail || '无法读取任务进度')
  progress.value = { completed: data.completed_files, total: data.total_files, currentFile: data.current_file, message: data.message }
  if (data.status === 'completed') { people.value = data.people; selectedPersonId.value = data.people[0]?.id || ''; outputUrl.value = data.output_url; processMessage.value = data.message; processing.value = false; return }
  if (data.status === 'failed') throw new Error(data.message || 'OCR 任务失败')
  window.setTimeout(() => pollJob(jobId).catch((error) => { processError.value = error.message; processing.value = false }), 700)
}
async function saveReview() {
  savingReview.value = true; processError.value = ''
  try {
    const response = await fetch(`/local-api/jobs/${lastJobId.value}/save-review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ people: people.value }) })
    const data = await response.json(); if (!response.ok || !data.success) throw new Error(data.detail || '保存失败'); if (data.people) people.value = data.people; outputUrl.value = data.output_url; processMessage.value = data.message; window.location.assign(data.output_url)
  } catch (error) { processError.value = error.message || '保存人工修改失败' } finally { savingReview.value = false }
}
const lastJobId = ref('')
async function loadMedicalNormalRanges() {
  try {
    const response = await fetch('/local-api/medical-normal-ranges'); if (!response.ok) return
    const data = await response.json(); normalRangeItems.value = (data.items || []).map((item) => ({ ...item, min: item.min ?? '', max: item.max ?? '' }))
  } catch (_) { /* 本地服务未启动时不阻塞页面 */ }
}
function openNormalRangeSettings() { normalRangeError.value = ''; normalRangeDraft.value = normalRangeItems.value.map((item) => ({ ...item })); normalRangeSettingsOpen.value = true }
function closeNormalRangeSettings() { if (!savingNormalRanges.value) normalRangeSettingsOpen.value = false }
async function saveNormalRanges() {
  savingNormalRanges.value = true; normalRangeError.value = ''
  try {
    const ranges = Object.fromEntries(normalRangeDraft.value.map((item) => [item.key, { min: item.min, max: item.max }]))
    const response = await fetch('/local-api/medical-normal-ranges', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ranges }) })
    const data = await response.json(); if (!response.ok || !data.success) throw new Error(data.detail || '正常范围保存失败')
    normalRangeItems.value = normalRangeDraft.value.map((item) => ({ ...item })); normalRangeSettingsOpen.value = false; processMessage.value = data.message
  } catch (error) { normalRangeError.value = error.message || '正常范围保存失败' } finally { savingNormalRanges.value = false }
}
async function loadLastTemplate() {
  try { const response = await fetch('/local-api/medical-template-status'); if (response.ok) lastTemplate.value = await response.json() } catch (_) { /* 本地服务未启动时不阻塞页面 */ }
}
onMounted(() => { loadLastTemplate(); loadMedicalNormalRanges() })
</script>
