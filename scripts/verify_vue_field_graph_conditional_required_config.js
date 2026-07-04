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
  'requiredWhenCandidateFields',
  'selectedRequiredWhenFieldKey',
  'updateRequiredWhenField',
  'clearRequiredWhenField',
  'conditional-required-row',
  'condition-summary-card',
  'accessory_replace_confirm',
  'field.requiredWhen?.fieldKey',
  'updateSelectedField({ requiredWhen:',
  'updateSelectedField({ requiredWhen: undefined })',
  ':disabled="!requiredWhenCandidateFields.length"',
  'v-for="option in requiredWhenCandidateFields"',
]

for (const token of requiredTokens) {
  if (!source.includes(token)) {
    fail(`FieldGraphDesigner.vue missing conditional required config token: ${token}`)
  }
}

console.log('[OK] Vue field graph conditional required config is wired.')
