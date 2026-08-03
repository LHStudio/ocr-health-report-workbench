<template>
  <section class="card service-card">
    <div class="section-title"><div><span class="step">1</span><h2>云端 OCR 服务</h2></div><button class="text-button" type="button" @click="saveUrl">保存地址</button></div>
    <div class="input-row"><input v-model.trim="serverUrl" class="text-input" placeholder="https://your-host:8443 或完整 /parse-file 地址" /><button class="secondary-button" :disabled="testing || !serverUrl" @click="testOcr">{{ testing ? '检查中…' : '测试连接' }}</button></div>
    <div class="recognition-options">
      <label class="parse-mode">识别结果解析来源 <select v-model="parseMode" @change="saveParseMode"><option value="markdown">Markdown（推荐：保留勾选列）</option><option value="excel">Excel</option></select></label>
      <label class="parse-mode">识别速度 <select v-model="processingMode" @change="saveProcessingMode"><option value="fast">快速模式（推荐）</option><option value="accurate">精确模式（较慢）</option></select></label>
    </div>
    <p class="mode-help">两种模式都保留 OpenCV 勾选检测。快速模式只在每名受访者的第一页补做姓名 OCR；精确模式会检查更多可能包含姓名或签字的页面。</p>
    <p v-if="serverMessage" :class="['server-state', serverOk ? 'ok' : 'error']">{{ serverMessage }}</p>
  </section>

  <section class="card">
    <div class="section-title"><div><span class="step">2</span><h2>选择食物频率调查报告</h2></div><a class="text-button" href="/local-api/nutrition-template" download>下载默认模板</a></div>
    <p class="hint">可上传你自己的 Excel 模板；未上传时使用系统默认的“人员汇总、食物频率明细、营养保健品”模板。可直接选择 PDF，或选择包含每名受访者子文件夹的根目录。</p>
    <div class="nutrition-config"><label>汇总模板（可选）<input type="file" accept=".xlsx,.xlsm" @change="selectTemplate" /><span>{{ templateFile?.name || '未上传，使用默认模板' }}</span></label></div>
    <div class="upload-actions">
      <label class="drop-zone compact" :class="{ ready: nutritionFiles.length && mode === 'files' }"><input type="file" accept=".pdf,application/pdf" multiple @change="selectFiles" /><strong>直接选择 PDF</strong><span>{{ mode === 'files' && nutritionFiles.length ? `已选 ${nutritionFiles.length} 份，每份单独处理` : '支持单份或多份问卷' }}</span></label>
      <label class="drop-zone compact" :class="{ ready: nutritionFiles.length && mode === 'folder' }"><input type="file" accept=".pdf,application/pdf" multiple webkitdirectory directory @change="selectFolder" /><strong>选择问卷文件夹</strong><span>{{ mode === 'folder' && nutritionFiles.length ? `已读取 ${nutritionFiles.length} 份 PDF` : '每个子文件夹自动对应一名受访者' }}</span></label>
    </div>
    <div class="nutrition-config body-composition-upload"><label>体成分报告（可选）<input type="file" accept=".pdf,application/pdf" multiple webkitdirectory directory @change="selectBodyCompositionFiles" /><span>{{ bodyCompositionFiles.length ? `已读取 ${bodyCompositionFiles.length} 份，将按姓名提取去脂体重（瘦体重）并合并` : '可选择 InBody 等体成分报告文件夹' }}</span></label></div>
    <div v-if="nutritionFiles.length" class="batch-summary"><span>将处理 <b>{{ personFolders.length }}</b> 名受访者 / <b>{{ nutritionFiles.length }}</b> 个 PDF</span><span v-for="folder in personFolders.slice(0, 6)" :key="folder">{{ folder }}</span></div>
    <div class="action-row"><button class="primary-button" :disabled="!canProcess" @click="process">开始识别并生成食物频率汇总</button><button class="secondary-button" :disabled="processing" @click="clear">清空</button></div>
    <div v-if="processing" class="progress-panel"><div class="progress-label"><strong>正在处理第 {{ Math.min(progress.completed + 1, progress.total) }}/{{ progress.total }} 个 PDF</strong><span>{{ progress.completed }}/{{ progress.total }}</span></div><div class="progress-track"><div class="progress-bar" :style="{ width: `${progressPercent}%` }"></div></div><p>{{ progress.currentFile || '正在准备任务…' }}</p></div>
    <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p><p v-if="successMessage" class="success-message">{{ successMessage }}</p>
  </section>

  <section v-if="people.length" class="card people-card">
    <div class="section-title"><div><span class="step">3</span><h2>逐人核对食物与勾选信息</h2></div><button class="primary-button" :disabled="saving" @click="save">{{ saving ? '正在保存…' : '保存人工修改并下载 Excel' }}</button></div>
    <p class="hint">OCR 未能可靠识别手写勾选的位置时，“频率周期”和就餐/日照选项会保持空白；请在此补充。“不吃”由频率周期自动确定，已选择每天/每周等频率时保持空白。</p>
    <div class="review-layout nutrition-review">
      <aside class="person-list"><button v-for="person in people" :key="person.id" type="button" :class="['person-item', { active: selectedId === person.id, 'has-review-items': personReviewCount(person) > 0 }]" @click="selectPerson(person)"><strong>{{ person.general.姓名 || person.id }}</strong><span>{{ person.id }} · {{ person.page_count || person.ocr_files.length }} 页 · {{ person.food_rows.length }} 类食物</span><span :class="['person-review-count', { clear: personReviewCount(person) === 0 }]">需核对 {{ personReviewCount(person) }} 项</span></button></aside>
      <div v-if="selected" class="person-detail">
        <div class="detail-head"><div><h3>{{ selected.general.姓名 || selected.id }}</h3><p>{{ selected.id }}：请核对 OCR 数据、频率周期和纸质问卷上的勾选项。</p></div></div>
          <div class="ocr-downloads"><span>OCR 原始结果：</span><a v-for="(file, index) in selected.ocr_files" :key="file" :href="file" download>第 {{ index + 1 }} 页 Excel</a><a v-for="(file, index) in selected.markdown_files || []" :key="file" :href="file" download>第 {{ index + 1 }} 页 Markdown</a></div>
        <section class="nutrition-report-launch">
          <div><h4>营养评价与报告</h4><p>打开独立复核窗口，可查看或修改机器初稿、人工评价和评语，并直接导出。</p></div>
          <button class="primary-button" type="button" @click="openNutritionReview">导出营养评价</button>
        </section>
        <section v-if="nutritionReviewOpen" class="nutrition-dialog-backdrop" @click.self="closeNutritionReview">
          <section class="nutrition-report-panel nutrition-report-dialog" role="dialog" aria-modal="true" aria-labelledby="nutrition-report-title">
          <div class="subsection-title"><div><h4 id="nutrition-report-title">营养报告导出</h4><p>报告文件在本机生成；食物营养值优先查询独立云端营养库，无法访问时自动使用本地营养库。年龄、性别和活动量会影响能量评价。</p></div><button class="dialog-close" type="button" aria-label="关闭营养评价窗口" @click="closeNutritionReview">×</button></div>
          <div class="general-grid report-profile-grid">
            <label>姓名<input v-model="reportProfile.name" class="value-input" placeholder="姓名（可选）" /></label>
            <label>年龄<input v-model="reportProfile.age" class="value-input" inputmode="numeric" placeholder="岁（可选）" /></label>
            <label>项目种类<input v-model="reportProfile.projectType" class="value-input" placeholder="例如：女足（可选）" /></label>
            <label>训练年限<input v-model="reportProfile.trainingYears" class="value-input" placeholder="例如：5年（可选）" /></label>
            <label>当前状态<input v-model="reportProfile.currentStatus" class="value-input" placeholder="例如：正常训练（可选）" /></label>
            <label>性别<select v-model="reportProfile.gender"><option value="">未填写</option><option value="female">女</option><option value="male">男</option></select></label>
            <label>身高<input v-model="reportProfile.height" class="value-input" inputmode="decimal" placeholder="cm（可选）" /></label>
            <label>体重<input v-model="reportProfile.weight" class="value-input" inputmode="decimal" placeholder="kg（可选）" /></label>
            <label>去脂体重（瘦体重）<input v-model="reportProfile.fatFreeMass" class="value-input" inputmode="decimal" placeholder="kg（可选）" /></label>
            <label>活动量<select v-model="reportProfile.activityLevel"><option value="">未填写</option><option value="1">低</option><option value="2">中</option><option value="3">高</option></select></label>
          </div>
          <div class="nutrition-preview-panel" aria-label="营养摄入即时预览">
            <div class="nutrition-preview-head"><div><h5>即时计算结果</h5><p>随人员信息和食物核对数据自动更新。</p></div><span v-if="previewLoading">计算中…</span><span v-else>{{ previewUsableFoodCount }} 项食物已计入</span></div>
            <p v-if="previewError" class="error-message preview-message">{{ previewError }}</p>
            <p v-if="nutritionDataSource.message" :class="['nutrition-source-status', nutritionDataSource.kind]">
              <strong>{{ nutritionDataSource.message }}</strong>
              <span v-if="nutritionDataSource.queried_at">查询时间：{{ formatSourceTime(nutritionDataSource.queried_at) }}</span>
              <span v-if="nutritionDataSource.error" :title="nutritionDataSource.error">原因：{{ nutritionDataSource.error }}</span>
            </p>
            <div class="nutrition-preview-grid">
              <div class="preview-metric"><span>BMI</span><strong>{{ bmiValue || '—' }}</strong><small>{{ bmiStatus || '填写身高和体重后显示' }}</small></div>
              <div class="preview-metric"><span>当前能量摄入</span><strong>{{ nutritionPreview?.nutrition?.energy?.value ?? '—' }}</strong><small>kcal/天</small></div>
              <div class="preview-metric"><span>推荐能量</span><strong>{{ nutritionPreview?.nutrition?.energy?.standard ?? '—' }}</strong><small>{{ energyStandardNote }}</small></div>
              <div class="preview-metric"><span>蛋白质</span><strong>{{ nutritionPreview?.nutrition?.protein ?? '—' }}</strong><small>g/天</small></div>
              <div class="preview-metric"><span>脂肪</span><strong>{{ nutritionPreview?.nutrition?.fat ?? '—' }}</strong><small>g/天</small></div>
              <div class="preview-metric"><span>碳水化合物</span><strong>{{ nutritionPreview?.nutrition?.carbohydrate ?? '—' }}</strong><small>g/天</small></div>
              <div class="preview-metric"><span>钙</span><strong>{{ nutritionPreview?.nutrition?.calcium?.value ?? '—' }}</strong><small>mg/天</small></div>
            </div>
          </div>
          <section class="nutrition-evaluation-review" aria-label="营养评价人工复核">
            <div class="subsection-title"><div><h4>营养评价人工复核</h4><p>机器评价仅作初稿。请按实际情况逐项选择偏少、适中、偏多或其他自定义评价，并编辑最终建议和解读。</p></div><div class="review-header-actions"><button class="secondary-button mini-button" type="button" :disabled="!nutritionPreview" @click="resetReportReviewFromMachine">重载机器初稿</button></div></div>
            <p v-if="!nutritionPreview || previewLoading" class="hint">正在计算机器初稿，完成后可复核。</p>
            <template v-else>
              <div class="mapping-wrap"><table class="mapping-table nutrition-evaluation-table"><thead><tr><th>项目</th><th>当前摄入</th><th>机器初稿</th><th>人工最终评价</th></tr></thead><tbody>
                <tr v-for="row in categoryReviewRows" :key="row.key"><td>{{ row.label }}</td><td>{{ row.value }} g/天</td><td>{{ row.machineEvaluation || '—' }}</td><td><div class="evaluation-control"><select :value="evaluationSelection(reportReview.categoryEvaluations[row.key], `category:${row.key}`)" class="evaluation-select" @change="setEvaluation('category', row.key, $event.target.value)"><option value="">—（不计算）</option><option value="偏少">偏少</option><option value="适中">适中</option><option value="偏多">偏多</option><option value="other">其他（手动填写）</option></select><input v-if="isManualEvaluation(reportReview.categoryEvaluations[row.key], `category:${row.key}`)" v-model="reportReview.categoryEvaluations[row.key]" class="cell-input manual-evaluation-input" placeholder="请输入其他评价" /></div></td></tr>
                <tr v-for="row in nutrientReviewRows" :key="row.key"><td>{{ row.label }}</td><td>{{ row.value }} {{ row.unit }}</td><td>{{ row.machineEvaluation || '—' }}</td><td><div class="evaluation-control"><select :value="evaluationSelection(reportReview[row.key], `nutrition:${row.key}`)" class="evaluation-select" @change="setEvaluation('nutrition', row.key, $event.target.value)"><option value="">—（不计算）</option><option value="偏少">偏少</option><option value="适中">适中</option><option value="偏多">偏多</option><option value="other">其他（手动填写）</option></select><input v-if="isManualEvaluation(reportReview[row.key], `nutrition:${row.key}`)" v-model="reportReview[row.key]" class="cell-input manual-evaluation-input" placeholder="请输入其他评价" /></div></td></tr>
              </tbody></table></div>
              <div class="report-review-textareas"><label>总体建议（可修改机器初稿）<textarea v-model="reportReview.overallSuggestions" rows="8" placeholder="每行一条建议"></textarea></label><label>最终总结 / 报告解读（可修改机器初稿）<textarea v-model="reportReview.interpretation" rows="8" placeholder="请输入最终总结或解读"></textarea></label></div>
              <p class="nutrition-disclaimer-preview">报告将注明：以上营养成分仅根据记录饮食计算，不包含维生素、矿物质、蛋白粉等其他补充剂摄入。</p>
            </template>
          </section>
          <div class="action-row report-actions"><button class="primary-button" :disabled="reportGenerating !== '' || !canExportReviewedReport" @click="generateReport('pdf')">{{ reportGenerating === 'pdf' ? '正在生成 PDF…' : '导出营养 PDF 报告' }}</button><button class="secondary-button" :disabled="reportGenerating !== '' || !canExportReviewedReport" @click="generateReport('excel')">{{ reportGenerating === 'excel' ? '正在生成 Excel…' : '导出营养分析 Excel' }}</button></div>
          <p v-if="!canExportReviewedReport" class="hint">请等待机器初稿计算完成后再导出。</p>
          <p v-if="reportErrorMessage" class="error-message report-message">{{ reportErrorMessage }}</p><p v-if="reportSuccessMessage" class="success-message report-message">{{ reportSuccessMessage }}</p>
          </section>
        </section>
        <h4>人员与问卷信息</h4>
        <div class="general-grid"><label v-for="(value, key) in selected.general" :key="key">{{ key }}<input v-model="selected.general[key]" class="value-input" :placeholder="key.includes('地点') || key.includes('时段') || key.includes('部位') ? '请根据勾选补充' : ''" /></label></div>
        <section v-if="checkboxReview.length" class="checkbox-review-panel" aria-label="纸质勾选识别核对">
          <div class="checkbox-review-head"><div><h4>纸质勾选识别核对</h4><p>点击“已选 / 未选 / 不确定”即可人工修改；设为已选后会同步更新上方对应餐次，保存时写入 Excel。</p></div><span>{{ checkboxReview.length }} 项</span></div>
          <div class="checkbox-review-grid">
            <div v-for="item in checkboxReview" :key="item.key" :class="['checkbox-review-item', item.stateClass]">
              <div class="checkbox-review-name"><strong>{{ item.meal }}</strong><span>{{ item.option }}</span></div>
              <span :class="['checkbox-review-status', item.stateClass]">{{ item.stateLabel }}</span>
              <span class="checkbox-review-confidence">自动置信度 {{ item.confidenceLabel }}<template v-if="item.source.manual_override"> · 已人工修改</template></span>
              <div class="checkbox-review-actions" :aria-label="`${item.meal}-${item.option}人工复核`">
                <button type="button" :class="{ active: item.source.selected === true }" @click="setCheckboxState(item, true)">已选</button>
                <button type="button" :class="{ active: item.source.selected === false }" @click="setCheckboxState(item, false)">未选</button>
                <button type="button" :class="{ active: item.source.selected == null }" @click="setCheckboxState(item, null)">不确定</button>
              </div>
            </div>
          </div>
        </section>
        <div class="subsection-title"><h4>食物频率明细</h4><button class="secondary-button mini-button" @click="addFood">添加食物</button></div>
        <div class="mapping-wrap"><table class="mapping-table nutrition-table"><thead><tr><th>食物</th><th>每次量</th><th>次数</th><th>频率周期</th><th>不吃</th><th>备注</th></tr></thead><tbody><tr v-for="(row, index) in selected.food_rows" :key="`${row.食物编号}-${index}`" :class="{ 'needs-review-row': foodRowNeedsReview(row) }" :title="foodRowReviewReason(row)"><td><input v-model="row.食物名称" class="cell-input" /></td><td><input v-model="row.平均每次食用量" class="cell-input" /></td><td><input v-model="row.次数" class="cell-input" /></td><td><select v-model="row['频率周期(请核对)']" @change="syncNotEat(row)"><option value="">原件空白</option><option value="未识别">未识别</option><option value="每天">每天</option><option value="每周">每周</option><option value="每月">每月</option><option value="每年">每年</option><option value="不吃">不吃（次数归零）</option></select></td><td>{{ row.是否不吃 || '—' }}</td><td><input v-model="row.人工核对备注" class="cell-input" /></td></tr></tbody></table></div>
        <div class="subsection-title"><h4>营养保健品</h4><button class="secondary-button mini-button" @click="addSupplement">添加保健品</button></div>
        <div class="mapping-wrap"><table class="mapping-table nutrition-table"><thead><tr><th>种类</th><th>名称</th><th>每次量</th><th>次数</th><th>频率周期</th><th>不吃</th><th>备注</th></tr></thead><tbody><tr v-for="(row, index) in selected.supplement_rows" :key="`${row.保健品种类}-${index}`" :class="{ 'needs-review-row': supplementRowNeedsReview(row) }" :title="supplementRowReviewReason(row)"><td><input v-model="row.保健品种类" class="cell-input" /></td><td><input v-model="row.保健品名称" class="cell-input" /></td><td><input v-model="row.平均每次服用量" class="cell-input" /></td><td><input v-model="row.次数" class="cell-input" /></td><td><select v-model="row['频率周期(请核对)']" @change="syncNotEat(row)"><option value="">原件空白</option><option value="未识别">未识别</option><option value="每天">每天</option><option value="每周">每周</option><option value="每月">每月</option><option value="每年">每年</option><option value="不吃">不吃（次数归零）</option></select></td><td>{{ row.是否不吃 || '—' }}</td><td><input v-model="row.备注" class="cell-input" /></td></tr></tbody></table></div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'

