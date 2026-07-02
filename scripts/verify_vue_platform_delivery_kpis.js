const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8')

const projectBoard = read('v2-web/src/views/ProjectBoardView.vue')
const projects = read('v2-web/src/views/ProjectsView.vue')
const services = read('v2-web/src/api/services.ts')
const types = read('v2-web/src/api/types.ts')

const checks = [
  {
    ok:
      types.includes('kpiReady: number') &&
      types.includes('photoTotal: number') &&
      types.includes('oldDeviceRecovered: number') &&
      types.includes('averageOnlineDurationMinutes: number') &&
      types.includes('installerCount: number') &&
      services.includes('kpiReady: Number(raw.kpi_ready || 0)') &&
      services.includes('oldDeviceRecovered: Number(raw.old_device_recovered || 0)') &&
      services.includes('averageOnlineDurationMinutes: Number(raw.average_online_duration_minutes || 0)'),
    message: 'Frontend project task contracts must map construction delivery KPI fields.',
  },
  {
    ok:
      projectBoard.includes('platformDeliveryKpiCards') &&
      projectBoard.includes('交付能力') &&
      projectBoard.includes('KPI资料完整') &&
      projectBoard.includes('旧设备回收') &&
      projectBoard.includes('平均在线时长') &&
      projectBoard.includes('安装人员'),
    message: 'ProjectBoardView must render construction delivery KPI cards in the cockpit.',
  },
  {
    ok:
      projects.includes('platform-delivery-kpi-line') &&
      projects.includes('KPI {{ row.tasks?.kpiReady || 0 }}') &&
      projects.includes('旧设备 {{ row.tasks?.oldDeviceRecovered || 0 }}') &&
      projects.includes('在线 {{ row.tasks?.averageOnlineDurationMinutes || 0 }}分') &&
      projects.includes('人员 {{ row.tasks?.installerCount || 0 }}'),
    message: 'ProjectsView must show construction delivery KPIs in the task center column.',
  },
]

const failures = checks.filter((check) => !check.ok)
if (failures.length) {
  console.error(failures.map((failure) => failure.message).join('\n'))
  process.exit(1)
}

console.log('[OK] Vue project views expose construction delivery KPIs.')
