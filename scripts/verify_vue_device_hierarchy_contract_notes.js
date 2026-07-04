const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const fieldGraphSource = fs.readFileSync(
  path.join(root, 'v2-web', 'src', 'components', 'project-fields', 'FieldGraphDesigner.vue'),
  'utf8',
)

function requireIncludes(source, token, message) {
  if (!source.includes(token)) {
    console.error(`[FAIL] ${message}`)
    process.exit(1)
  }
}

requireIncludes(
  fieldGraphSource,
  'backendDeviceHierarchyContractNotes',
  'field graph must derive backend hierarchy contract notes',
)
requireIncludes(
  fieldGraphSource,
  'field-backend-hierarchy-contract',
  'field graph must render the backend hierarchy contract as a visible block',
)
requireIncludes(
  fieldGraphSource,
  '后端层级口径',
  'field graph must label the backend hierarchy contract in operator language',
)
requireIncludes(
  fieldGraphSource,
  '任务对象下更换附属设备',
  'field graph must preserve the module replacement hierarchy wording',
)
requireIncludes(
  fieldGraphSource,
  '确认附属设备是否更换',
  'field graph must preserve the terminal replacement hierarchy wording',
)

console.log('[OK] Vue field graph shows backend device hierarchy contract notes.')
