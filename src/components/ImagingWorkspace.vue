<template>
  <section class="imaging-workspace">
    <header class="workspace-workbar">
      <div class="workspace-workbar-context">
        <strong>影像识别</strong>
        <span>{{ records.length ? `${records.length} 份超声报告 · ${reviewRecordCount} 份待核对` : '批量提取姓名、性别、年龄、超声所见、超声诊断和检查时间' }}</span>
      </div>
      <div class="workspace-workbar-actions">
        <button v-if="records.length" class="primary-button" type="button" :disabled="saving" @click="saveAndDownload">{{ saving ? '正在保存…' : '保存核对并下载 Excel' }}</button>
        <button :class="['workspace-settings-button', { 'needs-attention': !serverUrl }]" type="button" aria-label="打开影像识别设置" @click="settingsOpen = true"><span aria-hidden="true">⚙</span><span class="settings-button-label">设置</span></button>
      </div>
    </header>

    <div v-if="settingsOpen" class="settings-backdrop workspace-settings-backdrop" @click.self="settingsOpen = false">
      <section class="settings-dialog workspace-settings-dialog" role="dialog" aria-modal="true" aria-labelledby="imaging-settings-title">
        <div class="settings-head"><div><h2 id="imaging-settings-title">影像识别设置</h2><p>使用与其他工作台相同的云端 OCR 服务；精确模式适合扫描质量不稳定的报告。</p></div><button class="dialog-close" type="button" aria-label="关闭影像识别设置" @click="settingsOpen = false">×</button></div>
        <div class="nutrition-settings-content">
          <section class="nutrition-settings-group">
            <div class="settings-group-title"><span>1</span><div><h3>云端 OCR 服务</h3><p>地址保存在当前浏览器，并与体检报告工作台共享。</p></div></div>
            <div class="input-row"><input v-model.trim="serverUrl" class="text-input" placeholder="https://your-host:8443 或完整 /parse-file 地址" /><button class="secondary-button" type="button" :disabled="checkingServer || !serverUrl" @click="testOcr">{{ checkingServer ? '检查中…' : '测试连接' }}</button></div>
            <p v-if="serverMessage" :class="['server-state', serverOk ? 'ok' : 'error']">{{ serverMessage }}</p>
          </section>
          <section class="nutrition-settings-group">
            <div class="settings-group-title"><span>2</span><div><h3>识别模式</h3><p>默认精确模式；快速模式可减少补充识别步骤。</p></div></div>
            <label class="parse-mode">识别速度 <select v-model="processingMode"><option value="accurate">精确模式（推荐）</option><option value="fast">快速模式</option></select></label>
          </section>
        </div>
        <div class="settings-actions"><button class="secondary-button" type="button" @click="settingsOpen = false">取消</button><button class="primary-button" type="button" @click="saveSettings">保存设置</button></div>
      </section>
    </div>

    <section class="card">
      <div class="section-title"><div><span class="step">1</span><h2>选择影像 PDF</h2></div></div>
      <p class="hint">支持一次选择多份 PDF 或整个文件夹。每份报告单独识别；原始 OCR 结果会保留，便于追溯。</p>
      <div class="upload-actions">
        <label class="drop-zone compact" :class="{ ready: files.length && inputMode === 'files' }"><input type="file" accept=".pdf,application/pdf" multiple @change="selectFiles" /><strong>直接选择 PDF</strong><span>{{ inputMode === 'files' && files.length ? `已选择 ${files.length} 份报告` : '支持单个或多个 PDF' }}</span></label>
        <label class="drop-zone compact" :class="{ ready: files.length && inputMode === 'folder' }"><input type="file" accept=".pdf,application/pdf" multiple webkitdirectory directory @change="selectFolder" /><strong>选择影像文件夹</strong><span>{{ inputMode === 'folder' && files.length ? `已读取 ${files.length} 份报告` : '自动读取文件夹内的 PDF' }}</span></label>
      </div>
      <div v-if="files.length" class="batch-summary"><span>将识别 <b>{{ files.length }}</b> 份影像报告</span><span v-for="file in files.slice(0, 6)" :key="fileKey(file)">{{ file.name }}</span><span v-if="files.length > 6">…</span></div>
      <div class="action-row"><button class="primary-button" type="button" :disabled="!canProcess" @click="processReports">开始影像识别</button><button class="secondary-button" type="button" :disabled="processing" @click="clearAll">清空</button></div>
      <div v-if="processing" class="progress-panel"><div class="progress-label"><strong>正在识别影像报告</strong><span>{{ progress.completed }}/{{ progress.total }}</span></div><div class="progress-track"><div class="progress-bar" :style="{ width: progressPercent + '%' }"></div></div><p>{{ progress.currentFile || '正在准备任务…' }}</p></div>
      <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>
      <p v-if="successMessage" class="success-message">{{ successMessage }}</p>
    </section>

    <section v-if="records.length" class="card people-card">
      <div class="section-title"><div><span class="step">2</span><h2>逐份核对识别结果</h2></div><span :class="['imaging-review-summary', { clear: reviewRecordCount === 0 }]">{{ reviewRecordCount ? `${reviewRecordCount} 份待核对` : '字段完整' }}</span></div>
      <p class="hint">黄色记录存在缺失或格式不完整字段。扫描件右侧被裁切时，系统会保留可见日期并提示核对，不会猜测缺失数字。</p>
      <div class="review-layout imaging-review">
        <aside class="person-list">
          <button v-for="record in records" :key="record.id" type="button" :class="['person-item', { active: selectedRecordId === record.id, 'has-review-items': recordNeedsReview(record).length }]" @click="selectedRecordId = record.id">
            <strong>{{ record.fields.姓名 || filenameStem(record.filename) }}</strong>
            <span>{{ record.filename }}</span>
            <span :class="['person-review-count', { clear: !recordNeedsReview(record).length }]">{{ recordNeedsReview(record).length ? `${recordNeedsReview(record).join('、')}待核对` : '6 项字段完整' }}</span>
          </button>
        </aside>
        <div v-if="selectedRecord" class="person-detail imaging-detail">
          <div class="detail-head"><div><h3>{{ selectedRecord.fields.姓名 || filenameStem(selectedRecord.filename) }}</h3><p>{{ selectedRecord.filename }}</p></div><span :class="['match-badge', { warning: recordNeedsReview(selectedRecord).length }]">{{ recordNeedsReview(selectedRecord).length ? `${recordNeedsReview(selectedRecord).length} 项待核对` : '字段完整' }}</span></div>
          <div class="ocr-downloads"><span>OCR 原始结果：</span><a v-if="selectedRecord.raw_files?.excel" :href="selectedRecord.raw_files.excel" download>Excel</a><a v-if="selectedRecord.raw_files?.markdown" :href="selectedRecord.raw_files.markdown" download>Markdown</a><a v-if="selectedRecord.raw_files?.json" :href="selectedRecord.raw_files.json" download>JSON</a><a v-if="selectedRecord.raw_files?.body_text" :href="selectedRecord.raw_files.body_text" download>正文补充 OCR</a></div>
          <p v-for="warning in selectedRecord.warnings || []" :key="warning" class="imaging-ocr-warning">{{ warning }}</p>
          <div class="imaging-fields-grid">
            <label :class="{ 'needs-field-review': !selectedRecord.fields.姓名 }">姓名<input v-model.trim="selectedRecord.fields.姓名" class="value-input" placeholder="未识别，请人工填写" /></label>
            <label :class="{ 'needs-field-review': !selectedRecord.fields.性别 }">性别<select v-model="selectedRecord.fields.性别"><option value="">请选择</option><option value="女">女</option><option value="男">男</option></select></label>
            <label :class="{ 'needs-field-review': !selectedRecord.fields.年龄 }">年龄<input v-model.trim="selectedRecord.fields.年龄" class="value-input" inputmode="numeric" placeholder="未识别" /></label>
            <label :class="{ 'needs-field-review': needsDateReview(selectedRecord.fields.检查时间) }">检查时间<input v-model.trim="selectedRecord.fields.检查时间" class="value-input" placeholder="YYYY-MM-DD；不完整时请核对原件" /><small v-if="needsDateReview(selectedRecord.fields.检查时间)">日期为空或不是有效完整日期</small></label>
          </div>
          <label :class="['imaging-text-field', { 'needs-field-review': !selectedRecord.fields.超声所见 }]">超声所见<textarea v-model.trim="selectedRecord.fields.超声所见" placeholder="未识别，请对照原件补充"></textarea></label>
          <label :class="['imaging-text-field', { 'needs-field-review': !selectedRecord.fields.超声诊断 }]">超声诊断<textarea v-model.trim="selectedRecord.fields.超声诊断" placeholder="未识别，请对照原件补充"></textarea></label>
        </div>
      </div>
    </section>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'

