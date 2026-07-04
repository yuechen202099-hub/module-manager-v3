const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const reviewSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ReviewView.vue'), 'utf8')
const taskHallSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'TaskHallView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requiredTokens = [
  ['function reviewEvidenceIntentLabel', 'review view must compute evidence intent labels'],
  ['function reviewEvidenceIntentType', 'review view must compute evidence intent tag types'],
  ['class="platform-review-intent-tag"', 'review rows must render intent tags'],
  ['title="审阅证据意图"', 'review intent tags must name their purpose'],
  ['主设备本体', 'review labels must identify main replacement devices'],
  ['任务对象下的附属设备', 'review labels must identify accessories under the task object'],
  ['附属设备确认', 'review labels must identify accessory replacement confirmations'],
  ['条件补采', 'review labels must identify conditional follow-up evidence'],
  ['照片证据', 'review labels must identify photo evidence'],
  ['KPI资料', 'review labels must identify KPI evidence'],
  ['uploaded_at', 'review labels must treat upload time as KPI evidence'],
  ['reviewEvidenceIntentLabel(field)', 'field rows must display intent labels'],
  ['reviewEvidenceIntentLabel(slot)', 'photo rows must display intent labels'],
  ['reviewEvidenceIntentType(field)', 'field rows must color intent labels'],
  ['reviewEvidenceIntentType(slot)', 'photo rows must color intent labels'],
  ['field.requiredWhen?.fieldKey', 'conditional fields must be treated as conditional follow-up evidence'],
  ['slot.requiredWhen?.fieldKey', 'conditional photos must be treated as conditional follow-up evidence'],
]

for (const [token, message] of requiredTokens) {
  if (!reviewSource.includes(token)) fail(message)
}

const taskHallRequiredTokens = [
  ['type PlatformReviewEvidenceIntentItem', 'task hall review must define evidence intent item type'],
  ['const platformReviewKpiEvidenceRows', 'task hall review must expose KPI evidence rows'],
  ['function platformReviewEvidenceIntentLabel', 'task hall review must compute evidence intent labels'],
  ['function platformReviewEvidenceIntentType', 'task hall review must compute evidence intent tag types'],
  ['class="platform-review-intent-tag"', 'task hall review rows must render intent tags'],
  ['title="审阅证据意图"', 'task hall review intent tags must name their purpose'],
  ['主设备本体', 'task hall review labels must identify main replacement devices'],
  ['任务对象下的附属设备', 'task hall review labels must identify accessories under the task object'],
  ['附属设备确认', 'task hall review labels must identify accessory replacement confirmations'],
  ['条件补采', 'task hall review labels must identify conditional follow-up evidence'],
  ['照片证据', 'task hall review labels must identify photo evidence'],
  ['KPI资料', 'task hall review labels must identify KPI evidence'],
  ['uploaded_at', 'task hall review labels must treat upload time as KPI evidence'],
  ['platformReviewEvidenceIntentLabel(field)', 'task hall field rows must display intent labels'],
  ['platformReviewEvidenceIntentLabel(slot)', 'task hall photo rows must display intent labels'],
  ['platformReviewEvidenceIntentLabel(row)', 'task hall KPI rows must display intent labels'],
  ['platformReviewEvidenceIntentType(field)', 'task hall field rows must color intent labels'],
  ['platformReviewEvidenceIntentType(slot)', 'task hall photo rows must color intent labels'],
  ['platformReviewEvidenceIntentType(row)', 'task hall KPI rows must color intent labels'],
  ['field.requiredWhen?.fieldKey', 'task hall conditional fields must be treated as conditional follow-up evidence'],
  ['slot.requiredWhen?.fieldKey', 'task hall conditional photos must be treated as conditional follow-up evidence'],
]

for (const [token, message] of taskHallRequiredTokens) {
  if (!taskHallSource.includes(token)) fail(message)
}

console.log('[OK] Vue review hierarchy intent labels are visible.')
