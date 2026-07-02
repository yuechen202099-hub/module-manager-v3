const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8')

const types = read('v2-web/src/api/types.ts')
const services = read('v2-web/src/api/services.ts')
const projects = read('v2-web/src/views/ProjectsView.vue')

const checks = [
  {
    ok:
      types.includes('initialWorkOrders: number') &&
      types.includes('externalCompleted: number') &&
      types.includes('pendingReview: number') &&
      types.includes('returnedRework: number') &&
      types.includes('approvedArchive: number') &&
      types.includes('notReady: number'),
    message: 'Project task KPI frontend types must expose platform import and review-stage splits.',
  },
  {
    ok:
      services.includes('initial_work_orders?: number') &&
      services.includes('external_completed?: number') &&
      services.includes('returned_rework?: number') &&
      services.includes('approved_archive?: number') &&
      services.includes('initialWorkOrders: Number(raw.initial_work_orders || 0)') &&
      services.includes('returnedRework: Number(raw.returned_rework || 0)'),
    message: 'Project task KPI service mapping must convert backend platform KPI fields.',
  },
  {
    ok:
      projects.includes('初始 {{ row.tasks?.initialWorkOrders || 0 }}') &&
      projects.includes('接入 {{ row.tasks?.externalCompleted || 0 }}') &&
      projects.includes('返工 {{ row.tasks?.returnedRework || 0 }}') &&
      projects.includes('通过 {{ row.tasks?.approvedArchive || 0 }}') &&
      projects.includes('未就绪 {{ row.tasks?.notReady || 0 }}'),
    message: 'Projects list must render platform KPI splits in the task center column.',
  },
]

const failures = checks.filter((check) => !check.ok)
if (failures.length) {
  console.error(failures.map((failure) => failure.message).join('\n'))
  process.exit(1)
}

console.log('[OK] Vue projects page exposes platform KPI splits.')
