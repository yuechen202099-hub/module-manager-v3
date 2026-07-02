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

for (const token of [
  'ProjectReadinessActionCount',
  'ProjectReadinessSummaryItem',
  'ProjectReadinessSummaryList',
  'projectName',
  'projectStatus',
  'actionCounts',
]) {
  if (!typesSource.includes(token)) fail(`types.ts missing readiness summary token: ${token}`)
}

for (const token of [
  'type BackendProjectReadinessSummaryItem',
  'type BackendProjectReadinessActionCount',
  'type BackendProjectReadinessSummaryList',
  'function mapProjectReadinessSummaryList',
  'export async function fetchProjectReadinessSummary',
  '/projects/readiness/summary',
  'action_counts',
  'project_name',
  'not_ready',
]) {
  if (!servicesSource.includes(token)) fail(`services.ts missing readiness summary token: ${token}`)
}

for (const token of [
  'fetchProjectReadinessSummary',
  'ProjectReadinessSummaryList',
  'projectReadinessSummary',
  'loadProjectReadinessSummary',
  'readiness-summary-band',
  'readiness-action-todos',
  'topReadinessActionCounts',
  'readinessActionCountText',
  'selectedReadinessAction',
  'filteredProjects',
  'applyReadinessActionFilter',
  'clearReadinessActionFilter',
  'readinessActionFilterText',
  ':data="filteredProjects"',
  '@click="applyReadinessActionFilter(item.action)"',
  'project-list-readiness-cell',
  '上线状态',
  '接入待办',
  '筛选中',
  '清除筛选',
  '可接入',
  '需补齐',
  '通过',
]) {
  if (!projectsSource.includes(token)) fail(`ProjectsView.vue missing readiness summary token: ${token}`)
}

const operationsStart = projectsSource.indexOf('<ElTableColumn label="操作"')
const operationsEnd = projectsSource.indexOf('</ElTableColumn>', operationsStart)
if (operationsStart < 0 || operationsEnd < 0) fail('ProjectsView.vue operation column could not be located')

const operationColumnSource = projectsSource.slice(operationsStart, operationsEnd)
if (operationColumnSource.includes('上线状态') || operationColumnSource.includes('readiness-summary-band')) {
  fail('ProjectsView.vue must show readiness summary in the list, not as another row operation')
}

console.log('[OK] Project readiness summary list is wired to the frontend.')
