const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), 'utf8')
}

function requireCondition(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

const typesSource = read('v2-web/src/api/types.ts')
const servicesSource = read('v2-web/src/api/services.ts')
const projectsViewSource = read('v2-web/src/views/ProjectsView.vue')
const projectBoardSource = read('v2-web/src/views/ProjectBoardView.vue')

requireCondition(
  typesSource.includes('export type ProjectDashboardMetric') &&
    typesSource.includes('dashboardMetrics?: ProjectDashboardMetric[]'),
  'ProjectWorkItemSchema must expose dashboardMetrics as ProjectDashboardMetric[]',
)

requireCondition(
  servicesSource.includes('type BackendProjectDashboardMetric') &&
    servicesSource.includes('dashboard_metrics?: BackendProjectDashboardMetric[]'),
  'backend project schema type must model dashboard metric objects',
)

requireCondition(
  servicesSource.includes('function mapDashboardMetric(') &&
    servicesSource.includes('function mapDashboardMetricForCreate(') &&
    servicesSource.includes('(raw.dashboard_metrics || [])') &&
    servicesSource.includes('dashboard_metrics: (schema.dashboardMetrics || [])'),
  'service mapper must preserve dashboard metric objects in both directions',
)

requireCondition(
  projectsViewSource.includes('dashboardMetrics: ProjectDashboardMetric[]') &&
    projectsViewSource.includes('createForm.dashboardMetrics = []') &&
    projectsViewSource.includes('schemaForm.dashboardMetrics = schema?.dashboardMetrics?.length') &&
    projectsViewSource.includes('dashboardMetrics: [...form.dashboardMetrics]'),
  'project schema forms must keep dashboard metrics during save',
)

requireCondition(
  projectBoardSource.includes('platformDashboardMetricCards') &&
    projectBoardSource.includes('dashboardMetricHelper') &&
    projectBoardSource.includes('platform-dashboard-metric-card') &&
    projectBoardSource.includes('字段配置看板口径'),
  'project board must render configured dashboard metric cards',
)

console.log('OK: Vue dashboard metrics schema contract is wired')
