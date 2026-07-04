const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const templatesSource = fs.readFileSync(path.join(root, 'v2-api', 'app', 'services', 'platform', 'templates.py'), 'utf8')
const verifierSource = fs.readFileSync(
  path.join(root, 'scripts', 'verify_platform_external_completed_hierarchy_validation.py'),
  'utf8',
)

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const backendTokens = [
  ['def _validate_conditional_template_fields', 'template validation must define conditional hierarchy helper'],
  ['def _required_when_matches', 'template validation must define required_when matcher'],
  ['missing_conditional_field', 'template validation must report missing conditional child fields'],
  ['template_type == "external_completed"', 'conditional validation must be scoped to external_completed'],
  ['field.get("required_when")', 'conditional validation must inspect required_when fields'],
  ['_validate_conditional_template_fields(', 'validate_project_template_workbook must call conditional helper'],
]

for (const [token, message] of backendTokens) {
  if (!templatesSource.includes(token)) fail(message)
}

const verifierTokens = [
  ['Communication module replace', 'verifier must create a confirmation field'],
  ['Old communication module', 'verifier must check old device warning'],
  ['New communication module', 'verifier must check new device warning'],
  ['Communication module photo', 'verifier must check photo warning'],
  ['"replace"', 'verifier must trigger conditional validation'],
  ['"keep"', 'verifier must prove untriggered condition does not warn'],
]

for (const [token, message] of verifierTokens) {
  if (!verifierSource.includes(token)) fail(message)
}

console.log('[OK] external completed template hierarchy validation guard is wired.')
