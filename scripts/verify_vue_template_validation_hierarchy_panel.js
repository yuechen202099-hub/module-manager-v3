const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const source = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requiredTokens = [
  ['const hierarchyValidationItems', 'projects view must compute hierarchy validation items'],
  ["item.code === 'missing_conditional_field'", 'hierarchy panel must use backend conditional evidence code'],
  ['function validationIssueRowLabel', 'projects view must format validation row labels'],
  ['层级证据缺口', 'validation dialog must expose hierarchy gap heading'],
  ['条件采集缺失', 'validation dialog must explain conditional evidence gaps'],
  ['validation-hierarchy-panel', 'validation dialog must style the hierarchy gap panel'],
  ['validation-hierarchy-list', 'validation dialog must style hierarchy gap rows'],
]

for (const [token, message] of requiredTokens) {
  if (!source.includes(token)) fail(message)
}

console.log('[OK] Vue template validation hierarchy panel is visible.')
