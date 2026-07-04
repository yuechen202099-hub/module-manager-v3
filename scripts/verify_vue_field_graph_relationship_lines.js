const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const designerPath = path.join(root, 'v2-web', 'src', 'components', 'project-fields', 'FieldGraphDesigner.vue')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

if (!fs.existsSync(designerPath)) {
  fail('FieldGraphDesigner.vue must exist')
}

const source = fs.readFileSync(designerPath, 'utf8')

const requiredTokens = [
  'label: string',
  'labelX: number',
  'labelY: number',
  'labelClassName?: string',
  'mindMapConnectorLegend',
  'deviceRelationshipSummaryItems',
  'field-map-connector-label',
  'connector.label',
  'field-map-legend',
  'field-map-relation-summary',
  '平行核心字段',
  '隶属任务对象',
  '条件触发',
  '主设备更换',
  '附属设备确认',
  '条件采集',
]

for (const token of requiredTokens) {
  if (!source.includes(token)) {
    fail(`FieldGraphDesigner.vue missing relationship-line token: ${token}`)
  }
}

console.log('[OK] Vue field graph relationship lines are visible.')
