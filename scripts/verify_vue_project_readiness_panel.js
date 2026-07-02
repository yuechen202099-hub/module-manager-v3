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

for (const filePath of [typesPath, servicesPath, projectsViewPath]) {
  if (!fs.existsSync(filePath)) fail(`missing required file: ${path.relative(root, filePath)}`)
}

const typesSource = fs.readFileSync(typesPath, 'utf8')
const servicesSource = fs.readFileSync(servicesPath, 'utf8')
const projectsSource = fs.readFileSync(projectsViewPath, 'utf8')

const requiredTypeTokens = [
  'ProjectReadinessCheckStatus',
  'ProjectReadinessCheck',
  'ProjectReadinessSummary',
  'ProjectReadiness',
  'readinessVersion',
  'nextActions',
]

const requiredServiceTokens = [
  'ProjectReadiness,',
  'type BackendProjectReadiness',
  'type BackendProjectReadinessCheck',
  'function mapProjectReadiness',
  'export async function fetchProjectReadiness',
  '/readiness`',
  'readiness_version',
  'next_actions',
]

const requiredViewTokens = [
  'fetchProjectReadiness',
  'ProjectReadiness',
  'projectReadinessById',
  'loadingReadinessProjectId',
  'schemaProjectReadiness',
  'loadProjectReadiness',
  'readiness-server-panel',
  'readiness-server-summary',
  'readiness-check-list',
  'readiness-next-actions',
  '上线检查',
  '按已保存配置检查字段、证据、KPI 和流程是否可接入',
  'readinessStatusType',
  'readinessSummaryText',
  'readinessCheckLabel',
  'readinessActionText',
]

const requiredBehaviorTokens = [
  'void loadProjectReadiness(project)',
  'schemaProject.value = updatedProject',
  'await loadProjectReadiness(updatedProject)',
  '@click="loadProjectReadiness(schemaProject)"',
]

for (const token of requiredTypeTokens) {
  if (!typesSource.includes(token)) fail(`types.ts missing readiness token: ${token}`)
}

for (const token of requiredServiceTokens) {
  if (!servicesSource.includes(token)) fail(`services.ts missing readiness token: ${token}`)
}

for (const token of requiredViewTokens) {
  if (!projectsSource.includes(token)) fail(`ProjectsView.vue missing readiness panel token: ${token}`)
}

for (const token of requiredBehaviorTokens) {
  if (!projectsSource.includes(token)) fail(`ProjectsView.vue missing readiness behavior token: ${token}`)
}

const operationsStart = projectsSource.indexOf('<ElTableColumn label="操作"')
const operationsEnd = projectsSource.indexOf('<ElDialog', operationsStart)
if (operationsStart < 0 || operationsEnd < 0) fail('ProjectsView.vue operation column could not be located')

const operationColumnSource = projectsSource.slice(operationsStart, operationsEnd)
if (operationColumnSource.includes('上线检查') || operationColumnSource.includes('readiness-server-panel')) {
  fail('ProjectsView.vue must keep readiness inside 字段配置 instead of adding a row-level operation')
}

console.log('[OK] Project readiness panel is wired to the frontend.')
