const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const constructionSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ConstructionView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requiredTokens = [
  ['constructionCollectionIntentLabel', 'construction view must compute collection intent labels'],
  ['constructionCollectionIntentType', 'construction view must compute intent tag types'],
  ['construction-intent-tag', 'construction view must render styled intent tags'],
  ['施工采集意图', 'construction checklist must expose the collection intent label'],
  ['主设备本体', 'construction view must distinguish main device collection'],
  ['任务对象下的附属设备', 'construction view must distinguish accessory under task object'],
  ['附属设备确认', 'construction view must distinguish accessory confirmation'],
  ['条件补采', 'construction view must distinguish conditional accessory collection'],
  ['item.intentLabel', 'site checklist must render item intent labels'],
  ['field.requiredWhen?.fieldKey', 'field intent must respect conditional collection fields'],
  ['slot.requiredWhen?.fieldKey', 'photo intent must respect conditional photo slots'],
]

for (const [token, message] of requiredTokens) {
  if (!constructionSource.includes(token)) fail(message)
}

console.log('[OK] Vue construction hierarchy intent labels are visible.')
