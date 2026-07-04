const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const designerSource = fs.readFileSync(
  path.join(root, 'v2-web', 'src', 'components', 'project-fields', 'FieldGraphDesigner.vue'),
  'utf8',
)
const projectsSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const designerTokens = [
  ['type BackendDeviceHierarchyReadinessCheck', 'designer must define backend readiness check type'],
  ['type BackendDeviceHierarchyIssue', 'designer must define backend readiness issue type'],
  ['backendReadinessCheck?: BackendDeviceHierarchyReadinessCheck | null', 'designer must accept backend readiness check prop'],
  ['const backendDeviceHierarchyIssues', 'designer must compute backend device hierarchy issues'],
  ['const backendDeviceHierarchyIssueKeys', 'designer must compute backend issue keys'],
  ['function backendDeviceHierarchyIssueList', 'designer must map backend evidence into issues'],
  ['function backendDeviceHierarchyEvidenceList', 'designer must read backend evidence arrays'],
  ['后端上线检查回显', 'designer must render backend readiness echo heading'],
  ['设备更换层级', 'designer must label device hierarchy backend echo'],
  ['后端已通过', 'designer must render backend passed state'],
  ['后端需补齐', 'designer must render backend failed state'],
  ['missing_parent_keys', 'designer must handle missing parent evidence'],
  ['missing_confirmation_keys', 'designer must handle missing confirmation role evidence'],
  ['invalid_conditional_keys', 'designer must handle invalid conditional evidence'],
  ['unconditional_child_keys', 'designer must handle unconditional child evidence'],
  ['confirmation_without_child_keys', 'designer must handle confirmation without child evidence'],
  ['missing_main_accessory_confirmation', 'designer must handle missing main accessory confirmation evidence'],
  ['backend-issue-node', 'designer must highlight backend issue nodes'],
  ['field-backend-readiness-panel', 'designer must render backend readiness panel'],
]

for (const [token, message] of designerTokens) {
  if (!designerSource.includes(token)) fail(message)
}

const projectTokens = [
  ['const schemaDeviceHierarchyReadinessCheck', 'projects view must compute device hierarchy readiness check'],
  ['check.id === \'device_hierarchy\'', 'projects view must select device_hierarchy check'],
  [':backend-readiness-check="schemaDeviceHierarchyReadinessCheck"', 'schema field graph must receive backend readiness check'],
]

for (const [token, message] of projectTokens) {
  if (!projectsSource.includes(token)) fail(message)
}

const issueClassPattern = /:class="\[item\.className,[\s\S]*?backend-issue-node/
if (!issueClassPattern.test(designerSource)) {
  fail('mind map nodes must include backend issue class binding')
}

console.log('[OK] Vue field graph backend readiness echo is wired.')
