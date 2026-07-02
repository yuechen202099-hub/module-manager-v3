const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const viewPath = path.join(root, 'v2-web', 'src', 'views', 'ConstructionView.vue')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

if (!fs.existsSync(viewPath)) fail('ConstructionView.vue must exist')

const viewSource = fs.readFileSync(viewPath, 'utf8')

const requiredTokens = [
  'SiteChecklistItem',
  'siteChecklistItems',
  'fieldChecklistItems',
  'photoChecklistItems',
  'kpiChecklistItems',
  'siteChecklistSummary',
  '施工必采清单',
  '字段配置同步',
  '已完成',
  '待补齐',
  'site-checklist-panel',
  'site-checklist-grid',
  'captureMethodLabel',
  'requiredConstructionFieldLabels',
  'missingRequiredSlots',
  'platformKpiInputFields',
]

for (const token of requiredTokens) {
  if (!viewSource.includes(token)) fail(`ConstructionView.vue missing checklist token: ${token}`)
}

const panelCount = (viewSource.match(/site-checklist-panel/g) || []).length
if (panelCount < 3) {
  fail('ConstructionView.vue must render checklist panel in both inline and drawer forms and define styles')
}

const semanticSnippets = [
  "group: 'field'",
  "group: 'photo'",
  "group: 'kpi'",
  'hasSlotPhoto(activeGroup.value, slot.key)',
  'Boolean(selectedFiles.value[slot.key])',
  'fieldValue(field).trim()',
  'activePlatformWorkOrder.value',
]

for (const snippet of semanticSnippets) {
  if (!viewSource.includes(snippet)) fail(`ConstructionView.vue missing checklist behavior: ${snippet}`)
}

console.log('[OK] Vue construction page consumes configured checklist.')