const storageKey = 'medical-ocr-api-url'
const serverUrl = ref(localStorage.getItem(storageKey) || '')
const processingMode = ref(localStorage.getItem('imaging-processing-mode') || 'accurate')
const settingsOpen = ref(false)
const checkingServer = ref(false)
const serverOk = ref(false)
const serverMessage = ref('')
const files = ref([])
const inputMode = ref('files')
const processing = ref(false)
const saving = ref(false)
const progress = ref({ completed: 0, total: 0, currentFile: '' })
const records = ref([])
const selectedRecordId = ref('')
const lastJobId = ref('')
const errorMessage = ref('')
const successMessage = ref('')

const canProcess = computed(() => !!(serverUrl.value.trim() && files.value.length && !processing.value))
const progressPercent = computed(() => progress.value.total ? Math.round(progress.value.completed / progress.value.total * 100) : 0)
const selectedRecord = computed(() => records.value.find((record) => record.id === selectedRecordId.value) || records.value[0])
const reviewRecordCount = computed(() => records.value.filter((record) => recordNeedsReview(record).length).length)

function filenameStem(filename) { return String(filename || '').replace(/\.pdf$/i, '') }
function fileKey(file) { return file.webkitRelativePath || file.name }
function validDate(value) { const match = String(value || '').trim().match(/^(20\d{2})-(\d{2})-(\d{2})$/); if (!match) return false; const date = new Date(`${match[1]}-${match[2]}-${match[3]}T00:00:00`); return !Number.isNaN(date.getTime()) && date.getFullYear() === Number(match[1]) && date.getMonth() + 1 === Number(match[2]) && date.getDate() === Number(match[3]) }
function needsDateReview(value) { return !validDate(value) }
function recordNeedsReview(record) { const fields = record?.fields || {}; const missing = ['姓名', '性别', '年龄', '超声所见', '超声诊断'].filter((key) => !String(fields[key] || '').trim()); if (needsDateReview(fields.检查时间)) missing.push('检查时间'); return missing }
function setFiles(fileList, mode) { files.value = Array.from(fileList || []).filter((file) => /\.pdf$/i.test(file.name)); inputMode.value = mode; records.value = []; selectedRecordId.value = ''; errorMessage.value = ''; successMessage.value = '' }
function selectFiles(event) { setFiles(event.target.files, 'files') }
function selectFolder(event) { setFiles(event.target.files, 'folder') }
function saveSettings() { localStorage.setItem(storageKey, serverUrl.value.trim()); localStorage.setItem('imaging-processing-mode', processingMode.value); settingsOpen.value = false; serverOk.value = true }
function clearAll() { files.value = []; records.value = []; selectedRecordId.value = ''; lastJobId.value = ''; errorMessage.value = ''; successMessage.value = ''; progress.value = { completed: 0, total: 0, currentFile: '' } }
async function ensureLocalFeature() {
  try { const response = await fetch('/local-api/'); const data = await response.json(); if (!response.ok || !Array.isArray(data.features) || !data.features.includes('imaging')) throw new Error('本地后端仍是旧版本，请停止旧进程后重新运行 npm run backend') }
  catch (error) { if (String(error.message || '').includes('旧版本')) throw error; throw new Error('无法连接本地后端，请确认已重新运行 npm run backend') }
}

