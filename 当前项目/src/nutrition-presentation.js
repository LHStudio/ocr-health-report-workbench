// Display-only union. Do not alter evaluator rows or manual-review storage.
export function evaluationAlertClass(value) {
  if (['不足', '严重不足', '过少', '能量占比偏低', '占比偏低'].includes(String(value ?? '').trim())) return 'evaluation-deficit'
  return ['按照运动情况适当补充运动饮料', '偏多', '过多', '建议尽量不吃', '不建议吃零食', '能量占比偏低', '能量占比偏高', '占比偏低', '占比偏高'].includes(String(value ?? '').trim()) ? 'evaluation-alert' : ''
}

export function cleanDisplayText(text = '') {
  for (const [oldText, newText] of [
    ['；参数来自用户提供文档，需营养专业人员审核。', ''],
    ['，因此谷类占比上限为80%，不是必须达到80%。', '。'],
    ['；采用最低量规则，不以先前500g封顶。', '。'],
    ['；显式克数不二次折算', ''],
  ]) text = text.replaceAll(oldText, newText)
  return text
}

export function evaluationContext(data) {
  const parts = [data?.athlete_evaluation?.athlete_label || '']
  for (const section of ['athlete_evaluation', 'food_standard_evaluation']) {
    for (const rawNote of data?.[section]?.warnings || []) {
      const note = cleanDisplayText(rawNote)
      if (['仅训练期', '60-70kg标准', '基础膳食参考标准'].includes(note) && !parts.includes(note)) parts.push(note)
    }
  }
  return parts.filter(Boolean).join(' · ')
}

export function evaluationRows(data) {
  const rows = new Map()
  for (const section of ['athlete_evaluation', 'food_standard_evaluation']) {
    for (const row of data?.[section]?.rows || []) rows.set(row.key, { ...row, ...(row.display || {}), note: cleanDisplayText(row.display?.note ?? row.note ?? '') })
  }
  for (const row of reviewCategoryRows(data)) {
    rows.set('category_' + row.key, {key:'category_' + row.key,label:row.label,actual:row.value === '—' ? null : row.value,unit:'g/天',target:'—',gap:null,evaluation:row.machineEvaluation})
  }
  const ordered = [...rows.values()], keys = ['grains_remainder','tubers_energy','beans_energy']
  const staples = keys.map(key => rows.get(key)).filter(Boolean)
  let index = 0
  return ordered.map(row => keys.includes(row.key) ? staples[index++] : row)
}

export function evaluationWarnings(data) {
  const notes = [...new Set(['athlete_evaluation', 'food_standard_evaluation'].flatMap(section => data?.[section]?.warnings || []))]
    .filter(note => !['原文未明确年龄分界', '每项定量规则达标'].some(text => note.includes(text)))
    .filter(note => !['奶粉、奶酪折算鲜奶等价量', '蔬菜最低400g/天'].some(text => note.startsWith(text)))
    .filter(note => !note.includes('%') && !note.includes('优质蛋白=') && !note.includes('水产品占比'))
    .map(cleanDisplayText).filter(note => !['仅训练期', '60-70kg标准', '基础膳食参考标准'].includes(note))
  return [...new Set(notes.map(displayWarning).filter(Boolean))]
}

function displayWarning(note) {
  if (note.startsWith('示例食谱脂肪')) return ''
  if (['代表食物估算（需复核）：', '足球训练计划估算：', '篮球训练计划估算：'].some(prefix => note.startsWith(prefix))) return ''
  if (note.startsWith('既有优质蛋白至少一半约束下，示例食谱蛋白质计划点由')) {
    if (note.includes('仍在个人蛋白质参考范围内')) return ''
    if (note.includes('已超个人蛋白质参考上限')) return '示例食谱蛋白质超出个人参考上限，现有食谱约束不相容；请核对约束。'
  }
  return note
}

export function energyDisplayNote(energy) {
  return energy?.reference_type === 'bmr_plus_net'
    ? 'kcal/天 · 静息代谢＋日均运动净消耗'
    : energy?.standard_note || '请选择活动量'
}

export function finalEvaluation(row, review = {}) {
  const field = ['protein', 'carbohydrate', 'fat', 'calcium'].includes(row.key)
    ? `${row.key}Evaluation` : `standard_${row.key}Evaluation`
  const value = Object.hasOwn(review, field) ? review[field] : row.evaluation
  if (row.key === 'category_饮料') return '按照运动情况适当补充运动饮料'
  if (row.key?.startsWith('category_')) {
    const category = row.key.slice('category_'.length)
    return Object.hasOwn(review.categoryEvaluations || {}, category) ? review.categoryEvaluations[category] : row.evaluation
  }
  return row.key === 'snacks' ? '不建议吃零食' : value
}

// A single editable control per food identity. Keep the standard control,
// which already has precedence in PDF/Excel export, not two conflicting aliases.
export const foodReviewAliases = { nuts:'坚果', beans_energy:'豆类', tubers_energy:'薯类', grains_remainder:'谷类', milk:'奶类', eggs:'蛋类', seafood:'水产品', livestock_remainder:'畜禽肉', fruit:'水果', vegetables:'蔬菜', snacks:'零食' }
export function reviewCategoryRows(data) {
  const represented = new Set((data?.food_standard_evaluation?.rows || []).map(row => foodReviewAliases[row.key]))
  return Object.entries(data?.category_result || {}).filter(([key]) => !represented.has(key)).map(([key, info]) => ({key,label:key,value:info?.value ?? '—',machineEvaluation:String(info?.evaluation ?? '').trim()}))
}
export function coalesceReviewAliases(review, data) {
  const next = {...review, categoryEvaluations:{...review.categoryEvaluations}, manualEntryFields:{...review.manualEntryFields}, aliasConflicts:[]}
  if (!review.machineSeeded) return next
  const previous = review.lastMachine || {}
  for (const row of data?.food_standard_evaluation?.rows || []) {
    const category = foodReviewAliases[row.key], field = `standard_${row.key}Evaluation`
    if (!category) continue
    const categoryEdited = Object.hasOwn(next.categoryEvaluations,category) && (next.categoryEvaluations[category] !== previous.categoryEvaluations?.[category] || next.manualEntryFields[`category:${category}`])
    const standardEdited = Object.hasOwn(next,field) && (next[field] !== previous[field] || next.manualEntryFields[`nutrition:${field}`])
    if (categoryEdited && !standardEdited) {
      next[field] = next.categoryEvaluations[category]
      next.manualEntryFields[`nutrition:${field}`] = true
    } else if (categoryEdited && standardEdited && next[field] !== next.categoryEvaluations[category]) next.aliasConflicts.push(category)
  }
  return next
}
