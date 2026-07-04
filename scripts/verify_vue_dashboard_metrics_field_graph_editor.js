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

const fieldGraphSource = read('v2-web/src/components/project-fields/FieldGraphDesigner.vue')
const projectsViewSource = read('v2-web/src/views/ProjectsView.vue')

requireCondition(
  fieldGraphSource.includes('type DashboardMetricForm') &&
    fieldGraphSource.includes('dashboardMetrics?: DashboardMetricForm[]') &&
    fieldGraphSource.includes("(event: 'update-dashboard-metrics', payload: DashboardMetricForm[]): void"),
  'FieldGraphDesigner must accept and emit dashboard metric form objects',
)

requireCondition(
  fieldGraphSource.includes('dashboardMetricPresetCards') &&
    fieldGraphSource.includes('selectedDashboardMetricKeys') &&
    fieldGraphSource.includes('toggleDashboardMetric') &&
    fieldGraphSource.includes('dashboard-metric-editor-card'),
  'FieldGraphDesigner must expose selectable dashboard metric preset cards',
)

requireCondition(
  fieldGraphSource.includes('驾驶舱指标口径') &&
    fieldGraphSource.includes('项目进度') &&
    fieldGraphSource.includes('交付能力') &&
    fieldGraphSource.includes('现场采集') &&
    fieldGraphSource.includes('审阅质量') &&
    fieldGraphSource.includes('KPI 效率'),
  'dashboard metric editor must use operator-facing metric categories',
)

requireCondition(
  projectsViewSource.includes(':dashboard-metrics="createForm.dashboardMetrics"') &&
    projectsViewSource.includes('@update-dashboard-metrics="handleCreateDashboardMetricsUpdate"') &&
    projectsViewSource.includes(':dashboard-metrics="schemaForm.dashboardMetrics"') &&
    projectsViewSource.includes('@update-dashboard-metrics="handleSchemaDashboardMetricsUpdate"'),
  'ProjectsView must wire dashboard metric editor props and update events for create and schema forms',
)

requireCondition(
  projectsViewSource.includes('function handleCreateDashboardMetricsUpdate(metrics: ProjectDashboardMetric[])') &&
    projectsViewSource.includes('function handleSchemaDashboardMetricsUpdate(metrics: ProjectDashboardMetric[])'),
  'ProjectsView must copy dashboard metric updates into both form states',
)

console.log('OK: Vue dashboard metrics field graph editor is wired.')
