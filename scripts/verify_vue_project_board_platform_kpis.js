const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const source = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ProjectBoardView.vue'), 'utf8')

const checks = [
  {
    ok:
      source.includes('fetchProjects') &&
      source.includes('platformProject') &&
      source.includes('platformKpiCards') &&
      source.includes('route.query.project_id'),
    message: 'ProjectBoardView must load the active platform project from the project_id query.',
  },
  {
    ok:
      source.includes('platform-kpi-band') &&
      source.includes('初始工单') &&
      source.includes('系统外接入') &&
      source.includes('待审') &&
      source.includes('退回返工') &&
      source.includes('通过归档') &&
      source.includes('未就绪'),
    message: 'ProjectBoardView must render platform KPI cards for project operations stages.',
  },
]

const failures = checks.filter((check) => !check.ok)
if (failures.length) {
  console.error(failures.map((failure) => failure.message).join('\n'))
  process.exit(1)
}

console.log('[OK] Vue project board exposes platform KPI cockpit cards.')
