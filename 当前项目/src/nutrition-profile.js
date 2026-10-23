// Shared person fields are stored once, on the reviewed questionnaire.
export const SPORT_OPTIONS = Object.freeze(['足球', '篮球', '体操'])
const INTERNAL_TYPES = { 足球: 'team', 篮球: 'team', 体操: 'strength' }
const FIELDS = { name: '姓名', age: '年龄', projectType: '项目种类', trainingPhase: '训练阶段',
  trainingYears: '训练年限', currentStatus: '当前状态', gender: '性别', height: '身高',
  weight: '体重', fatFreeMass: '去脂体重', activityLevel: '运动量', foodTargetScale: '食物摄入倍率' }
const gender = value => ['女', '女性', 'female', 'f'].includes(String(value || '').toLowerCase()) ? 'female'
  : ['男', '男性', 'male', 'm'].includes(String(value || '').toLowerCase()) ? 'male' : ''

export function canonicalSport(value) {
  const text = String(value || '').trim()
  return ({ 足球队: '足球', 女足: '足球', 女子足球: '足球', 篮球队: '篮球', 女篮: '篮球', 女子篮球: '篮球', 体操队: '体操' })[text]
    || (SPORT_OPTIONS.includes(text) ? text : '')
}

export function profileFromGeneral(general = {}, cached = {}) {
  const result = { ...cached }
  for (const [field, key] of Object.entries(FIELDS)) {
    if (Object.hasOwn(general, key)) result[field] = general[key]
    else if (!Object.hasOwn(result, field)) result[field] = ''
  }
  result.projectType = canonicalSport(result.projectType)
  result.athleteType = INTERNAL_TYPES[result.projectType] || ''
  result.gender = gender(result.gender)
  if (!Object.hasOwn(general, '训练阶段') && !cached.trainingPhase) {
    const status = String(general['当前状态'] || '').trim()
    result.trainingPhase = ({ 正常训练: 'training', 训练期: 'training', 比赛期: 'competition', 赛期: 'competition' })[status]
      ?? (status ? '' : 'training')
  }
  return result
}

export function syncProfileToGeneral(profile, general) {
  for (const [field, key] of Object.entries(FIELDS)) {
    if (!Object.hasOwn(profile, field)) continue
    let value = profile[field]
    if (field === 'projectType') value = canonicalSport(value)
    if (field === 'gender') {
      if (gender(general[key]) === gender(value)) continue
      value = ({ female: '女', male: '男' })[gender(value)] || ''
    }
    if (!Object.hasOwn(general, key) && (value === '' || value == null)) continue
    if (general[key] !== value) general[key] = value
  }
  const type = INTERNAL_TYPES[canonicalSport(profile.projectType)] || ''
  if (type && general['运动类型'] !== type) general['运动类型'] = type
  else if (!type && Object.hasOwn(general, '运动类型')) general['运动类型'] = ''
  profile.athleteType = type
}
