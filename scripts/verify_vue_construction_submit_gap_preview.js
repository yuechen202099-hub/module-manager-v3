const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const viewPath = path.join(root, 'v2-web', 'src', 'views', 'ConstructionView.vue')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

if (!fs.existsSync(viewPath)) fail('ConstructionView.vue must exist')

const view = fs.readFileSync(viewPath, 'utf8')
const compactView = view.replace(/\s+/g, '')

const requiredTokens = [
  'missingRequiredKpiFieldLabels',
  'constructionSubmitGapGroups',
  'constructionSubmitBlocked',
  '缺少KPI',
  '施工提交缺口',
  'construction-submit-gap',
  ':disabled="constructionSubmitBlocked"',
]

for (const token of requiredTokens) {
  if (!view.includes(token)) fail(`ConstructionView.vue missing submit gap token: ${token}`)
}

const behaviorSnippets = [
  'activePlatformWorkOrder.value?.kpiValues[field.key]',
  'requiredConstructionFieldLabels.value',
  'missingRequiredSlots.value',
  'missingRequiredKpiFieldLabels.value',
]

for (const snippet of behaviorSnippets) {
  if (!view.includes(snippet)) fail(`ConstructionView.vue missing submit gap behavior: ${snippet}`)
}

if (!compactView.includes('platformKpiInputFields.filter')) {
  fail('ConstructionView.vue must derive KPI submit gaps from platformKpiInputFields.')
}

const disabledCount = (view.match(/:disabled="constructionSubmitBlocked"/g) || []).length
if (disabledCount < 2) {
  fail('Both inline and drawer platform submit buttons must use constructionSubmitBlocked.')
}

console.log('[OK] Vue construction submit gap preview is wired.')