async function testOcr() {
  checkingServer.value = true; serverMessage.value = ''
  try { const body = new FormData(); body.append('ocr_url', serverUrl.value); const response = await fetch('/local-api/test-ocr', { method: 'POST', body }); const data = await response.json(); if (!response.ok) throw new Error(data.detail || '服务不可用'); serverOk.value = true; serverMessage.value = data.message }
  catch (error) { serverOk.value = false; serverMessage.value = `连接失败：${error.message}` }
  finally { checkingServer.value = false }
}

async function processReports() {
  processing.value = true; errorMessage.value = ''; successMessage.value = ''; records.value = []; progress.value = { completed: 0, total: files.value.length, currentFile: '' }
  try {
    await ensureLocalFeature()
    saveSettings()
    const body = new FormData(); body.append('ocr_url', serverUrl.value.trim()); body.append('processing_mode', processingMode.value); files.value.forEach((file) => body.append('files', file))
    const response = await fetch('/local-api/imaging/process', { method: 'POST', body }); const data = await response.json(); if (!response.ok || !data.success) throw new Error(data.detail || '任务创建失败')
    lastJobId.value = data.job_id; await pollJob(data.job_id)
  } catch (error) { errorMessage.value = error.message || '影像识别失败'; processing.value = false }
}

async function pollJob(jobId) {
  const response = await fetch(`/local-api/jobs/${jobId}`); const data = await response.json(); if (!response.ok) throw new Error(data.detail || '无法读取任务进度')
  progress.value = { completed: data.completed_files || 0, total: data.total_files || 0, currentFile: data.current_file || '' }
  if (data.status === 'completed') { records.value = data.records || []; selectedRecordId.value = records.value[0]?.id || ''; successMessage.value = data.message; processing.value = false; return }
  if (data.status === 'failed') throw new Error(data.message || '影像 OCR 任务失败')
  window.setTimeout(() => pollJob(jobId).catch((error) => { errorMessage.value = error.message; processing.value = false }), 700)
}

async function saveAndDownload() {
  saving.value = true; errorMessage.value = ''
  try {
    const response = await fetch(`/local-api/imaging/jobs/${lastJobId.value}/save-review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ records: records.value }) })
    const data = await response.json(); if (!response.ok || !data.success) throw new Error(data.detail || '保存失败'); records.value = data.records || records.value; successMessage.value = data.message; window.location.assign(data.output_url)
  } catch (error) { errorMessage.value = error.message || '保存影像核对结果失败' }
  finally { saving.value = false }
}
</script>
