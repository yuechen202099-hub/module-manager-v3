const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const constructionPath = path.join(root, 'v2-web', 'src', 'views', 'ConstructionView.vue')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

if (!fs.existsSync(constructionPath)) {
  fail('ConstructionView.vue must exist')
}

const source = fs.readFileSync(constructionPath, 'utf8')

const requiredTokens = [
  'activeConstructionFields',
  'activePhotoSlots',
  'activeConstructionFieldSections',
  'activeConstructionPhotoSections',
  'function platformWorkOrderConditionValues',
  'function platformConstructionFieldsForOrder',
  'function platformConstructionPhotoSlotsForOrder',
  'function isFieldConditionActive',
  'function isFieldConditionActiveForValues',
  'function isPhotoSlotConditionActive',
  'function isPhotoSlotConditionActiveForValues',
  'activeConstructionFields.value.map',
  'activeConstructionFields.value.filter',
  'activePhotoSlots.value.filter',
  'activePhotoSlotKeys',
  'platformConstructionFields.value.filter((field) => isFieldConditionActiveForValues(field, platformWorkOrderConditionValues(order)))',
  'platformConstructionPhotoSlots.value.filter((slot) => isPhotoSlotConditionActiveForValues(slot, platformWorkOrderConditionValues(order)))',
  'selectedFiles.value[slotKey] = null',
  'delete previewUrls.value[slotKey]',
  'clearInactiveConditionalValues',
  'collectFieldValues()',
  'v-for="section in activeConstructionFieldSections"',
  'v-for="photoSection in activeConstructionPhotoSections"',
  'v-for="field in platformConstructionFieldsForOrder(order)"',
  'v-for="slot in platformConstructionPhotoSlotsForOrder(order)"',
  'isFieldConditionActiveForValues(field, draft.field_values || {})',
  'isPhotoSlotConditionActiveForValues(slot, draft.field_values || {})',
]

for (const token of requiredTokens) {
  if (!source.includes(token)) {
    fail(`ConstructionView.vue missing conditional visibility token: ${token}`)
  }
}

console.log('[OK] Vue construction conditional visibility is wired.')
