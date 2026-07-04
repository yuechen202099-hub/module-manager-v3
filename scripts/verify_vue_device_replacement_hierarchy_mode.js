const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const graphSource = fs.readFileSync(
  path.join(root, 'v2-web', 'src', 'components', 'project-fields', 'FieldGraphDesigner.vue'),
  'utf8',
)

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requiredTokens = [
  ['replacementHierarchyModeCards', 'field graph must compute replacement hierarchy mode cards'],
  ['deviceReplacementHierarchyMode', 'field graph must classify replacement hierarchy mode'],
  ['accessory_under_task_object', 'field graph must name module/accessory replacement mode'],
  ['main_device_with_accessory_confirmation', 'field graph must name terminal replacement mode'],
  ['任务对象下更换附属设备', 'field graph must explain module replacement hierarchy'],
  ['主设备更换后确认附属设备', 'field graph must explain terminal replacement hierarchy'],
  ['更换层级', 'field graph must show replacement hierarchy heading'],
  ['field-replacement-mode-cards', 'field graph must style replacement hierarchy cards'],
]

for (const [token, message] of requiredTokens) {
  if (!graphSource.includes(token)) fail(message)
}

console.log('[OK] Vue device replacement hierarchy mode is explicit.')
