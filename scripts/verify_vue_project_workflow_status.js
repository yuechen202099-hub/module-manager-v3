const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const typesPath = path.join(root, 'v2-web', 'src', 'api', 'types.ts')
const servicesPath = path.join(root, 'v2-web', 'src', 'api', 'services.ts')
const projectsViewPath = path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const typesSource = fs.readFileSync(typesPath, 'utf8')
const servicesSource = fs.readFileSync(servicesPath, 'utf8')
const projectsSource = fs.readFileSync(projectsViewPath, 'utf8')

const requiredTypeTokens = [
  'ProjectWorkflowStatus',
  'workflowStatus?: ProjectWorkflowStatus',
  'enabledNodeIds',
  'enabledModuleIds',
  'currentNodeLabel',
  'moduleSyncEnabled',
]

for (const token of requiredTypeTokens) {
  if (!typesSource.includes(token)) fail(`types.ts missing workflow status token: ${token}`)
}

const requiredServiceTokens = [
  'BackendProjectWorkflowStatus',
  'workflow_status?: BackendProjectWorkflowStatus',
  'mapProjectWorkflowStatus',
  'workflowStatus: mapProjectWorkflowStatus',
  'current_node_label',
  'module_sync_enabled',
]

for (const token of requiredServiceTokens) {
  if (!servicesSource.includes(token)) fail(`services.ts missing workflow status token: ${token}`)
}

const requiredProjectTokens = [
  'workflowStatusText',
  'row.workflowStatus',
  '当前流程',
  '节点',
  '同步模块',
]

for (const token of requiredProjectTokens) {
  if (!projectsSource.includes(token)) fail(`ProjectsView.vue missing workflow status token: ${token}`)
}

console.log('[OK] Vue project workflow status is mapped and displayed.')
