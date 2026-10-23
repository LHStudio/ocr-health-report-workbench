import { profileFromGeneral } from './nutrition-profile.js'
// Preserve deliberate edits, but recompute machine drafts against the current input.
export function buildBatchPayload(people, format, profiles, reviews) {
  const manual = {}
  for (const person of people) {
    const review = reviews[person.id]
    if (!review?.machineSeeded) continue
    const previous = review.lastMachine || {}
    const changes = {}
    for (const [category, value] of Object.entries(review.categoryEvaluations || {})) {
      if (value !== previous.categoryEvaluations?.[category]) {
        ;(changes.categoryEvaluations ||= {})[category] = value
      }
    }
    for (const [key, value] of Object.entries(review)) {
      if (key === 'categoryEvaluations' || !(key.endsWith('Evaluation') || ['overallSuggestions', 'interpretation'].includes(key))) continue
      if (value === previous[key]) continue
      if (key.startsWith('standard_')) {
        ;(changes.standardEvaluations ||= {})[key.slice(9, -10)] = value
      } else changes[key] = value
    }
    if (Object.keys(changes).length) manual[person.id] = changes
  }
  const currentProfiles = Object.fromEntries(people.map(person => [person.id,
    profileFromGeneral(person.general || {}, profiles?.[person.id] || {})]))
  return { people, format, profiles: currentProfiles, reviews: manual }
}
