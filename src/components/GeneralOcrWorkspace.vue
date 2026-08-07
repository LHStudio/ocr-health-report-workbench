<template>
  <section class="general-workspace">
    <header class="workspace-workbar">
      <div class="workspace-workbar-context">
        <strong>通用识别</strong>
        <span>{{ records.length ? `${records.length} 份文档 · ${formatTitle(outputFormat)} 结果已生成` : '识别非医疗类文档，不做字段限制或业务解析' }}</span>
      </div>
      <div class="workspace-workbar-actions">
        <a v-if="outputUrl" class="primary-button general-download-button" :href="outputUrl" download>{{ records.length > 1 ? '下载全部 ZIP' : `下载 ${formatTitle(outputFormat)}` }}</a>
        <button :class="['workspace-settings-button', { 'needs-attention': !serverUrl }]" type="button" aria-label="打开通用识别设置" @click="settingsOpen = true"><span aria-hidden="true">⚙</span><span class="settings-button-label">设置</span></button>
      </div>
    </header>

    <div v-if="settingsOpen" class="settings-backdrop workspace-settings-backdrop" @click.self="settingsOpen = false">
      <section class="settings-dialog workspace-settings-dialog" role="dialog" aria-modal="true" aria-labelledby="general-settings-title">
        <div class="settings-head"><div><h2 id="general-settings-title">通用识别设置</h2><p>通用识别只调用 OCR，不套用体检、营养或影像字段规则。</p></div><button class="dialog-close" type="button" aria-label="关闭通用识别设置" @click="settingsOpen = false">×</button></div>
        <div class="nutrition-settings-content">
          <section class="nutrition-settings-group">
            <div class="settings-group-title"><span>1</span><div><h3>云端 OCR 服务</h3><p>与其他工作台共享同一个浏览器地址配置。</p></div></div>
            <div class="input-row"><input v-model.trim="serverUrl" class="text-input" placeholder="https://your-host:8443 或完整 /parse-file 地址" /><button class="secondary-button" type="button" :disabled="checkingServer || !serverUrl" @click="testOcr">{{ checkingServer ? '检查中…' : '测试连接' }}</button></div>
            <p v-if="serverMessage" :class="['server-state', serverOk ? 'ok' : 'error']">{{ serverMessage }}</p>
          </section>
          <section class="nutrition-settings-group">
            <div class="settings-group-title"><span>2</span><div><h3>识别模式</h3><p>精确模式适合复杂版面；快速模式减少补充识别步骤。</p></div></div>
            <label class="parse-mode">识别速度 <select v-model="processingMode"><option value="accurate">精确模式（推荐）</option><option value="fast">快速模式</option></select></label>
          </section>
        </div>
        <div class="settings-actions"><button class="secondary-button" type="button" @click="settingsOpen = false">取消</button><button class="primary-button" type="button" @click="saveSettings">保存设置</button></div>
      </section>
    </div>

    <section class="card">
      <div class="section-title"><div><span class="step">1</span><h2>选择文档与返回格式</h2></div></div>
      <p class="hint">可识别 PDF、PNG、JPG、JPEG、BMP 和 WEBP。系统仅还原 OCR 内容，不要求文档属于现有医疗业务。</p>
      <div class="general-format-grid" role="radiogroup" aria-label="OCR 返回格式">
        <button v-for="option in formatOptions" :key="option.value" type="button" role="radio" :aria-checked="outputFormat === option.value" :disabled="processing" :class="['general-format-option', { active: outputFormat === option.value }]" @click="selectOutputFormat(option.value)">
          <span class="general-format-icon">{{ option.icon }}</span><span><strong>{{ option.title }}</strong><small>{{ option.description }}</small></span><span class="general-format-check">{{ outputFormat === option.value ? '✓' : '' }}</span>
        </button>
      </div>
      <div class="upload-actions general-upload-actions">
        <label class="drop-zone compact" :class="{ ready: files.length && inputMode === 'files' }"><input type="file" accept=".pdf,.png,.jpg,.jpeg,.bmp,.webp,application/pdf,image/*" multiple @change="selectFiles" /><strong>直接选择文档</strong><span>{{ inputMode === 'files' && files.length ? `已选择 ${files.length} 份文档` : '支持单个或多个文件' }}</span></label>
        <label class="drop-zone compact" :class="{ ready: files.length && inputMode === 'folder' }"><input type="file" accept=".pdf,.png,.jpg,.jpeg,.bmp,.webp,application/pdf,image/*" multiple webkitdirectory directory @change="selectFolder" /><strong>选择文档文件夹</strong><span>{{ inputMode === 'folder' && files.length ? `已读取 ${files.length} 份文档` : '读取文件夹内支持的文件' }}</span></label>
      </div>
      <div v-if="files.length" class="batch-summary"><span>将识别 <b>{{ files.length }}</b> 份文档并返回 {{ formatTitle(outputFormat) }}</span><span v-for="file in files.slice(0, 6)" :key="fileKey(file)">{{ file.name }}</span><span v-if="files.length > 6">…</span></div>
      <div class="action-row"><button class="primary-button" type="button" :disabled="!canProcess" @click="processDocuments">开始通用识别</button><button class="secondary-button" type="button" :disabled="processing" @click="clearAll">清空</button></div>
      <div v-if="processing" class="progress-panel"><div class="progress-label"><strong>正在进行通用 OCR</strong><span>{{ progress.completed }}/{{ progress.total }}</span></div><div class="progress-track"><div class="progress-bar" :style="{ width: progressPercent + '%' }"></div></div><p>{{ progress.currentFile || '正在准备任务…' }}</p></div>
      <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>
      <p v-if="successMessage" class="success-message">{{ successMessage }}</p>
    </section>

    <section v-if="records.length" class="card general-results-card">
      <div class="section-title"><div><span class="step">2</span><h2>识别结果</h2></div><span class="general-result-format">{{ formatTitle(outputFormat) }}</span></div>
      <div class="general-result-list">
        <article v-for="record in records" :key="record.id" class="general-result-item">
          <div class="general-result-head"><div><strong>{{ record.filename }}</strong><span>{{ formatBytes(record.size) }} · {{ formatTitle(record.output_format) }}</span></div><a class="secondary-button mini-button" :href="record.output_url" download>下载此结果</a></div>
          <pre v-if="record.preview" class="general-result-preview">{{ record.preview }}</pre>
          <div v-else class="general-excel-placeholder"><span>XL</span><div><strong>Excel 工作簿已生成</strong><p>点击右上角按钮下载后，可在 Excel 或兼容软件中打开并核对版面内容。</p></div></div>
        </article>
      </div>
    </section>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'

