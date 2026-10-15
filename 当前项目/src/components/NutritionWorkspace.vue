<template>
  <header class="workspace-workbar">
    <div class="workspace-workbar-context"><strong>食物频率核对</strong><span>{{ people.length ? `${people.length} 名人员 · ${saving ? '正在保存当前核对信息…' : '修改内容会保存在当前任务中'}` : '上传问卷、识别并核对营养数据' }}</span></div>
    <div class="workspace-workbar-actions"><button :class="['workspace-settings-button', { 'needs-attention': !serverUrl }]" type="button" aria-label="打开食物频率设置" title="OCR 服务、汇总模板与报告设置" @click="openNutritionSettings"><span aria-hidden="true">⚙</span><span class="settings-button-label">设置</span></button></div>
  </header>
  <section v-if="nutritionSettingsOpen" class="settings-backdrop nutrition-settings-backdrop" @click.self="closeNutritionSettings">
    <section class="settings-dialog nutrition-settings-dialog" role="dialog" aria-modal="true" aria-labelledby="nutrition-settings-title">
      <div class="settings-head"><div><h2 id="nutrition-settings-title">食物频率设置</h2><p>配置 OCR 服务、识别方式、汇总模板和报告样式。设置保存在当前浏览器中，模板仅用于当前处理批次。</p></div><button class="dialog-close" type="button" aria-label="关闭食物频率设置" @click="closeNutritionSettings">×</button></div>
      <div class="nutrition-settings-content">
        <section class="nutrition-settings-group"><div class="settings-group-title"><span>1</span><div><h3>云端 OCR 服务</h3><p>用于识别食物频率问卷和体成分报告。</p></div></div><div class="input-row"><input v-model.trim="serverUrl" class="text-input" placeholder="https://your-host:8443 或完整 /parse-file 地址" /><button class="secondary-button" :disabled="testing || !serverUrl" @click="testOcr">{{ testing ? '检查中…' : '测试连接' }}</button></div><div class="recognition-options"><label class="parse-mode">识别结果解析来源 <select v-model="parseMode"><option value="markdown">Markdown（推荐：保留勾选列）</option><option value="excel">Excel</option></select></label><label class="parse-mode">识别速度 <select v-model="processingMode"><option value="fast">快速模式（推荐）</option><option value="accurate">精确模式（较慢）</option></select></label></div><p class="mode-help">两种模式都保留 OpenCV 勾选检测。快速模式只在每名受访者的第一页补做姓名 OCR；精确模式会检查更多可能包含姓名或签字的页面。</p><p v-if="serverMessage" :class="['server-state', serverOk ? 'ok' : 'error']">{{ serverMessage }}</p></section>
        <section class="nutrition-settings-group"><div class="settings-group-title"><span>2</span><div><h3>汇总模板</h3><p>可使用自己的 Excel 模板；未选择时使用系统默认模板。</p></div></div><label class="settings-file-picker"><input type="file" accept=".xlsx,.xlsm" @change="selectTemplate" /><strong>选择汇总模板</strong><span>{{ templateFile?.name || '当前使用系统默认模板' }}</span></label><a class="settings-template-download" href="/local-api/nutrition-template" download>下载系统默认模板</a></section>
        <section class="nutrition-settings-group"><div class="settings-group-title"><span>3</span><div><h3>报告附加页</h3><p>默认不生成说明页；如需核对 OCR 换算过程，可主动开启。适用于单人和批量 PDF 导出。</p></div></div><label class="parse-mode"><input v-model="includeQualityPage" type="checkbox" />增加“OCR 换算与数据质量说明”页</label></section>
        <section class="nutrition-settings-group"><div class="settings-group-title"><span>4</span><div><h3>报告样式</h3><p>默认使用新版报告；可切回原版报告。适用于单人和批量 PDF，不影响 Excel、计算结果或人工评价。</p></div></div><label class="parse-mode">PDF 报告样式 <select v-model="reportStyle" aria-label="营养 PDF 报告样式"><option value="modern">新版报告</option><option value="legacy">原版报告</option></select></label></section>
      </div>
      <div class="settings-actions"><button class="secondary-button" type="button" @click="closeNutritionSettings">取消</button><button class="primary-button" type="button" @click="saveNutritionSettings">保存设置</button></div>
    </section>
  </section>

  <section class="card">
    <div class="section-title"><div><span class="step">1</span><h2>选择食物频率调查报告</h2></div></div>
    <p class="hint">可直接选择 PDF，或选择包含每名受访者子文件夹的根目录。OCR 服务和汇总模板可在标题栏右上角的设置面板中调整。</p>
    <div class="upload-actions">
      <label class="drop-zone compact" :class="{ ready: nutritionFiles.length && mode === 'files' }"><input type="file" accept=".pdf,application/pdf" multiple @change="selectFiles" /><strong>直接选择 PDF</strong><span>{{ mode === 'files' && nutritionFiles.length ? `已选 ${nutritionFiles.length} 份，每份单独处理` : '支持单份或多份问卷' }}</span></label>
      <label class="drop-zone compact" :class="{ ready: nutritionFiles.length && mode === 'folder' }"><input type="file" accept=".pdf,application/pdf" multiple webkitdirectory directory @change="selectFolder" /><strong>选择问卷文件夹</strong><span>{{ mode === 'folder' && nutritionFiles.length ? `已读取 ${nutritionFiles.length} 份 PDF` : '每个子文件夹自动对应一名受访者' }}</span></label>
    </div>
    <div class="body-composition-upload">
      <div class="section-title"><div><span class="step">2</span><h2>体成分报告（可选）</h2></div></div>
      <div class="upload-actions">
        <label class="drop-zone compact" :class="{ ready: bodyCompositionFiles.length && bodyCompositionMode === 'files' }"><input type="file" accept=".pdf,application/pdf" multiple @change="selectBodyCompositionFiles" /><strong>直接选择体成分 PDF</strong><span>{{ bodyCompositionMode === 'files' && bodyCompositionFiles.length ? `已选 ${bodyCompositionFiles.length} 份体成分报告` : '支持单份或多份报告' }}</span></label>
        <label class="drop-zone compact" :class="{ ready: bodyCompositionFiles.length && bodyCompositionMode === 'folder' }"><input type="file" accept=".pdf,application/pdf" multiple webkitdirectory directory @change="selectBodyCompositionFolder" /><strong>选择体成分文件夹</strong><span>{{ bodyCompositionMode === 'folder' && bodyCompositionFiles.length ? `已读取 ${bodyCompositionFiles.length} 份体成分报告` : '自动读取文件夹内的 PDF 报告' }}</span></label>
      </div>
      <p v-if="bodyCompositionFiles.length" class="hint">将按报告姓名提取去脂体重（瘦体重）并合并。</p>
    </div>
    <div v-if="nutritionFiles.length" class="batch-summary"><span>将处理 <b>{{ personFolders.length }}</b> 名受访者 / <b>{{ nutritionFiles.length }}</b> 个 PDF</span><span v-for="folder in personFolders.slice(0, 6)" :key="folder">{{ folder }}</span></div>
    <div class="action-row"><button class="primary-button" :disabled="!canProcess" @click="process">开始识别并生成食物频率汇总</button><button class="secondary-button" :disabled="processing" @click="clear">清空</button></div>
    <div v-if="processing" class="progress-panel"><div class="progress-label"><strong>正在处理第 {{ Math.min(progress.completed + 1, progress.total) }}/{{ progress.total }} 个 PDF</strong><span>{{ progress.completed }}/{{ progress.total }}</span></div><div class="progress-track"><div class="progress-bar" :style="{ width: `${progressPercent}%` }"></div></div><p>{{ progress.currentFile || '正在准备任务…' }}</p></div>
    <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p><p v-if="successMessage" class="success-message">{{ successMessage }}</p>
  </section>

  <section v-if="people.length" class="card people-card nutrition-workspace">
    <div class="nutrition-section-head"><div><h2>问卷核对</h2><p>逐人核对人员资料、勾选信息和食物频率。</p></div><div class="nutrition-section-actions"><button class="secondary-button" type="button" :disabled="saving" @click="save">{{ saving ? '正在保存…' : '保存并下载 Excel' }}</button><button class="primary-button" type="button" :disabled="saving" @click="saveCurrentReview">{{ saving ? '保存中…' : '保存当前核对信息' }}</button></div></div>
    <p class="hint">已完成问卷中，食物摄入空白项按未食用处理；“未识别”或无法换算的非空填写仍保留核对提示。</p>
    <section class="nutrition-report-launch nutrition-batch-export" aria-label="批量导出全部营养报告">
      <h3>批量导出全部营养报告</h3>
      <p>导出当前任务全部 {{ people.length }} 人，不受搜索或分页限制。使用当前核对数据；未人工修改的人员保留机器初稿。ZIP 内附成功/失败清单，食物摄入空白项按未食用处理。</p>
      <div class="action-row"><select v-model="batchFormat" :disabled="batchGenerating" aria-label="批量报告格式"><option value="both">PDF + Excel</option><option value="pdf">仅 PDF</option><option value="excel">仅 Excel</option></select><button class="primary-button" :disabled="batchGenerating || reportGenerating !== '' || saving || appendingBodyComposition || applyingBodyCompositionMatches" @click="generateAllReports">{{ batchGenerating ? '正在生成全部报告…' : `导出全部 ${people.length} 人报告（ZIP）` }}</button></div>
      <p v-if="batchMessage" class="success-message">{{ batchMessage }}</p><p v-if="batchError" class="error-message">{{ batchError }}</p>
    </section>
    <section class="nutrition-report-launch body-composition-append">
      <div><h4>补充体成分报告</h4><p>只识别新上传的 InBody 等体成分报告，不会重新识别食物问卷，也不会清除当前已核对内容。识别完成后请确认姓名配对。</p></div>
      <div class="append-actions"><label class="secondary-button file-button"><input type="file" accept=".pdf,application/pdf" multiple @change="selectAppendBodyCompositionFiles" />选择体成分 PDF</label><button class="primary-button" type="button" :disabled="appendingBodyComposition || !appendBodyCompositionFiles.length" @click="appendBodyComposition">{{ appendingBodyComposition ? '正在识别…' : '追加并识别' }}</button></div>
    </section>
    <p v-if="appendBodyCompositionFiles.length" class="hint">已选 {{ appendBodyCompositionFiles.length }} 份体成分报告；会保留当前食物与人工核对数据。</p>
    <p v-if="bodyCompositionMessage" :class="['server-state', bodyCompositionError ? 'error' : 'ok']">{{ bodyCompositionMessage }}</p>
    <section v-if="bodyCompositionHistory.length" class="body-composition-match-panel">
      <button class="body-composition-panel-toggle" type="button" :aria-expanded="bodyCompositionPanelOpen" @click="bodyCompositionPanelOpen = !bodyCompositionPanelOpen"><span><strong>体成分资料与人员配对</strong><small>{{ bodyCompositionHistory.length }} 份报告 · 点击记录可统一补录全部资料</small></span><span class="panel-chevron" :class="{ open: bodyCompositionPanelOpen }">⌄</span></button>
      <div v-show="bodyCompositionPanelOpen" class="body-composition-panel-content"><div class="subsection-title"><div><h4>核对或修改配对</h4><p>每份报告的资料作为一个整体展示；橙色标签表示该项尚未识别。点击任意记录即可在弹窗中统一补录，年龄保存时只保留整数。</p></div><div class="append-actions"><label>筛选 <select v-model="bodyCompositionMatchFilter"><option value="all">全部</option><option value="pending">仅待配对</option><option value="paired">仅已配对</option><option value="missing-name">仅姓名未识别</option></select></label><button class="primary-button" type="button" :disabled="applyingBodyCompositionMatches" @click="applyBodyCompositionMatches">{{ applyingBodyCompositionMatches ? '正在保存…' : '保存配对修改' }}</button></div></div>
      <div class="mapping-wrap"><table class="mapping-table nutrition-table body-composition-match-table"><thead><tr><th>体成分文件</th><th>姓名</th><th>体成分资料</th><th>配对人员</th></tr></thead><tbody><tr v-for="record in visibleBodyCompositionMatches" :key="record.id" tabindex="0" :class="['body-record-row', { 'needs-review-row': bodyRecordNeedsReview(record), 'body-match-applied': record.match_status === 'applied' }]" title="点击补录或修改体成分资料" @click="openBodyRecordEditor(record)" @keydown.enter.prevent="openBodyRecordEditor(record)"><td @click.stop><a v-if="record.file_url" :href="record.file_url" download>{{ record.filename }}</a><span v-else>{{ record.filename }}</span></td><td><strong>{{ effectiveBodyName(record) || '未识别' }}</strong><small v-if="record.corrected_name && record.name && record.corrected_name !== record.name" class="body-ocr-original">OCR：{{ record.name }}</small></td><td><div class="body-data-list"><span v-for="item in bodyFieldItems(record)" :key="item.key" :class="['body-data-chip', { missing: item.missing }]"><b>{{ item.label }}</b>{{ item.missing ? '未识别' : item.value }}</span></div><span class="body-record-edit-hint">点击整行补录或修改</span></td><td @click.stop><span v-if="record.match_status === 'applied'" class="applied-match">已写入，可修改</span><select v-model="bodyCompositionAssignments[record.id]"><option value="">取消配对（保留待处理）</option><option v-for="person in people" :key="person.id" :value="person.id">{{ bodyPairLabel(record, person) }}</option></select></td></tr></tbody></table></div></div>
    </section>
    <section v-if="bodyRecordEditorOpen" class="nutrition-dialog-backdrop body-record-editor-backdrop" @click.self="closeBodyRecordEditor">
      <section class="nutrition-report-panel nutrition-report-dialog body-record-editor-dialog" role="dialog" aria-modal="true" aria-labelledby="body-record-editor-title">
        <div class="subsection-title"><div><h4 id="body-record-editor-title">补录体成分资料</h4><p>{{ bodyRecordDraft.filename }} · 所有字段属于同一份体成分记录，空白项保存后仍会以橙色提示。</p></div><button class="dialog-close" type="button" aria-label="关闭体成分补录窗口" @click="closeBodyRecordEditor">×</button></div>
        <div class="general-grid report-profile-grid body-record-editor-grid">
          <label>姓名<input v-model.trim="bodyRecordDraft.name" class="value-input" placeholder="姓名" /></label>
          <label>性别<select v-model="bodyRecordDraft.gender"><option value="">未识别</option><option value="female">女</option><option value="male">男</option></select></label>
          <label>年龄<input v-model.trim="bodyRecordDraft.age" class="value-input" inputmode="decimal" placeholder="岁，保存时取整数" /></label>
          <label>身高<input v-model.trim="bodyRecordDraft.height" class="value-input" inputmode="decimal" placeholder="cm" /></label>
          <label>体重<input v-model.trim="bodyRecordDraft.weight" class="value-input" inputmode="decimal" placeholder="kg" /></label>
          <label>去脂体重（瘦体重）<input v-model.trim="bodyRecordDraft.fatFreeMass" class="value-input" inputmode="decimal" placeholder="kg" /></label>
        </div>
        <p v-if="bodyRecordEditorError" class="error-message">{{ bodyRecordEditorError }}</p>
        <div class="settings-actions"><button class="secondary-button" type="button" @click="closeBodyRecordEditor">取消</button><button class="primary-button" type="button" @click="saveBodyRecordEditor">保存当前记录</button></div>
      </section>
    </section>
    <div class="review-layout nutrition-review">
      <aside class="person-list">
        <div class="person-list-toolbar"><div class="person-list-toolbar-head"><span>人员列表</span><strong>{{ filteredNutritionPeople.length }} / {{ people.length }} 人</strong></div><label class="person-list-search"><span class="sr-only">搜索受访者</span><input v-model="nutritionPersonSearch" type="search" placeholder="搜索姓名或人员编号" /></label><div class="person-list-options"><span>{{ nutritionPageRange }}</span><label>每页 <select v-model.number="nutritionPageSize"><option v-for="size in pageSizeOptions" :key="size" :value="size">{{ size }} 人</option></select></label></div></div>
        <p v-if="!filteredNutritionPeople.length" class="person-list-empty">没有找到匹配的受访者，请更换关键词。</p>
        <button v-for="person in pagedNutritionPeople" :key="person.id" type="button" :class="['person-item', { active: selectedId === person.id, 'has-review-items': personReviewCount(person) > 0 }]" @click="selectPerson(person)"><strong>{{ person.general.姓名 || person.id }}</strong><span>{{ person.id }} · {{ person.page_count || person.ocr_files.length }} 页 · {{ person.food_rows.length }} 类食物</span><span :class="['person-review-count', { clear: personReviewCount(person) === 0 }]">需核对 {{ personReviewCount(person) }} 项</span></button>
        <nav v-if="filteredNutritionPeople.length" class="person-list-pagination" aria-label="食物频率人员分页"><button type="button" :disabled="nutritionPage <= 1" @click="setNutritionPage(nutritionPage - 1)">上一页</button><span>第 {{ nutritionPage }} / {{ nutritionPageCount }} 页</span><button type="button" :disabled="nutritionPage >= nutritionPageCount" @click="setNutritionPage(nutritionPage + 1)">下一页</button></nav>
      </aside>
      <div v-if="selected" class="person-detail">
        <div class="detail-head"><div><h3>{{ selected.general.姓名 || selected.id }}</h3><p>{{ selected.id }}：请核对 OCR 数据、频率周期和纸质问卷上的勾选项。</p></div></div>
          <div class="ocr-downloads"><span>OCR 原始结果：</span><a v-for="(file, index) in selected.ocr_files" :key="file" :href="file" download>第 {{ index + 1 }} 页 Excel</a><a v-for="(file, index) in selected.markdown_files || []" :key="file" :href="file" download>第 {{ index + 1 }} 页 Markdown</a></div>
        <section class="nutrition-report-launch">
          <div><h4>营养评价与报告</h4><p>打开独立复核窗口，可查看或修改机器初稿、人工评价和评语，并直接导出。</p></div>
          <button class="primary-button" type="button" @click="openNutritionReview">导出营养评价</button>
        </section>
        <section v-if="nutritionReviewOpen" class="nutrition-dialog-backdrop" @click.self="closeNutritionReview">
          <section class="nutrition-report-panel nutrition-report-dialog" role="dialog" aria-modal="true" aria-labelledby="nutrition-report-title">
          <div class="subsection-title"><div><h4 id="nutrition-report-title">营养报告导出</h4><p>机器初稿依据运动员膳食干预参数V2.0，仅适用训练期。运动类型、体重和年龄决定参考目标；文档未规定的项目不自动判定。报告在本机生成。</p></div><button class="dialog-close" type="button" aria-label="关闭营养评价窗口" @click="closeNutritionReview">×</button></div>
          <div class="general-grid report-profile-grid">
            <label>姓名<input v-model="reportProfile.name" class="value-input" placeholder="姓名（可选）" /></label>
            <label>年龄<input v-model="reportProfile.age" class="value-input" inputmode="numeric" placeholder="岁（可选）" /></label>
            <label>项目种类<input v-model="reportProfile.projectType" class="value-input" placeholder="例如：女足（可选）" /></label>
            <label>运动类型<select v-model="reportProfile.athleteType" aria-label="运动类型"><option value="">按项目精确匹配／待确认</option><option value="strength">力量为主</option><option value="team">团体（有氧+力量）</option><option value="endurance">有氧为主</option></select></label>
            <label>训练阶段<select v-model="reportProfile.trainingPhase" aria-label="训练阶段"><option value="">按当前状态匹配／待确认</option><option value="training">训练期</option><option value="competition">赛期（不适用）</option><option value="other">其他（不适用）</option></select></label>
            <label>训练年限<input v-model="reportProfile.trainingYears" class="value-input" placeholder="例如：5年（可选）" /></label>
            <label>当前状态<input v-model="reportProfile.currentStatus" class="value-input" placeholder="例如：正常训练（可选）" /></label>
            <label>性别<select v-model="reportProfile.gender"><option value="">未填写</option><option value="female">女</option><option value="male">男</option></select></label>
            <label>身高<input v-model="reportProfile.height" class="value-input" inputmode="decimal" placeholder="cm（可选）" /></label>
            <label>体重<input v-model="reportProfile.weight" class="value-input" inputmode="decimal" placeholder="kg（可选）" /></label>
            <label>去脂体重（瘦体重）<input v-model="reportProfile.fatFreeMass" class="value-input" inputmode="decimal" placeholder="kg（可选）" /></label>
            <label>活动量<select v-model="reportProfile.activityLevel"><option value="">未填写</option><option value="1">低</option><option value="2">中</option><option value="3">高</option></select></label>
          </div>
          <label v-if="Number(reportProfile.weight) > 70">超过70kg的食物摄入倍率（专业人员确认）<input v-model="reportProfile.foodTargetScale" class="value-input" inputmode="decimal" placeholder="留空：只列基础参考；如1.2" /></label>
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
            <div v-if="unifiedEvaluationRows.length" class="nutrition-preview-panel">
              <h5>运动员专项膳食评价</h5>
              <p class="hint">{{ unifiedEvaluationContext }}</p>
              <p v-for="note in unifiedEvaluationWarnings" :key="note" class="hint">{{ note }}</p>
              <div class="mapping-wrap"><table class="mapping-table athlete-evaluation-table"><colgroup><col style="width: 20%" /><col style="width: 17%" /><col style="width: 39%" /><col style="width: 11%" /><col style="width: 13%" /></colgroup><thead><tr><th>项目</th><th>实际摄入</th><th>参考目标</th><th>差值</th><th>最终评价</th></tr></thead><tbody><tr v-for="row in unifiedEvaluationRows" :key="row.key"><td>{{ row.label }}</td><td>{{ row.actual ?? '—' }} {{ row.unit }}</td><td :class="row.target === '建议尽量不吃' ? '' : evaluationAlertClass(row.target)">{{ row.target }}<span v-if="row.note">；{{ row.note }}</span></td><td>{{ row.gap ?? '—' }}</td><td :class="evaluationAlertClass(finalEvaluation(row, reportReview))">{{ finalEvaluation(row, reportReview) || '—' }}</td></tr></tbody></table></div>
            </div>
            <div class="subsection-title"><div><h4>营养评价人工复核</h4><p>机器评价仅作初稿。请按实际情况逐项选择不足、适中、过多或其他自定义评价，并编辑最终建议和解读。</p></div><div class="review-header-actions"><button class="secondary-button mini-button" type="button" :disabled="!nutritionPreview" @click="resetReportReviewFromMachine">重载机器初稿</button></div></div>
            <p v-if="!nutritionPreview || previewLoading" class="hint">正在计算机器初稿，完成后可复核。</p>
            <template v-else>
              <div class="mapping-wrap"><table class="mapping-table nutrition-evaluation-table"><thead><tr><th>项目</th><th>当前摄入</th><th>人工最终评价</th></tr></thead><tbody>
                <tr v-for="row in categoryReviewRows" :key="row.key"><td>{{ row.label }}</td><td>{{ row.value }} g/天</td><td><div class="evaluation-control"><select :value="evaluationSelection(reportReview.categoryEvaluations[row.key], `category:${row.key}`)" class="evaluation-select" :class="evaluationAlertClass(reportReview.categoryEvaluations[row.key])" @change="setEvaluation('category', row.key, $event.target.value)"><option value="">—（不计算）</option><option value="不足">不足</option><option value="适中">适中</option><option value="过多">过多</option><option value="other">其他（手动填写）</option></select><input v-if="isManualEvaluation(reportReview.categoryEvaluations[row.key], `category:${row.key}`)" v-model="reportReview.categoryEvaluations[row.key]" :class="evaluationAlertClass(reportReview.categoryEvaluations[row.key])" class="cell-input manual-evaluation-input" placeholder="请输入其他评价" /></div></td></tr>
                <tr v-for="row in nutrientReviewRows" :key="row.key"><td>{{ row.label }}</td><td>{{ row.value }} {{ row.unit }}</td><td><div class="evaluation-control"><select :value="evaluationSelection(reportReview[row.key], `nutrition:${row.key}`)" class="evaluation-select" :class="evaluationAlertClass(reportReview[row.key])" @change="setEvaluation('nutrition', row.key, $event.target.value)"><option value="">—（不计算）</option><option value="不足">不足</option><option value="适中">适中</option><option value="过多">过多</option><option value="other">其他（手动填写）</option></select><input v-if="isManualEvaluation(reportReview[row.key], `nutrition:${row.key}`)" v-model="reportReview[row.key]" :class="evaluationAlertClass(reportReview[row.key])" class="cell-input manual-evaluation-input" placeholder="请输入其他评价" /></div></td></tr>
              </tbody></table></div>
              <div class="report-review-textareas"><label>总体建议（可修改机器初稿）<textarea v-model="reportReview.overallSuggestions" rows="8" placeholder="每行一条建议"></textarea></label><label>最终总结 / 报告解读（可修改机器初稿）<textarea v-model="reportReview.interpretation" rows="8" placeholder="请输入最终总结或解读"></textarea></label></div>
              <p class="nutrition-disclaimer-preview">报告将注明：以上营养成分仅根据记录饮食计算，不包含维生素、矿物质、蛋白粉等其他补充剂摄入。</p>
            </template>
          </section>
          <div class="action-row report-actions"><button class="primary-button" :disabled="batchGenerating || reportGenerating !== '' || !canExportReviewedReport" @click="generateReport('pdf')">{{ reportGenerating === 'pdf' ? '正在生成 PDF…' : '导出营养 PDF 报告' }}</button><button class="secondary-button" :disabled="batchGenerating || reportGenerating !== '' || !canExportReviewedReport" @click="generateReport('excel')">{{ reportGenerating === 'excel' ? '正在生成 Excel…' : '导出营养分析 Excel' }}</button></div>
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
import { storedOcrApiUrl } from '../runtime-config'
import { buildBatchPayload } from '../nutrition-batch'
import { evaluationRows, evaluationWarnings, evaluationContext, finalEvaluation, evaluationAlertClass } from '../nutrition-presentation'

