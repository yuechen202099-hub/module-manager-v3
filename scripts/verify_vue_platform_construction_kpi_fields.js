const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const services = fs.readFileSync(path.join(root, 'v2-web', 'src', 'api', 'services.ts'), 'utf8')
const types = fs.readFileSync(path.join(root, 'v2-web', 'src', 'api', 'types.ts'), 'utf8')
const view = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ConstructionView.vue'), 'utf8')

const checks = [
  {
    ok:
      services.includes('kpi_values') &&
      services.includes('kpiValues: mapStringRecord(raw.kpi_values)') &&
      types.includes('kpiValues: Record<string, string>'),
    message: 'Platform construction work orders must map backend kpi_values into frontend kpiValues.',
  },
  {
    ok:
      services.includes('kpi_ready') &&
      services.includes('old_device_recovered') &&
      services.includes('average_online_duration_minutes') &&
      types.includes('kpiReady') &&
      types.includes('oldDeviceRecovered') &&
      types.includes('averageOnlineDurationMinutes'),
    message: 'Project task KPI summary fields must be exposed to the frontend.',
  },
  {
    ok:
      view.includes('platformKpiInputFields') &&
      view.includes('KPI 必备资料') &&
      view.includes('安装时间') &&
      view.includes('完成时间') &&
      view.includes('在线时长（分钟）') &&
      view.includes('旧设备回收') &&
      view.includes('platformWorkOrderKpiLine'),
    message: 'ConstructionView must show required platform KPI collection fields and status.',
  },
]

const failures = checks.filter((check) => !check.ok)
if (failures.length) {
  console.error(failures.map((failure) => failure.message).join('\n'))
  process.exit(1)
}

console.log('[OK] Vue construction page preserves platform KPI collection fields.')