const storageKey = 'medical-ocr-api-url'
const allowedPattern = /\.(pdf|png|jpe?g|bmp|webp)$/i
const formatOptions = [
  { value: 'excel', title: 'Excel', icon: 'XL', description: '适合表格、人工核对和二次整理' },
  { value: 'markdown', title: 'Markdown', icon: 'MD', description: '适合阅读、复制和交给大模型处理' },
  { value: 'json', title: 'JSON', icon: '{}', description: '保留结构化 OCR 区块，便于程序接入' },
]

const serverUrl = ref(localStorage.getItem(storageKey) || '')
const processingMode = ref(localStorage.getItem('general-processing-mode') || 'accurate')
const savedOutputFormat = localStorage.getItem('general-output-format') || 'excel'
const outputFormat = ref(formatOptions.some((option) => option.value === savedOutputFormat) ? savedOutputFormat : 'excel')
const settingsOpen = ref(false)
const checkingServer = ref(false)
const serverOk = ref(false)
const serverMessage = ref('')
const files = ref([])
const inputMode = ref('files')
const processing = ref(false)
const progress = ref({ completed: 0, total: 0, currentFile: '' })
const records = ref([])
const outputUrl = ref('')
const lastJobId = ref('')
const errorMessage = ref('')
const successMessage = ref('')

const canProcess = computed(() => !!(serverUrl.value.trim() && files.value.length && !processing.value))
const progressPercent = computed(() => progress.value.total ? Math.round(progress.value.completed / progress.value.total * 100) : 0)