const includeQualityPage = ref(localStorage.getItem('nutrition-include-quality-page') === 'true')
const reportStyle = ref(localStorage.getItem('nutrition-report-style') === 'legacy' ? 'legacy' : 'modern')
const serverUrl = ref(storedOcrApiUrl())
const serverMessage = ref(''); const serverOk = ref(false); const testing = ref(false)
const nutritionFiles = ref([]); const bodyCompositionFiles = ref([]); const mode = ref('folder'); const bodyCompositionMode = ref(''); const templateFile = ref(null); const parseMode = ref(localStorage.getItem('ocr-parse-mode') || 'markdown'); const processingMode = ref(localStorage.getItem('ocr-processing-mode') || 'fast'); const processing = ref(false); const saving = ref(false)
const progress = ref({ completed: 0, total: 0, currentFile: '' }); const errorMessage = ref(''); const successMessage = ref('')
const people = ref([]); const selectedId = ref(''); const jobId = ref('')
const batchGenerating = ref(false); const batchFormat = ref('both'); const batchMessage = ref(''); const batchError = ref('')
const reportGenerating = ref(''); const reportProfiles = ref({}); const reportProfile = ref(emptyReportProfile()); const reportReviews = ref({}); const reportReview = ref(emptyReportReview())
const nutritionPreview = ref(null); const previewLoading = ref(false); const previewError = ref(''); const previewUsableFoodCount = ref(0)
const reportErrorMessage = ref(''); const reportSuccessMessage = ref('')
const nutritionReviewOpen = ref(false)
const nutritionSettingsOpen = ref(false); const nutritionSettingsSnapshot = ref(null)
const appendBodyCompositionFiles = ref([]); const appendingBodyComposition = ref(false); const applyingBodyCompositionMatches = ref(false)
const bodyCompositionMatches = ref([]); const bodyCompositionHistory = ref([]); const bodyCompositionAssignments = ref({}); const bodyCompositionMessage = ref(''); const bodyCompositionError = ref(false); const bodyCompositionMatchFilter = ref('all'); const bodyCompositionPanelOpen = ref(true)
const bodyRecordEditorOpen = ref(false); const editingBodyRecordId = ref(''); const bodyRecordDraft = ref(emptyBodyRecordDraft()); const bodyRecordEditorError = ref('')
const pageSizeOptions = [10, 20, 30, 50, 100]
const nutritionPersonSearch = ref(''); const nutritionPageSize = ref(10); const nutritionPage = ref(1)
const canProcess = computed(() => !!(serverUrl.value && nutritionFiles.value.length && !processing.value))
const personFolders = computed(() => [...new Set(nutritionFiles.value.map(folderFor))].sort((a, b) => a.localeCompare(b, 'zh-CN')))
const selected = computed(() => people.value.find((person) => person.id === selectedId.value) || people.value[0])
const filteredNutritionPeople = computed(() => { const query = nutritionPersonSearch.value.trim().toLocaleLowerCase('zh-CN'); if (!query) return people.value; return people.value.filter((person) => nutritionPersonSearchText(person).includes(query)) })
const nutritionPageCount = computed(() => Math.max(1, Math.ceil(filteredNutritionPeople.value.length / nutritionPageSize.value)))
const pagedNutritionPeople = computed(() => { const start = (nutritionPage.value - 1) * nutritionPageSize.value; return filteredNutritionPeople.value.slice(start, start + nutritionPageSize.value) })
const nutritionPageRange = computed(() => { if (!filteredNutritionPeople.value.length) return '0 人'; const start = (nutritionPage.value - 1) * nutritionPageSize.value + 1; const end = Math.min(start + nutritionPageSize.value - 1, filteredNutritionPeople.value.length); return `显示 ${start}–${end}，共 ${filteredNutritionPeople.value.length} 人` })
const bmiValue = computed(() => { const height = Number(reportProfile.value.height); const weight = Number(reportProfile.value.weight); if (!(height > 0 && weight > 0)) return ''; return (weight / ((height / 100) ** 2)).toFixed(1) })
const bmiStatus = computed(() => { const bmi = Number(bmiValue.value); if (!bmi) return ''; if (bmi < 18.5) return '偏瘦'; if (bmi < 24) return '正常'; if (bmi < 28) return '超重'; return '肥胖' })
const energyStandardNote = computed(() => nutritionPreview.value?.nutrition?.energy?.standard_note || '请选择活动量')
const nutritionDataSource = computed(() => nutritionPreview.value?.food_data_source || {})
const unifiedEvaluationRows = computed(() => evaluationRows(nutritionPreview.value))
const unifiedEvaluationContext = computed(() => evaluationContext(nutritionPreview.value))
const unifiedEvaluationWarnings = computed(() => evaluationWarnings(nutritionPreview.value))
const categoryReviewRows = computed(() => Object.entries(nutritionPreview.value?.category_result || {}).map(([key, info]) => ({ key, label: key, value: key === '奶类' && 'equivalent_value' in info ? `${info.value}（原重），鲜奶等价量（按蛋白质估计）${info.equivalent_value ?? '-'}` : (info?.value ?? 0), machineEvaluation: machineEvaluationText(info?.evaluation) })))
const nutrientReviewRows = computed(() => {
  const nutrition = nutritionPreview.value?.nutrition || {}
  return [
    { key: 'energyEvaluation', label: '总能量', value: nutrition.energy?.value ?? '—', unit: 'kcal/天', machineEvaluation: machineEvaluationText(nutrition.energy?.evaluation) },
    { key: 'calciumEvaluation', label: '钙', value: nutrition.calcium?.value ?? '—', unit: 'mg/天', machineEvaluation: machineEvaluationText(nutrition.calcium?.evaluation) },
    ...unifiedEvaluationRows.value.filter(row => !['protein','carbohydrate','fat','calcium'].includes(row.key)).map((row) => ({ key: `standard_${row.key}Evaluation`, label: row.label, value: row.actual ?? '—', unit: row.unit, machineEvaluation: machineEvaluationText(row.machine_evaluation) })),
    ...unifiedEvaluationRows.value.filter((row) => ['protein', 'carbohydrate', 'fat'].includes(row.key)).map((row) => ({ key: `${row.key}Evaluation`, label: row.label, value: row.actual ?? '—', unit: row.unit, machineEvaluation: machineEvaluationText(row.machine_evaluation) })),
  ]
})
const canExportReviewedReport = computed(() => !!(selected.value && nutritionPreview.value && !previewLoading.value))
const visibleBodyCompositionMatches = computed(() => bodyCompositionHistory.value.filter((record) => {
  const paired = Boolean(bodyCompositionAssignments.value[record.id]); const missingName = !String(record.corrected_name || record.name || '').trim()
  if (bodyCompositionMatchFilter.value === 'pending') return !paired
  if (bodyCompositionMatchFilter.value === 'paired') return record.match_status === 'applied' || paired
  if (bodyCompositionMatchFilter.value === 'missing-name') return missingName
  return true
}))
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
function nutritionPersonSearchText(person) { return `${person?.general?.姓名 || ''} ${person?.id || ''} ${personSourceFileNames(person)}`.toLocaleLowerCase('zh-CN') }
function ensureNutritionSelectionOnPage() { const person = pagedNutritionPeople.value.find((item) => item.id === selectedId.value) || pagedNutritionPeople.value[0]; if (person && person.id !== selectedId.value) selectPerson(person) }
function setNutritionPage(page) { nutritionPage.value = Math.min(Math.max(1, page), nutritionPageCount.value); ensureNutritionSelectionOnPage() }
function saveUrl() { localStorage.setItem('medical-ocr-api-url', serverUrl.value); serverOk.value = true; serverMessage.value = '云端地址已保存。' }
function saveParseMode() { localStorage.setItem('ocr-parse-mode', parseMode.value) }
function saveProcessingMode() { localStorage.setItem('ocr-processing-mode', processingMode.value) }
function openNutritionSettings() { nutritionSettingsSnapshot.value = { serverUrl: serverUrl.value, parseMode: parseMode.value, processingMode: processingMode.value, templateFile: templateFile.value, includeQualityPage: includeQualityPage.value, reportStyle: reportStyle.value }; nutritionSettingsOpen.value = true }
function closeNutritionSettings() { const snapshot = nutritionSettingsSnapshot.value; if (snapshot) { serverUrl.value = snapshot.serverUrl; parseMode.value = snapshot.parseMode; processingMode.value = snapshot.processingMode; templateFile.value = snapshot.templateFile; includeQualityPage.value = snapshot.includeQualityPage; reportStyle.value = snapshot.reportStyle }; nutritionSettingsSnapshot.value = null; nutritionSettingsOpen.value = false }
function saveNutritionSettings() { saveUrl(); saveParseMode(); saveProcessingMode(); localStorage.setItem('nutrition-include-quality-page', String(includeQualityPage.value)); localStorage.setItem('nutrition-report-style', reportStyle.value); nutritionSettingsSnapshot.value = null; nutritionSettingsOpen.value = false }
function selectTemplate(event) { templateFile.value = event.target.files?.[0] || null }
function setFiles(files, nextMode) { mode.value = nextMode; nutritionFiles.value = Array.from(files || []).filter((file) => /\.pdf$/i.test(file.name)); errorMessage.value = ''; successMessage.value = '' }
function selectFiles(event) { setFiles(event.target.files, 'files') }
function selectFolder(event) { setFiles(event.target.files, 'folder') }
function setBodyCompositionFiles(files, nextMode) { bodyCompositionMode.value = nextMode; bodyCompositionFiles.value = Array.from(files || []).filter((file) => /\.pdf$/i.test(file.name)); errorMessage.value = ''; successMessage.value = '' }
function selectBodyCompositionFiles(event) { setBodyCompositionFiles(event.target.files, 'files') }
function selectBodyCompositionFolder(event) { setBodyCompositionFiles(event.target.files, 'folder') }
function selectAppendBodyCompositionFiles(event) { appendBodyCompositionFiles.value = Array.from(event.target.files || []).filter((file) => /\.pdf$/i.test(file.name)); bodyCompositionMessage.value = ''; bodyCompositionError.value = false }
function emptyReportProfile() { return { name: '', age: '', projectType: '', athleteType: '', trainingPhase: 'training', trainingYears: '', currentStatus: '', gender: '', height: '', weight: '', fatFreeMass: '', activityLevel: '', foodTargetScale: '' } }
function emptyBodyRecordDraft() { return { filename: '', name: '', gender: '', age: '', height: '', weight: '', fatFreeMass: '' } }
function emptyReportReview() { return { categoryEvaluations: {}, energyEvaluation: '', calciumEvaluation: '', overallSuggestions: '', interpretation: '', machineSeeded: false, manualEntryFields: {} } }
function copyReportReview(review) { return { ...emptyReportReview(), ...(review || {}), categoryEvaluations: { ...(review?.categoryEvaluations || {}) }, manualEntryFields: { ...(review?.manualEntryFields || {}) } } }
function machineEvaluationText(value) { return String(value ?? '').trim() }
function machineInterpretation(preview) {
  const nutrition = preview?.nutrition || {}; const lines = []
  if (nutrition.energy?.evaluation === '不足') lines.push('总能量摄入不足，需结合训练量调整全天饮食。')
  else if (nutrition.energy?.evaluation === '过多') lines.push('能量摄入偏多，建议结合训练量调整总能量摄入。')
  const carb = (preview?.athlete_evaluation?.rows || []).find(row => row.key === 'carbohydrate')
  const grains = (preview?.food_standard_evaluation?.rows || []).find(row => row.key === 'grains_remainder')
  if (carb?.evaluation === '不足') lines.push('碳水化合物营养素摄入不足，需结合训练量补充碳水来源。')
  if (grains?.evaluation_basis === 'ratio' && ['过多', '能量占比偏高'].includes(grains?.evaluation)) lines.push('谷类在主食总能量中占比偏高；建议增加豆类、薯类的搭配。')
  if (nutrition.calcium?.evaluation === '不足') lines.push('钙摄入偏少，建议优先从奶类、豆制品等食物补充。')
  return lines.join('\n') || '请结合受访者训练、疾病和补充剂使用情况进行最终解读。'
}
function seedReportReviewFromPreview() {
  if (!selected.value || !nutritionPreview.value) return
  const preview = nutritionPreview.value; const categoryEvaluations = {}
  Object.entries(preview.category_result || {}).forEach(([category, info]) => { categoryEvaluations[category] = machineEvaluationText(info?.evaluation) })
  const next = { categoryEvaluations, energyEvaluation: machineEvaluationText(preview.nutrition?.energy?.evaluation), calciumEvaluation: machineEvaluationText(preview.nutrition?.calcium?.evaluation), overallSuggestions: (preview.suggestions || []).join('\n') || '请结合实际饮食、训练与健康状况给出建议。', interpretation: machineInterpretation(preview) }
  for (const row of preview.athlete_evaluation?.rows || []) if (['protein', 'carbohydrate', 'fat'].includes(row.key)) next[`${row.key}Evaluation`] = machineEvaluationText(row.machine_evaluation)
  for (const row of preview.food_standard_evaluation?.rows || []) next[`standard_${row.key}Evaluation`] = machineEvaluationText(row.machine_evaluation)
  const previous = reportReview.value.lastMachine || {}
  const merged = { ...reportReview.value, categoryEvaluations: { ...reportReview.value.categoryEvaluations } }
  for (const [key, value] of Object.entries(next)) {
    if (key === 'categoryEvaluations') {
      for (const [category, evaluation] of Object.entries(value)) if (!reportReview.value.machineSeeded || merged.categoryEvaluations[category] === previous.categoryEvaluations?.[category]) merged.categoryEvaluations[category] = evaluation
    } else if (!reportReview.value.machineSeeded || merged[key] === previous[key]) merged[key] = value
  }
  reportReview.value = { ...merged, lastMachine: next, machineSeeded: true }
  reportReviews.value[selected.value.id] = copyReportReview(reportReview.value)
}
function resetReportReviewFromMachine() { reportReview.value = emptyReportReview(); seedReportReviewFromPreview() }
function evaluationSelection(value, fieldKey) { const text = String(value || '').trim(); if (reportReview.value.manualEntryFields?.[fieldKey] || (text && !['不足', '适中', '过多'].includes(text))) return 'other'; return text }
function isManualEvaluation(value, fieldKey) { return evaluationSelection(value, fieldKey) === 'other' }
function setEvaluation(kind, key, selection) {
  const fieldKey = `${kind === 'category' ? 'category' : 'nutrition'}:${key}`
  const target = kind === 'category' ? reportReview.value.categoryEvaluations : reportReview.value
  if (selection === 'other') {
    reportReview.value.manualEntryFields[fieldKey] = true
    if (['不足', '适中', '过多'].includes(String(target[key] || '').trim())) target[key] = ''
    return
  }
  delete reportReview.value.manualEntryFields[fieldKey]
  target[key] = selection
}
function manualEvaluationsPayload() {
  const manual = buildBatchPayload([selected.value], 'pdf', {}, { [selected.value.id]: reportReview.value }).reviews[selected.value.id]
  return manual || {}
}
function openNutritionReview() { reportErrorMessage.value = ''; reportSuccessMessage.value = ''; nutritionReviewOpen.value = true; scheduleNutritionPreview() }
function closeNutritionReview() { nutritionReviewOpen.value = false }
function formatSourceTime(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value || '') : date.toLocaleString('zh-CN', { hour12: false }) }
function genderForReport(value) { const text = String(value || '').trim().toLowerCase(); return ['女', '女性', 'female', 'f'].includes(text) ? 'female' : ['男', '男性', 'male', 'm'].includes(text) ? 'male' : '' }
function selectPerson(person) {
  if (selectedId.value) { reportProfiles.value[selectedId.value] = { ...reportProfile.value }; reportReviews.value[selectedId.value] = copyReportReview(reportReview.value) }
  selectedId.value = person.id
  reportProfile.value = { ...emptyReportProfile(), ...(reportProfiles.value[person.id] || { name: person.general?.姓名 || '', age: person.general?.年龄 || '', projectType: person.general?.项目种类 || '', trainingYears: person.general?.训练年限 || '', currentStatus: person.general?.当前状态 || '', gender: genderForReport(person.general?.性别), height: person.general?.身高 || '', weight: person.general?.体重 || '', fatFreeMass: person.general?.去脂体重 || '', activityLevel: person.general?.运动量 || '' }) }
  reportReview.value = copyReportReview(reportReviews.value[person.id])
  nutritionPreview.value = null
  scheduleNutritionPreview()
}
function clear() { nutritionFiles.value = []; bodyCompositionFiles.value = []; bodyCompositionMode.value = ''; appendBodyCompositionFiles.value = []; bodyCompositionMatches.value = []; bodyCompositionHistory.value = []; bodyCompositionAssignments.value = {}; bodyCompositionMessage.value = ''; bodyCompositionError.value = false; bodyRecordEditorOpen.value = false; editingBodyRecordId.value = ''; bodyRecordDraft.value = emptyBodyRecordDraft(); bodyRecordEditorError.value = ''; people.value = []; selectedId.value = ''; nutritionPersonSearch.value = ''; nutritionPage.value = 1; errorMessage.value = ''; successMessage.value = ''; reportProfiles.value = {}; reportProfile.value = emptyReportProfile(); reportReviews.value = {}; reportReview.value = emptyReportReview(); nutritionPreview.value = null; nutritionReviewOpen.value = false; previewError.value = ''; reportErrorMessage.value = ''; reportSuccessMessage.value = '' }
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
async function testOcr() { testing.value = true; try { const form = new FormData(); form.append('ocr_url', serverUrl.value); const r = await fetch('/local-api/test-ocr', { method: 'POST', body: form }); const d = await r.json(); if (!r.ok) throw new Error(d.detail); serverOk.value = true; serverMessage.value = d.message } catch (e) { serverOk.value = false; serverMessage.value = `连接失败：${e.message}` } finally { testing.value = false } }
async function process() { processing.value = true; errorMessage.value = ''; successMessage.value = ''; people.value = []; reportReviews.value = {}; bodyCompositionMatches.value = []; bodyCompositionHistory.value = []; progress.value = { completed: 0, total: nutritionFiles.value.length + bodyCompositionFiles.value.length, currentFile: '' }; try { saveProcessingMode(); const form = new FormData(); form.append('ocr_url', serverUrl.value); form.append('parse_mode', parseMode.value); form.append('processing_mode', processingMode.value); if (templateFile.value) form.append('template', templateFile.value); nutritionFiles.value.forEach((file) => { form.append('files', file); form.append('relative_paths', mode.value === 'folder' ? (file.webkitRelativePath || file.name) : file.name) }); bodyCompositionFiles.value.forEach((file) => { form.append('body_composition_files', file); form.append('body_composition_relative_paths', bodyCompositionMode.value === 'folder' ? (file.webkitRelativePath || file.name) : file.name) }); const r = await fetch('/local-api/nutrition/process', { method: 'POST', body: form }); const d = await r.json(); if (!r.ok || !d.success) throw new Error(d.detail || '任务创建失败'); jobId.value = d.job_id; localStorage.setItem('nutrition-last-job-id', d.job_id); poll() } catch (e) { errorMessage.value = e.message; processing.value = false } }
async function poll() { try { const r = await fetch(`/local-api/jobs/${jobId.value}`); const d = await r.json(); if (!r.ok) throw new Error(d.detail); progress.value = { completed: d.completed_files, total: d.total_files, currentFile: d.current_file }; if (d.status === 'completed') { people.value = d.people; reportProfiles.value = {}; reportReviews.value = {}; selectPerson(d.people[0] || { id: '', general: {} }); successMessage.value = d.message; processing.value = false; return } if (d.status === 'failed') throw new Error(d.message); window.setTimeout(poll, 700) } catch (e) { errorMessage.value = e.message; processing.value = false } }
function matchScore(record, personId) { return (record.match_candidates || []).find((candidate) => candidate.person_id === personId)?.score || '' }
function selectedBodyRecordCount(personId) { return Object.values(bodyCompositionAssignments.value).filter((value) => value === personId).length }
function pairedPersonLabel(record) { const person = people.value.find((item) => item.id === record.assigned_person_id); return person ? `${person.general?.姓名 || person.id}｜${personSourceFileNames(person)}` : record.assigned_person_id || '已写入人员' }
function personSourceFileNames(person) { const explicit = (person.source_files || []).map((file) => String(file || '').trim()).filter(Boolean); if (explicit.length) return explicit.join('、'); const inferred = (person.ocr_files || []).map((file) => { const name = decodeURIComponent(String(file || '').split('/').pop() || ''); const match = name.match(/^\d+_(.+)_ocr\.xlsx$/); return match ? `${match[1]}.pdf` : '' }).filter(Boolean); return inferred.length ? [...new Set(inferred)].join('、') : String(person.id || '未记录原文件') }
function bodyPairLabel(record, person) { const name = person.general?.姓名 || person.id; const score = matchScore(record, person.id); const used = selectedBodyRecordCount(person.id); return `${name}｜原件：${personSourceFileNames(person)}${score ? `｜候选 ${score}%` : ''}${used ? ` ★已选 ${used}` : ''}` }
function effectiveFatFreeMass(record) { return String(record.corrected_fat_free_mass || record.fat_free_mass || '').trim() }
function effectiveBodyName(record) { return String(record.corrected_name || record.name || '').trim() }
function bodyFieldItems(record) { const gender = genderForReport(record.gender); return [{ key: 'gender', label: '性别', value: gender === 'female' ? '女' : gender === 'male' ? '男' : '', missing: !gender }, { key: 'age', label: '年龄', value: record.age ? `${record.age} 岁` : '', missing: !record.age }, { key: 'height', label: '身高', value: record.height ? `${record.height} cm` : '', missing: !record.height }, { key: 'weight', label: '体重', value: record.weight ? `${record.weight} kg` : '', missing: !record.weight }, { key: 'fatFreeMass', label: '去脂体重', value: effectiveFatFreeMass(record) ? `${effectiveFatFreeMass(record)} kg` : '', missing: !effectiveFatFreeMass(record) }] }
function bodyRecordNeedsReview(record) { return !bodyCompositionAssignments.value[record.id] || !effectiveBodyName(record) || bodyFieldItems(record).some((item) => item.missing) }
function openBodyRecordEditor(record) { editingBodyRecordId.value = record.id; bodyRecordDraft.value = { filename: record.filename || '未命名体成分报告', name: effectiveBodyName(record), gender: genderForReport(record.gender), age: String(record.age || ''), height: String(record.height || ''), weight: String(record.weight || ''), fatFreeMass: effectiveFatFreeMass(record) }; bodyRecordEditorError.value = ''; bodyRecordEditorOpen.value = true }
function closeBodyRecordEditor() { bodyRecordEditorOpen.value = false; editingBodyRecordId.value = ''; bodyRecordDraft.value = emptyBodyRecordDraft(); bodyRecordEditorError.value = '' }
function normalizedBodyNumber(value, label, minimum, maximum, integer = false) { const text = String(value || '').trim(); if (!text) return ''; const number = Number(text); if (!Number.isFinite(number) || number < minimum || number > maximum) throw new Error(`${label}应填写 ${minimum}–${maximum} 之间的数字`); return String(integer ? Math.trunc(number) : number) }
function saveBodyRecordEditor() { const record = bodyCompositionHistory.value.find((item) => item.id === editingBodyRecordId.value); if (!record) { bodyRecordEditorError.value = '当前体成分记录已不存在，请关闭后重试。'; return } try { record.corrected_name = String(bodyRecordDraft.value.name || '').replace(/\s+/g, ''); record.gender = bodyRecordDraft.value.gender || ''; record.age = normalizedBodyNumber(bodyRecordDraft.value.age, '年龄', 0, 150, true); record.height = normalizedBodyNumber(bodyRecordDraft.value.height, '身高', 80, 250); record.weight = normalizedBodyNumber(bodyRecordDraft.value.weight, '体重', 20, 300); record.corrected_fat_free_mass = normalizedBodyNumber(bodyRecordDraft.value.fatFreeMass, '去脂体重', 10, 250); autoPairByManualName(record); bodyCompositionError.value = false; bodyCompositionMessage.value = `已更新“${record.filename || '当前记录'}”，请点击“保存配对修改”写入人员资料。`; closeBodyRecordEditor() } catch (error) { bodyRecordEditorError.value = error.message || '请检查补录内容' } }
function autoPairByManualName(record) { const name = String(record.corrected_name || '').replace(/\s+/g, ''); if (!name) return; const matches = people.value.filter((person) => String(person.general?.姓名 || '').replace(/\s+/g, '') === name); if (matches.length === 1) { bodyCompositionAssignments.value[record.id] = matches[0].id; bodyCompositionError.value = false; bodyCompositionMessage.value = `手工姓名“${name}”已自动精确匹配到“${matches[0].general?.姓名 || matches[0].id}”。` } }
function loadBodyCompositionMatches(data) { const pending = Array.isArray(data.body_composition_pending_matches) ? data.body_composition_pending_matches : []; const history = Array.isArray(data.body_composition_match_history) && data.body_composition_match_history.length ? data.body_composition_match_history : pending; bodyCompositionHistory.value = history.map((record) => ({ ...record, corrected_name: record.corrected_name || '', corrected_fat_free_mass: record.corrected_fat_free_mass || '' })); bodyCompositionMatches.value = bodyCompositionHistory.value; const savedAssignments = data.body_composition_assignments || {}; bodyCompositionAssignments.value = Object.fromEntries(bodyCompositionHistory.value.map((record) => [record.id, savedAssignments[record.id] || record.assigned_person_id || record.suggested_person_id || ''])) }
function replacePeople(nextPeople) { const currentId = selectedId.value; people.value = Array.isArray(nextPeople) ? nextPeople : people.value; reportProfiles.value = {}; reportReviews.value = {}; selectedId.value = ''; selectPerson(people.value.find((person) => person.id === currentId) || people.value[0] || { id: '', general: {} }) }
async function pollAppendedBodyComposition() {
  try {
    const response = await fetch(`/local-api/jobs/${jobId.value}`); const data = await response.json(); if (!response.ok) throw new Error(data.detail || '无法读取体成分追加状态')
    const status = data.body_composition_status
    if (status === 'processing') { bodyCompositionMessage.value = `正在识别体成分报告 ${data.body_composition_completed_files || 0}/${data.body_composition_total_files || appendBodyCompositionFiles.value.length}…`; window.setTimeout(pollAppendedBodyComposition, 700); return }
    appendingBodyComposition.value = false
    if (status === 'awaiting_match') { bodyCompositionMessage.value = data.message || '识别完成，请确认姓名配对。'; bodyCompositionError.value = false; loadBodyCompositionMatches(data); return }
    if (status === 'failed') throw new Error(data.message || '体成分追加失败')
  } catch (error) { appendingBodyComposition.value = false; bodyCompositionError.value = true; bodyCompositionMessage.value = error.message || '体成分追加失败' }
}
async function appendBodyComposition() {
  if (!jobId.value || !appendBodyCompositionFiles.value.length) return
  appendingBodyComposition.value = true; bodyCompositionError.value = false; bodyCompositionMessage.value = '正在上传并保留当前食物问卷核对结果…'; bodyCompositionMatches.value = []; bodyCompositionAssignments.value = {}
  try {
    const form = new FormData(); form.append('ocr_url', serverUrl.value); form.append('people_json', JSON.stringify(people.value)); appendBodyCompositionFiles.value.forEach((file) => { form.append('files', file); form.append('relative_paths', file.webkitRelativePath || file.name) })
    const response = await fetch(`/local-api/nutrition/jobs/${jobId.value}/body-composition`, { method: 'POST', body: form }); const data = await response.json(); if (!response.ok || !data.success) throw new Error(data.detail || '体成分追加任务创建失败'); pollAppendedBodyComposition()
  } catch (error) { appendingBodyComposition.value = false; bodyCompositionError.value = true; bodyCompositionMessage.value = error.message || '体成分追加失败' }
}
async function applyBodyCompositionMatches() {
  applyingBodyCompositionMatches.value = true; bodyCompositionError.value = false
  try {
    const response = await fetch(`/local-api/nutrition/jobs/${jobId.value}/body-composition/apply-matches`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ people: people.value, assignments: bodyCompositionAssignments.value, body_composition_matches: bodyCompositionHistory.value }) }); const data = await response.json(); if (!response.ok || !data.success) throw new Error(data.detail || '体成分配对写入失败')
    replacePeople(data.people); loadBodyCompositionMatches({ body_composition_pending_matches: data.pending_matches || [], body_composition_match_history: data.history || [], body_composition_assignments: data.assignments || {} }); appendBodyCompositionFiles.value = []; bodyCompositionMessage.value = data.message || '体成分资料已追加。'
  } catch (error) { bodyCompositionError.value = true; bodyCompositionMessage.value = error.message || '体成分配对写入失败' } finally { applyingBodyCompositionMatches.value = false }
}
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
function currentReviewPayload() { return { people: people.value, body_composition_pending_matches: bodyCompositionMatches.value, body_composition_assignments: bodyCompositionAssignments.value } }
async function saveCurrentReview() { if (!jobId.value) return; saving.value = true; try { const r = await fetch(`/local-api/nutrition/jobs/${jobId.value}/save-review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...currentReviewPayload(), write_output: false }) }); const d = await r.json(); if (!r.ok || !d.success) throw new Error(d.detail || '保存失败'); successMessage.value = '当前核对信息已保存，可随时继续配对。'; errorMessage.value = '' } catch (e) { errorMessage.value = e.message } finally { saving.value = false } }
async function save() { saving.value = true; try { const r = await fetch(`/local-api/nutrition/jobs/${jobId.value}/save-review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(currentReviewPayload()) }); const d = await r.json(); if (!r.ok || !d.success) throw new Error(d.detail || '保存失败'); successMessage.value = d.message; window.location.assign(d.output_url) } catch (e) { errorMessage.value = e.message } finally { saving.value = false } }
let previewTimer = 0
let previewRequest = 0
function scheduleNutritionPreview() { window.clearTimeout(previewTimer); ++previewRequest; previewLoading.value = true; previewTimer = window.setTimeout(refreshNutritionPreview, 350) }
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
    people.value = data.people; localStorage.setItem('nutrition-last-job-id', jobId.value); reportProfiles.value = {}; reportReviews.value = {}; selectPerson(data.people[0] || { id: '', general: {} }); if (data.body_composition_status === 'awaiting_match') loadBodyCompositionMatches(data); successMessage.value = data.message || '已恢复最近一次本地营养任务。'
  } catch (_) { /* 没有可恢复任务时保持新任务页面 */ }
}
async function generateAllReports() {
  if (!jobId.value || !people.value.length || batchGenerating.value) return
  batchGenerating.value = true; batchMessage.value = ''; batchError.value = ''
  try {
    if (selected.value) {
      reportProfiles.value[selected.value.id] = { ...reportProfile.value, bmi: bmiValue.value }
      reportReviews.value[selected.value.id] = copyReportReview(reportReview.value)
    }
    const payload = buildBatchPayload(people.value, batchFormat.value, reportProfiles.value, reportReviews.value)
    payload.include_quality_page = includeQualityPage.value
    if (batchFormat.value !== 'excel') payload.report_style = reportStyle.value
    const response = await fetch(`/local-api/nutrition/jobs/${jobId.value}/reports/batch`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
    })
    if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || '批量报告生成失败') }
    const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement('a')
    link.href = url; link.download = decodeURIComponent(response.headers.get('X-Report-Filename') || '全部营养报告.zip')
    document.body.appendChild(link); link.click(); link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1500)
    const failures = Number(response.headers.get('X-Report-Failure-Count') || 0)
    batchMessage.value = `已处理 ${response.headers.get('X-Report-Person-Count')} 人，成功 ${response.headers.get('X-Report-Success-Count')} 份文件。ZIP 已开始下载。`
    if (failures) batchError.value = `${failures} 份文件未生成，请查看 ZIP 内“导出清单.txt”的具体原因，补齐后重试。`
  } catch (error) { batchError.value = error.message || '批量报告生成失败' }
  finally { batchGenerating.value = false }
}
async function generateReport(format) {
  if (!selected.value || !jobId.value) return
  reportGenerating.value = format; reportErrorMessage.value = ''; reportSuccessMessage.value = ''
  try {
    reportProfiles.value[selected.value.id] = { ...reportProfile.value }; reportReviews.value[selected.value.id] = copyReportReview(reportReview.value)
    const response = await fetch(`/local-api/nutrition/jobs/${jobId.value}/report`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ person: selected.value, format, include_quality_page: includeQualityPage.value, ...(format === 'pdf' ? { report_style: reportStyle.value } : {}), user_overrides: { ...reportProfile.value, bmi: bmiValue.value }, report_date: selected.value.general?.调查日期 || '', auto_evaluation: Object.keys(manualEvaluationsPayload()).length === 0, manual_evaluations: manualEvaluationsPayload() })
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
watch([nutritionPersonSearch, nutritionPageSize], () => { nutritionPage.value = 1; ensureNutritionSelectionOnPage() })
watch(nutritionPageCount, (pageCount) => { if (nutritionPage.value > pageCount) nutritionPage.value = pageCount })
onMounted(resumeLatestNutritionJob)
</script>
