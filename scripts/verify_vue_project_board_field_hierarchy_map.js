const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const boardPath = path.join(root, 'v2-web', 'src', 'views', 'ProjectBoardView.vue')
const boardSource = fs.readFileSync(boardPath, 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requiredTokens = [
  ['ProjectFieldDefinition', 'project board must import project field definitions'],
  ['type BoardFieldHierarchyColumn', 'project board must define hierarchy columns'],
  ['const boardFieldHierarchyColumns', 'project board must derive hierarchy columns from saved schema'],
  ['function boardFieldIsMainDeviceReplacement', 'project board must distinguish main device replacement fields'],
  ['function boardFieldIsConditionalAccessory', 'project board must distinguish conditionally collected accessory fields'],
  ['function boardFieldRelationRoleLabel', 'project board must label relation roles'],
  ['function boardFieldCaptureLabel', 'project board must label capture methods'],
  ['function boardFieldRequiredWhenSummary', 'project board must explain conditional accessory rules'],
  ['function boardFieldParentLabel', 'project board must show the parent-child field relationship'],
  ['platform-field-hierarchy-map', 'project board must render a field hierarchy map'],
  ['board-field-column aggregate', 'field map must include aggregate column'],
  ['board-field-column task-core', 'field map must include task core column'],
  ['board-field-column main-device-replacement', 'field map must include main device replacement column'],
  ['board-field-column accessory-confirmation', 'field map must include accessory confirmation column'],
  ['board-field-column conditional-accessory', 'field map must include conditional accessory column'],
  ['board-field-column evidence-stack', 'field map must include evidence column'],
  ['主设备更换', 'field map must label terminal replacement as main-device replacement'],
  ['附属设备确认', 'field map must label accessory replacement confirmations'],
  ['条件补采', 'field map must label conditional accessory follow-up fields'],
  ['任务对象下更换附属设备', 'field map must explain module replacement as accessory replacement under one task object'],
  ['确认附属设备是否更换', 'field map must explain terminal replacement accessory confirmation'],
  ['v-for="column in boardFieldHierarchyColumns"', 'field map must render hierarchy columns'],
  ['v-for="field in column.fields"', 'field map must render fields in each hierarchy column'],
  ['boardFieldRelationRoleLabel(field.relationRole)', 'field map must show role tags'],
  ['boardFieldCaptureLabel(field.captureMethod)', 'field map must show capture method tags'],
  ['boardFieldParentLabel(field)', 'field map must show field parent labels'],
  ['boardFieldRequiredWhenSummary(field)', 'field map must show conditional requirement hints'],
  ['field.requiredWhen?.fieldKey', 'field map must use requiredWhen to connect conditional accessory fields'],
  ['board-field-node-parent', 'field map must style parent relationship rows'],
  ['board-field-node-condition', 'field map must style conditional rows'],
  ['platformProject?.workItemSchema', 'field map must be driven by the saved platform project schema'],
]

for (const [token, message] of requiredTokens) {
  if (!boardSource.includes(token)) fail(message)
}

console.log('[OK] Vue project board field hierarchy map is wired.')