const serverUrl = ref(localStorage.getItem('medical-ocr-api-url') || '')
const serverMessage = ref(''); const serverOk = ref(false); const testing = ref(false)
const nutritionFiles = ref([]); const bodyCompositionFiles = ref([]); const mode = ref('folder'); const templateFile = ref(null); const parseMode = ref(localStorage.getItem('ocr-parse-mode') || 'markdown'); const processingMode = ref(localStorage.getItem('ocr-processing-mode') || 'fast'); const processing = ref(false); const saving = ref(false)
const progress = ref({ completed: 0, total: 0, currentFile: '' }); const errorMessage = ref(''); const successMessage = ref('')
const people = ref([]); const selectedId = ref(''); const jobId = ref('')
const reportGenerating = ref(''); const reportProfiles = ref({}); const reportProfile = ref(emptyReportProfile()); const reportReviews = ref({}); const reportReview = ref(emptyReportReview())
const nutritionPreview = ref(null); const previewLoading = ref(false); const previewError = ref(''); const previewUsableFoodCount = ref(0)
const reportErrorMessage = ref(''); const reportSuccessMessage = ref('')
const nutritionReviewOpen = ref(false)
const canProcess = computed(() => !!(serverUrl.value && nutritionFiles.value.length && !processing.value))
const personFolders = computed(() => [...new Set(nutritionFiles.value.map(folderFor))].sort((a, b) => a.localeCompare(b, 'zh-CN')))
const selected = computed(() => people.value.find((person) => person.id === selectedId.value) || people.value[0])
const bmiValue = computed(() => { const height = Number(reportProfile.value.height); const weight = Number(reportProfile.value.weight); if (!(height > 0 && weight > 0)) return ''; return (weight / ((height / 100) ** 2)).toFixed(1) })
const bmiStatus = computed(() => { const bmi = Number(bmiValue.value); if (!bmi) return ''; if (bmi < 18.5) return '偏瘦'; if (bmi < 24) return '正常'; if (bmi < 28) return '超重'; return '肥胖' })
const energyStandardNote = computed(() => { const standard = nutritionPreview.value?.nutrition?.energy?.standard; if (standard) return 'kcal/天'; if (reportProfile.value.gender === 'male') return '当前迁移的 EER 表仅含女性标准'; return '补全年龄、性别和活动量后显示' })
const nutritionDataSource = computed(() => nutritionPreview.value?.food_data_source || {})
const categoryReviewRows = computed(() => Object.entries(nutritionPreview.value?.category_result || {}).map(([key, info]) => ({ key, label: key, value: info?.value ?? 0, machineEvaluation: machineEvaluationText(info?.evaluation) })))
const nutrientReviewRows = computed(() => {
  const nutrition = nutritionPreview.value?.nutrition || {}
  return [
    { key: 'energyEvaluation', label: '总能量', value: nutrition.energy?.value ?? '—', unit: 'kcal/天', machineEvaluation: machineEvaluationText(nutrition.energy?.evaluation) },
    { key: 'calciumEvaluation', label: '钙', value: nutrition.calcium?.value ?? '—', unit: 'mg/天', machineEvaluation: machineEvaluationText(nutrition.calcium?.evaluation) },
  ]
})
const canExportReviewedReport = computed(() => !!(selected.value && nutritionPreview.value && !previewLoading.value))
const checkboxReview = computed(() => {
  const items = Array.isArray(selected.value?.checkbox_review) ? selected.value.checkbox_review : []
  return items.filter((item) => item && typeof item === 'object').map((item, index) => {
    const explicitMeal = String(item.meal_label || item.question_label || item.question || '').trim()
    const explicitOption = String(item.option_label || item.option || '').trim()
    const rawLabel = String(item.label || '').trim()
    const labelParts = rawLabel.split(/[-－—]/).map((part) => part.trim()).filter(Boolean)
    const meal = explicitMeal || labelParts[0] || '勾选项'
    const option = explicitOption || labelParts.slice(1).join('-') || (explicitMeal ? rawLabel : '') || '未命名选项'
    const stateLabel = item.selected === true ? '已选' : item.selected === false ? '未选' : '不确定'
    const stateClass = item.selected === true ? 'is-selected' : item.selected === false ? 'is-unselected' : 'is-uncertain'
    const confidence = Number(item.confidence)
    const confidenceLabel = Number.isFinite(confidence) ? `${Math.round(Math.max(0, Math.min(100, confidence <= 1 ? confidence * 100 : confidence)))}%` : '—'
    return { key: `${rawLabel || meal}-${index}`, meal, option, stateLabel, stateClass, confidenceLabel, multiSelect: item.multi_select === true, source: item }
  })
})
const progressPercent = computed(() => progress.value.total ? Math.round(progress.value.completed / progress.value.total * 100) : 0)
function folderFor(file) { if (mode.value === 'files') return file.name.replace(/\.pdf$/i, ''); const parts = (file.webkitRelativePath || file.name).split('/').filter(Boolean); return parts.length > 1 ? parts.slice(0, -1).join('/') : file.name.replace(/\.pdf$/i, '') }
function saveUrl() { localStorage.setItem('medical-ocr-api-url', serverUrl.value); serverOk.value = true; serverMessage.value = '云端地址已保存。' }
function saveParseMode() { localStorage.setItem('ocr-parse-mode', parseMode.value) }
function saveProcessingMode() { localStorage.setItem('ocr-processing-mode', processingMode.value) }
function selectTemplate(event) { templateFile.value = event.target.files?.[0] || null }
function setFiles(files, nextMode) { mode.value = nextMode; nutritionFiles.value = Array.from(files || []).filter((file) => /\.pdf$/i.test(file.name)); errorMessage.value = ''; successMessage.value = '' }
function selectFiles(event) { setFiles(event.target.files, 'files') }
function selectFolder(event) { setFiles(event.target.files, 'folder') }
function selectBodyCompositionFiles(event) { bodyCompositionFiles.value = Array.from(event.target.files || []).filter((file) => /\.pdf$/i.test(file.name)); errorMessage.value = ''; successMessage.value = '' }
function emptyReportProfile() { return { name: '', age: '', projectType: '', trainingYears: '', currentStatus: '', gender: '', height: '', weight: '', fatFreeMass: '', activityLevel: '' } }
function emptyReportReview() { return { categoryEvaluations: {}, energyEvaluation: '', calciumEvaluation: '', overallSuggestions: '', interpretation: '', machineSeeded: false, manualEntryFields: {} } }
function copyReportReview(review) { return { ...emptyReportReview(), ...(review || {}), categoryEvaluations: { ...(review?.categoryEvaluations || {}) }, manualEntryFields: { ...(review?.manualEntryFields || {}) } } }
function machineEvaluationText(value) { const text = String(value || '').trim(); if (text === '不足') return '偏少'; if (text === '偏高') return '偏多'; if (text === '适宜') return '适中'; return '' }
function machineInterpretation(preview) {
  const nutrition = preview?.nutrition || {}; const lines = []
  if (nutrition.energy?.evaluation === '不足') lines.push('能量摄入偏少，建议结合训练量补充主食等碳水化合物来源。')
  else if (nutrition.energy?.evaluation === '偏高') lines.push('能量摄入偏多，建议结合训练量调整总能量摄入。')
  if (nutrition.calcium?.evaluation === '不足') lines.push('钙摄入偏少，建议优先从奶类、豆制品等食物补充。')
  return lines.join('\n') || '请结合受访者训练、疾病和补充剂使用情况进行最终解读。'
}
function seedReportReviewFromPreview() {
  if (!selected.value || !nutritionPreview.value || reportReview.value.machineSeeded) return
  const preview = nutritionPreview.value; const categoryEvaluations = {}
  Object.entries(preview.category_result || {}).forEach(([category, info]) => { categoryEvaluations[category] = machineEvaluationText(info?.evaluation) })
  reportReview.value = { ...reportReview.value, categoryEvaluations, energyEvaluation: machineEvaluationText(preview.nutrition?.energy?.evaluation), calciumEvaluation: machineEvaluationText(preview.nutrition?.calcium?.evaluation), overallSuggestions: (preview.suggestions || []).join('\n') || '请结合实际饮食、训练与健康状况给出建议。', interpretation: machineInterpretation(preview), machineSeeded: true }
  reportReviews.value[selected.value.id] = copyReportReview(reportReview.value)
}
function resetReportReviewFromMachine() { reportReview.value = emptyReportReview(); seedReportReviewFromPreview() }
function evaluationSelection(value, fieldKey) { const text = String(value || '').trim(); if (reportReview.value.manualEntryFields?.[fieldKey] || (text && !['偏少', '适中', '偏多'].includes(text))) return 'other'; return text }
function isManualEvaluation(value, fieldKey) { return evaluationSelection(value, fieldKey) === 'other' }
function setEvaluation(kind, key, selection) {
  const fieldKey = `${kind === 'category' ? 'category' : 'nutrition'}:${key}`
  const target = kind === 'category' ? reportReview.value.categoryEvaluations : reportReview.value
  if (selection === 'other') {
    reportReview.value.manualEntryFields[fieldKey] = true
    if (['偏少', '适中', '偏多'].includes(String(target[key] || '').trim())) target[key] = ''
    return
  }
  delete reportReview.value.manualEntryFields[fieldKey]
  target[key] = selection
}
function manualEvaluationsPayload() { return { categoryEvaluations: { ...reportReview.value.categoryEvaluations }, energyEvaluation: String(reportReview.value.energyEvaluation || '').trim(), calciumEvaluation: String(reportReview.value.calciumEvaluation || '').trim(), overallSuggestions: String(reportReview.value.overallSuggestions || '').trim(), interpretation: String(reportReview.value.interpretation || '').trim() } }
function openNutritionReview() { reportErrorMessage.value = ''; reportSuccessMessage.value = ''; nutritionReviewOpen.value = true; scheduleNutritionPreview() }
function closeNutritionReview() { nutritionReviewOpen.value = false }
function formatSourceTime(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value || '') : date.toLocaleString('zh-CN', { hour12: false }) }
function genderForReport(value) { const text = String(value || '').trim().toLowerCase(); return ['女', '女性', 'female', 'f'].includes(text) ? 'female' : ['男', '男性', 'male', 'm'].includes(text) ? 'male' : '' }
function selectPerson(person) {
  if (selectedId.value) { reportProfiles.value[selectedId.value] = { ...reportProfile.value }; reportReviews.value[selectedId.value] = copyReportReview(reportReview.value) }
  selectedId.value = person.id
  reportProfile.value = { ...(reportProfiles.value[person.id] || { name: person.general?.姓名 || '', age: person.general?.年龄 || '', projectType: person.general?.项目种类 || '', trainingYears: person.general?.训练年限 || '', currentStatus: person.general?.当前状态 || '', gender: genderForReport(person.general?.性别), height: person.general?.身高 || '', weight: person.general?.体重 || '', fatFreeMass: person.general?.去脂体重 || '', activityLevel: person.general?.运动量 || '' }) }
  reportReview.value = copyReportReview(reportReviews.value[person.id])
  nutritionPreview.value = null
  scheduleNutritionPreview()
}
function clear() { nutritionFiles.value = []; bodyCompositionFiles.value = []; people.value = []; selectedId.value = ''; errorMessage.value = ''; successMessage.value = ''; reportProfiles.value = {}; reportProfile.value = emptyReportProfile(); reportReviews.value = {}; reportReview.value = emptyReportReview(); nutritionPreview.value = null; nutritionReviewOpen.value = false; previewError.value = ''; reportErrorMessage.value = ''; reportSuccessMessage.value = '' }
function hasText(value) { return String(value ?? '').trim().length > 0 }
function actionableFoodNote(value) { return String(value ?? '').split('；').map((part) => part.trim()).filter(Boolean).some((part) => !part.startsWith('OCR项目原文：')) }
function rowNeedsReview(row, noteKey) { return String(row?.['频率周期(请核对)'] ?? '').trim() === '未识别' || hasText(row?.[noteKey]) }
function foodRowNeedsReview(row) { return String(row?.['频率周期(请核对)'] ?? '').trim() === '未识别' || actionableFoodNote(row?.人工核对备注) }
function foodRowReviewReason(row) {
  const reasons = []
  if (String(row?.['频率周期(请核对)'] ?? '').trim() === '未识别') reasons.push('频率周期未识别')
  if (actionableFoodNote(row?.人工核对备注)) reasons.push(`风险备注：${row.人工核对备注}`)
  return reasons.length ? `需核对：${reasons.join('；')}` : ''
}
function supplementRowNeedsReview(row) { return rowNeedsReview(row, '备注') }
function supplementRowReviewReason(row) {
  const reasons = []
  if (String(row?.['频率周期(请核对)'] ?? '').trim() === '未识别') reasons.push('频率周期未识别')
  if (hasText(row?.备注)) reasons.push(`风险备注：${row.备注}`)
  return reasons.length ? `需核对：${reasons.join('；')}` : ''
}
function personReviewCount(person) {
  const foodCount = (person?.food_rows || []).filter(foodRowNeedsReview).length
  const supplementCount = (person?.supplement_rows || []).filter(supplementRowNeedsReview).length
  return foodCount + supplementCount
}
async function testOcr() { testing.value = true; try { const form = new FormData(); form.append('ocr_url', serverUrl.value); const r = await fetch('/local-api/test-ocr', { method: 'POST', body: form }); const d = await r.json(); if (!r.ok) throw new Error(d.detail); serverOk.value = true; serverMessage.value = d.message; saveUrl() } catch (e) { serverOk.value = false; serverMessage.value = `连接失败：${e.message}` } finally { testing.value = false } }
async function process() { processing.value = true; errorMessage.value = ''; successMessage.value = ''; people.value = []; reportReviews.value = {}; progress.value = { completed: 0, total: nutritionFiles.value.length + bodyCompositionFiles.value.length, currentFile: '' }; try { saveProcessingMode(); const form = new FormData(); form.append('ocr_url', serverUrl.value); form.append('parse_mode', parseMode.value); form.append('processing_mode', processingMode.value); if (templateFile.value) form.append('template', templateFile.value); nutritionFiles.value.forEach((file) => { form.append('files', file); form.append('relative_paths', mode.value === 'folder' ? (file.webkitRelativePath || file.name) : file.name) }); bodyCompositionFiles.value.forEach((file) => { form.append('body_composition_files', file); form.append('body_composition_relative_paths', file.webkitRelativePath || file.name) }); const r = await fetch('/local-api/nutrition/process', { method: 'POST', body: form }); const d = await r.json(); if (!r.ok || !d.success) throw new Error(d.detail || '任务创建失败'); jobId.value = d.job_id; localStorage.setItem('nutrition-last-job-id', d.job_id); poll() } catch (e) { errorMessage.value = e.message; processing.value = false } }
async function poll() { try { const r = await fetch(`/local-api/jobs/${jobId.value}`); const d = await r.json(); if (!r.ok) throw new Error(d.detail); progress.value = { completed: d.completed_files, total: d.total_files, currentFile: d.current_file }; if (d.status === 'completed') { people.value = d.people; reportProfiles.value = {}; reportReviews.value = {}; selectPerson(d.people[0] || { id: '', general: {} }); successMessage.value = d.message; processing.value = false; return } if (d.status === 'failed') throw new Error(d.message); window.setTimeout(poll, 700) } catch (e) { errorMessage.value = e.message; processing.value = false } }
function addFood() { selected.value.food_rows.push({ 食物编号: '', 食物名称: '', 平均每次食用量: '', 次数: '', '频率周期(请核对)': '未识别', 是否不吃: '', OCR原始行: '', 人工核对备注: '' }) }
function addSupplement() { selected.value.supplement_rows.push({ 保健品种类: '', 保健品名称: '', 平均每次服用量: '', 次数: '', '频率周期(请核对)': '未识别', 是否不吃: '', 备注: '' }) }
function syncNotEat(row) { const period = row['频率周期(请核对)']; const notEat = period === '不吃'; row.是否不吃 = notEat ? '是' : ''; if (notEat) row.次数 = '0'; else if (!period) row.次数 = '' }
function checkboxLabels(item) { const raw = String(item?.label || '').trim().split(/[-－—]/).map((part) => part.trim()).filter(Boolean); return { meal: String(item?.meal_label || item?.question_label || item?.question || raw[0] || '').trim(), option: String(item?.option_label || item?.option || raw.slice(1).join('-') || '').trim() } }
function setCheckboxState(reviewItem, nextState) {
  if (!selected.value || !reviewItem?.source) return
  const source = reviewItem.source
  source.selected = nextState
  source.manual_override = true
  const allItems = Array.isArray(selected.value.checkbox_review) ? selected.value.checkbox_review : []
  if (reviewItem.multiSelect) {
    const selectedOptions = allItems.filter((candidate) => candidate.selected === true && checkboxLabels(candidate).meal === reviewItem.meal).map((candidate) => checkboxLabels(candidate).option).filter(Boolean)
    const uniqueOptions = [...new Set(selectedOptions)]
    if (reviewItem.meal) selected.value.general[reviewItem.meal] = uniqueOptions.join('、')
    return
  }
  if (nextState === true) {
    allItems.forEach((candidate) => {
      if (candidate === source) return
      const labels = checkboxLabels(candidate)
      if (labels.meal === reviewItem.meal && candidate.selected === true) {
        candidate.selected = false
        candidate.manual_override = true
      }
    })
    if (reviewItem.meal) selected.value.general[reviewItem.meal] = reviewItem.option
    return
  }
  const replacement = allItems.find((candidate) => candidate !== source && candidate.selected === true && checkboxLabels(candidate).meal === reviewItem.meal)
  if (replacement) {
    selected.value.general[reviewItem.meal] = checkboxLabels(replacement).option
  } else if (selected.value.general[reviewItem.meal] === reviewItem.option) {
    selected.value.general[reviewItem.meal] = ''
  }
}
async function save() { saving.value = true; try { const r = await fetch(`/local-api/nutrition/jobs/${jobId.value}/save-review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ people: people.value }) }); const d = await r.json(); if (!r.ok || !d.success) throw new Error(d.detail || '保存失败'); successMessage.value = d.message; window.location.assign(d.output_url) } catch (e) { errorMessage.value = e.message } finally { saving.value = false } }
let previewTimer = 0
let previewRequest = 0
function scheduleNutritionPreview() { window.clearTimeout(previewTimer); previewTimer = window.setTimeout(refreshNutritionPreview, 350) }
async function refreshNutritionPreview() {
  if (!selected.value) { nutritionPreview.value = null; return }
  const requestId = ++previewRequest; previewLoading.value = true; previewError.value = ''
  try {
    const response = await fetch('/local-api/nutrition/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ person: selected.value, user_overrides: { ...reportProfile.value, bmi: bmiValue.value }, report_date: selected.value.general?.调查日期 || '' }) })
    const data = await response.json(); if (!response.ok || !data.success) throw new Error(data.detail || '营养摄入计算失败')
    if (requestId !== previewRequest) return
    nutritionPreview.value = data.preview; previewUsableFoodCount.value = data.usable_food_count || 0
    seedReportReviewFromPreview()
  } catch (error) { if (requestId === previewRequest) { previewError.value = error.message || '营养摄入计算失败'; nutritionPreview.value = null } } finally { if (requestId === previewRequest) previewLoading.value = false }
}
async function resumeLatestNutritionJob() {
  try {
    const savedId = localStorage.getItem('nutrition-last-job-id')
    let response = savedId ? await fetch(`/local-api/jobs/${savedId}`) : null
    let data = response?.ok ? await response.json() : null
    if (!data) { response = await fetch('/local-api/nutrition/latest-job'); if (!response.ok) return; data = await response.json(); jobId.value = data.job_id }
    else jobId.value = savedId
    if (data.status !== 'completed' || !Array.isArray(data.people)) return
    people.value = data.people; localStorage.setItem('nutrition-last-job-id', jobId.value); reportProfiles.value = {}; reportReviews.value = {}; selectPerson(data.people[0] || { id: '', general: {} }); successMessage.value = data.message || '已恢复最近一次本地营养任务。'
  } catch (_) { /* 没有可恢复任务时保持新任务页面 */ }
}
async function generateReport(format) {
  if (!selected.value || !jobId.value) return
  reportGenerating.value = format; reportErrorMessage.value = ''; reportSuccessMessage.value = ''
  try {
    reportProfiles.value[selected.value.id] = { ...reportProfile.value }; reportReviews.value[selected.value.id] = copyReportReview(reportReview.value)
    const response = await fetch(`/local-api/nutrition/jobs/${jobId.value}/report`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ person: selected.value, format, user_overrides: { ...reportProfile.value, bmi: bmiValue.value }, report_date: selected.value.general?.调查日期 || '', auto_evaluation: false, manual_evaluations: manualEvaluationsPayload() })
    })
    if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || '报告生成失败') }
    const dataSource = response.headers.get('X-Nutrition-Data-Source') || 'unknown'
    const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url
    const fallbackName = `${selected.value.general?.姓名 || selected.value.id || '营养报告'}_${format === 'pdf' ? '营养健康评估报告.pdf' : '营养分析报告.xlsx'}`
    const encodedFilename = response.headers.get('X-Report-Filename'); let downloadName = fallbackName
    if (encodedFilename) { try { downloadName = decodeURIComponent(encodedFilename) } catch (_) { /* 使用安全回退文件名 */ } }
    link.download = downloadName
    document.body.appendChild(link); link.click(); link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1500)
    const sourceMessage = dataSource === 'local' ? '云端无法访问，本次已使用本地营养库。' : dataSource === 'stale_cloud' ? '云端无法访问，本次已使用上次云端缓存。' : '本次使用云端食物营养库。'
    reportSuccessMessage.value = `${format === 'pdf' ? '营养 PDF 报告' : '营养分析 Excel'}已生成并开始下载。${sourceMessage}`
  } catch (error) { reportErrorMessage.value = error.message || '报告生成失败' } finally { reportGenerating.value = '' }
}
watch(reportProfile, scheduleNutritionPreview, { deep: true })
watch(selected, scheduleNutritionPreview, { deep: true })
onMounted(resumeLatestNutritionJob)
</script>