function formatTitle(value) { return formatOptions.find((option) => option.value === value)?.title || String(value || '').toUpperCase() }
function formatBytes(value) { const bytes = Number(value) || 0; if (bytes < 1024) return `${bytes} B`; if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`; return `${(bytes / 1024 / 1024).toFixed(1)} MB` }
function fileKey(file) { return file.webkitRelativePath || file.name }
function selectOutputFormat(value) { if (processing.value) return; outputFormat.value = value; localStorage.setItem('general-output-format', value); records.value = []; outputUrl.value = ''; successMessage.value = ''; errorMessage.value = '' }
function setFiles(fileList, mode) { files.value = Array.from(fileList || []).filter((file) => allowedPattern.test(file.name)); inputMode.value = mode; records.value = []; outputUrl.value = ''; errorMessage.value = ''; successMessage.value = '' }
function selectFiles(event) { setFiles(event.target.files, 'files') }
function selectFolder(event) { setFiles(event.target.files, 'folder') }
function saveSettings() { localStorage.setItem(storageKey, serverUrl.value.trim()); localStorage.setItem('general-processing-mode', processingMode.value); settingsOpen.value = false; serverOk.value = true }
function clearAll() { files.value = []; records.value = []; outputUrl.value = ''; lastJobId.value = ''; errorMessage.value = ''; successMessage.value = ''; progress.value = { completed: 0, total: 0, currentFile: '' } }
async function ensureLocalFeature() {
  try { const response = await fetch('/local-api/'); const data = await response.json(); if (!response.ok || !Array.isArray(data.features) || !data.features.includes('general')) throw new Error('本地后端仍是旧版本，请停止旧进程后重新运行 npm run backend') }
  catch (error) { if (String(error.message || '').includes('旧版本')) throw error; throw new Error('无法连接本地后端，请确认已重新运行 npm run backend') }
}

async function testOcr() {
  checkingServer.value = true; serverMessage.value = ''
  try { const body = new FormData(); body.append('ocr_url', serverUrl.value); const response = await fetch('/local-api/test-ocr', { method: 'POST', body }); const data = await response.json(); if (!response.ok) throw new Error(data.detail || '服务不可用'); serverOk.value = true; serverMessage.value = data.message }
  catch (error) { serverOk.value = false; serverMessage.value = `连接失败：${error.message}` }
  finally { checkingServer.value = false }
}

async function processDocuments() {
  processing.value = true; errorMessage.value = ''; successMessage.value = ''; records.value = []; outputUrl.value = ''; progress.value = { completed: 0, total: files.value.length, currentFile: '' }
  try {
    await ensureLocalFeature()
    saveSettings()
    const body = new FormData(); body.append('ocr_url', serverUrl.value.trim()); body.append('processing_mode', processingMode.value); body.append('output_format', outputFormat.value); files.value.forEach((file) => body.append('files', file))
    const response = await fetch('/local-api/general/process', { method: 'POST', body }); const data = await response.json(); if (!response.ok || !data.success) throw new Error(data.detail || '任务创建失败')
    lastJobId.value = data.job_id; await pollJob(data.job_id)
  } catch (error) { errorMessage.value = error.message || '通用识别失败'; processing.value = false }
}

async function pollJob(jobId) {
  const response = await fetch(`/local-api/jobs/${jobId}`); const data = await response.json(); if (!response.ok) throw new Error(data.detail || '无法读取任务进度')
  progress.value = { completed: data.completed_files || 0, total: data.total_files || 0, currentFile: data.current_file || '' }
  if (data.status === 'completed') { outputFormat.value = data.output_format || outputFormat.value; records.value = data.records || []; outputUrl.value = data.output_url || ''; successMessage.value = data.message; processing.value = false; return }
  if (data.status === 'failed') throw new Error(data.message || '通用 OCR 任务失败')
  window.setTimeout(() => pollJob(jobId).catch((error) => { errorMessage.value = error.message; processing.value = false }), 700)
}
</script>
