const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const graphSource = fs.readFileSync(
  path.join(root, 'v2-web', 'src', 'components', 'project-fields', 'FieldGraphDesigner.vue'),
  'utf8',
)
const projectsSource = fs.readFileSync(
  path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue'),
  'utf8',
)

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const graphTokens = [
  ['ReplacementHierarchyTemplateCard', 'field graph must define visible replacement hierarchy template cards'],
  ['field-replacement-template-panel', 'field graph must render a replacement hierarchy template panel'],
  ['apply-replacement-template', 'field graph must emit a template apply event'],
  ['module-replacement', 'field graph must expose the module replacement hierarchy template'],
  ['terminal-replacement', 'field graph must expose the terminal replacement hierarchy template'],
  ['设备更换层级模板', 'field graph must label the template panel in operator language'],
]

for (const [token, message] of graphTokens) {
  if (!graphSource.includes(token)) fail(message)
}

const projectTokens = [
  ['type ReplacementHierarchyTemplateId', 'projects view must type replacement hierarchy template ids'],
  ['knownReplacementTemplateFieldKeys', 'projects view must know which fields belong to replacement templates'],
  ['applyReplacementHierarchyTemplate', 'projects view must merge template fields into the current schema form'],
  ['handleCreateReplacementTemplateApply', 'new project field graph must apply hierarchy templates'],
  ['handleSchemaReplacementTemplateApply', 'existing draft schema field graph must apply hierarchy templates'],
  ['@apply-replacement-template="handleCreateReplacementTemplateApply"', 'new project field graph must wire the template apply event'],
  ['@apply-replacement-template="handleSchemaReplacementTemplateApply"', 'schema editor field graph must wire the template apply event'],
]

for (const [token, message] of projectTokens) {
  if (!projectsSource.includes(token)) fail(message)
}

console.log('[OK] Vue replacement hierarchy templates can be applied from the field graph.')
