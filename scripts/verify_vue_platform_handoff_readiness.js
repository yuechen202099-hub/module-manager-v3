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
  'PlatformHandoffReadiness',
  'PlatformProductionBaseline',
  'readyForReviewPackage',
  'readyForProductionMigration',
  'productionSafety',
]) {
  if (!typesSource.includes(token)) fail(`types.ts missing handoff readiness token: ${token}`)
}

for (const token of [
  'type BackendPlatformHandoffReadiness',
  'function mapPlatformHandoffReadiness',
  'export async function fetchPlatformHandoffReadiness',
  '/projects/handoff/readiness',
  'ready_for_review_package',
  'ready_for_production_migration',
  'production_safety',
]) {
  if (!servicesSource.includes(token)) fail(`services.ts missing handoff readiness token: ${token}`)
}

for (const token of [
  'fetchPlatformHandoffReadiness',
  'PlatformHandoffReadiness',
  'platformHandoffReadiness',
  'loadingPlatformHandoffReadiness',
  'loadPlatformHandoffReadiness',
  'handoffReviewStatusText',
  'handoffMigrationStatusText',
  'handoff-readiness-band',
  '交付就绪',
  '可评审包',
  '生产迁移未放行',
  'production/V3/3.0.77',
]) {
  if (!projectsSource.includes(token)) fail(`ProjectsView.vue missing handoff readiness token: ${token}`)
}

const handoffBandStart = projectsSource.indexOf('class="handoff-readiness-band"')
const readinessBandStart = projectsSource.indexOf('class="readiness-summary-band"')
if (handoffBandStart < 0) fail('handoff readiness band is missing')
if (readinessBandStart < 0) fail('readiness summary band is missing')
if (handoffBandStart > readinessBandStart) {
  fail('handoff readiness band should appear before the project readiness summary band')
}

const operationsStart = projectsSource.indexOf('<ElTableColumn label="操作"')
const operationsEnd = projectsSource.indexOf('</ElTableColumn>', operationsStart)
if (operationsStart >= 0 && operationsEnd > operationsStart) {
  const operationColumnSource = projectsSource.slice(operationsStart, operationsEnd)
  if (operationColumnSource.includes('交付就绪') || operationColumnSource.includes('handoff-readiness-band')) {
    fail('handoff readiness must stay as a summary band, not another row operation')
  }
}

for (const token of [
  '.handoff-readiness-band strong',
  'overflow-wrap: anywhere',
  '@media (max-width: 720px)',
  'grid-template-columns: 1fr',
]) {
  if (!projectsSource.includes(token)) fail(`handoff readiness mobile layout token missing: ${token}`)
}

console.log('[OK] Vue platform handoff readiness is wired.')
