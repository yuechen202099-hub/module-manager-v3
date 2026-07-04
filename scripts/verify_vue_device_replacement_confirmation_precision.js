const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const fieldDesigner = fs.readFileSync(
  path.join(root, 'v2-web', 'src', 'components', 'project-fields', 'FieldGraphDesigner.vue'),
  'utf8',
)
const projectsView = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

function between(source, startToken, endToken) {
  const start = source.indexOf(startToken)
  if (start === -1) fail(`missing start token: ${startToken}`)
  const end = source.indexOf(endToken, start + startToken.length)
  if (end === -1) fail(`missing end token after ${startToken}: ${endToken}`)
  return source.slice(start, end)
}

function requirePreciseConfirmationDetector(source, startToken, endToken, label) {
  const body = between(source, startToken, endToken)
  if (body.includes("field.captureMethod === 'select'")) {
    fail(`${label} must not treat every select field as an accessory replacement confirmation`)
  }
  if (body.includes("field.dataType === 'enum'")) {
    fail(`${label} must not treat every enum field as an accessory replacement confirmation`)
  }
  if (!body.includes("field.relationRole === 'accessory_replace_confirm'")) {
    fail(`${label} must preserve explicit accessory_replace_confirm relation role`)
  }
  if (!body.includes("是否更换") || !body.includes("确认是否更换")) {
    fail(`${label} must still detect operator labels that clearly mean replacement confirmation`)
  }
}

requirePreciseConfirmationDetector(
  fieldDesigner,
  'function isReplacementConfirmationField(field: FieldForm) {',
  'function isRequiredReplacementField',
  'FieldGraphDesigner',
)

requirePreciseConfirmationDetector(
  projectsView,
  'function isSaveReplacementConfirmationField(field: CreateFieldForm) {',
  'function isSaveRecoveredDeviceField',
  'ProjectsView save gate',
)

console.log('[OK] Vue device replacement confirmation detection is precise.')
