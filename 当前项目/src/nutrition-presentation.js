// Display-only union. Do not alter evaluator rows or manual-review storage.
export function evaluationAlertClass(value) {
  return ['不足', '过多', '建议尽量不吃', '能量占比偏低', '能量占比偏高', '占比偏低', '占比偏高'].includes(String(value ?? '').trim()) ? 'evaluation-alert' : ''
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
      if (['仅训练期', '60-70kg标准'].includes(note) && !parts.includes(note)) parts.push(note)
    }
  }
  return parts.filter(Boolean).join(' · ')
}

export function evaluationRows(data) {
  const rows = new Map()
  for (const section of ['athlete_evaluation', 'food_standard_evaluation']) {
    for (const row of data?.[section]?.rows || []) rows.set(row.key, { ...row, ...(row.display || {}), note: cleanDisplayText(row.display?.note ?? row.note ?? '') })
  }
  return [...rows.values()]
}

export function evaluationWarnings(data) {
  return [...new Set(['athlete_evaluation', 'food_standard_evaluation'].flatMap(section => data?.[section]?.warnings || []))]
    .filter(note => !['原文未明确年龄分界', '每项定量规则达标'].some(text => note.includes(text)))
    .filter(note => !['奶粉、奶酪折算鲜奶等价量', '蔬菜最低400g/天'].some(text => note.startsWith(text)))
    .filter(note => !note.includes('%') && !note.includes('优质蛋白=') && !note.includes('水产品占比'))
    .map(cleanDisplayText).filter(note => !['仅训练期', '60-70kg标准'].includes(note))
}

export function finalEvaluation(row, review = {}) {
  const field = ['protein', 'carbohydrate', 'fat', 'calcium'].includes(row.key)
    ? `${row.key}Evaluation` : `standard_${row.key}Evaluation`
  const value = Object.hasOwn(review, field) ? review[field] : row.evaluation
  return !['quantity_first', 'quantity_unknown'].includes(row.evaluation_basis) && ['beans_energy', 'tubers_energy', 'grains_remainder'].includes(row.key)
    ? ({ '不足': '能量占比偏低', '过多': '能量占比偏高', '适中': '能量占比适中' }[value] || value) : value
}
