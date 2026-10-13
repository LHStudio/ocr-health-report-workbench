// Display-only union. Do not alter evaluator rows or manual-review storage.
export function evaluationRows(data) {
  const rows = new Map()
  for (const section of ['athlete_evaluation', 'food_standard_evaluation']) {
    for (const row of data?.[section]?.rows || []) rows.set(row.key, row)
  }
  return [...rows.values()]
}

export function evaluationWarnings(data) {
  return [...new Set(['athlete_evaluation', 'food_standard_evaluation'].flatMap(section => data?.[section]?.warnings || []))]
    .filter(note => !['原文未明确年龄分界', '每项定量规则达标'].some(text => note.includes(text)))
}

export function finalEvaluation(row, review = {}) {
  const field = ['protein', 'carbohydrate', 'fat', 'calcium'].includes(row.key)
    ? `${row.key}Evaluation` : `standard_${row.key}Evaluation`
  return Object.hasOwn(review, field) ? review[field] : row.evaluation
}
