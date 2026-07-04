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
  if (start === -1) fail(`missing scope start token: ${startToken}`)
  const end = source.indexOf(endToken, start + startToken.length)
  if (end === -1) fail(`missing scope end token: ${endToken}`)
  return source.slice(start, end)
}

const designerTokens = [
  'selectedFieldHierarchyHint',
  '主设备 · 更换前',
  '主设备 · 更换后',
  '任务对象下的附属设备',
  '换主设备时，附属设备不能直接平铺',
  'terminal-unconditional-accessory',
  'field-hierarchy-hint-card',
]

for (const token of designerTokens) {
  if (!fieldDesigner.includes(token)) fail(`FieldGraphDesigner.vue missing terminal hierarchy token: ${token}`)
}

const fieldGraphIssueList = between(
  fieldDesigner,
  'function fieldGraphHierarchyIssueList(fields: FieldForm[]): FieldHierarchyReadinessIssue[] {',
  'function backendDeviceHierarchyEvidenceList',
)
if (!fieldGraphIssueList.includes('unconditionalMainAccessoryFields')) {
  fail('field graph readiness must compute unconditional accessory fields under main-device replacement')
}
if (!fieldGraphIssueList.includes('terminal-unconditional-accessory')) {
  fail('field graph readiness must report flat terminal accessory fields')
}

const saveIssueList = between(
  projectsView,
  'function fieldHierarchySaveIssues(form: WorkItemSchemaForm) {',
  'function validateFieldHierarchyBeforeSave',
)
if (!saveIssueList.includes('unconditionalMainAccessoryFields')) {
  fail('project save gate must compute unconditional accessory fields under main-device replacement')
}
if (!saveIssueList.includes('换终端的附属设备不能直接平铺')) {
  fail('project save gate must explain terminal accessory confirmation before save')
}

console.log('[OK] terminal accessory confirmation gate is explicit in the field graph and save gate.')
