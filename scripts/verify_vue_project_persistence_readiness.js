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
  'PlatformPersistenceStatus',
  'PlatformPersistenceStore',
  'PlatformMigrationGateItem',
  'PlatformMigrationReadiness',
  'ProjectConfigPersistenceContract',
  'ProjectConfigRoundtrip',
  'migrationRequiredForPostgresPlatformConfig',
]) {
  if (!typesSource.includes(token)) fail(`types.ts missing persistence readiness token: ${token}`)
}

for (const token of [
  'type BackendPlatformPersistenceStatus',
  'type BackendPlatformMigrationReadiness',
  'type BackendPlatformMigrationGateItem',
  'type BackendProjectConfigPersistenceContract',
  'function mapPlatformPersistenceStatus',
  'function mapPlatformMigrationReadiness',
  'function mapProjectConfigPersistenceContract',
  'export async function fetchPlatformPersistenceStatus',
  'export async function fetchPlatformMigrationReadiness',
  'export async function fetchProjectConfigPersistenceContract',
  '/projects/persistence/status',
  '/projects/persistence/migration-readiness',
  '/persistence/contract',
  'migration_required_for_postgres_platform_config',
  'target_backend',
]) {
  if (!servicesSource.includes(token)) fail(`services.ts missing persistence readiness token: ${token}`)
}

for (const token of [
  'fetchPlatformPersistenceStatus',
  'fetchPlatformMigrationReadiness',
  'fetchProjectConfigPersistenceContract',
  'PlatformPersistenceStatus',
  'PlatformMigrationReadiness',
  'ProjectConfigPersistenceContract',
  'projectPersistenceStatus',
  'projectMigrationReadiness',
  'projectPersistenceContractsById',
  'loadingPersistenceReadinessProjectId',
  'schemaProjectPersistenceContract',
  'loadProjectPersistenceReadiness',
  'persistenceBackendText',
  'persistenceRoundtripText',
  'migrationGateStatusText',
  'persistence-readiness-panel',
  'migration-gate-list',
  '持久化准备',
  '迁移门禁',
  '当前存储',
  'PostgreSQL',
  '迁移审批',
  '目标表',
  '安全门槛',
  '备份',
  'dry-run',
  '回滚',
  '审批',
]) {
  if (!projectsSource.includes(token)) fail(`ProjectsView.vue missing persistence readiness token: ${token}`)
}

const schemaDialogStart = projectsSource.indexOf(':title="schemaProject ? `字段配置')
const schemaDialogEnd = projectsSource.indexOf('</ElDialog>', schemaDialogStart)
if (schemaDialogStart < 0 || schemaDialogEnd < 0) fail('ProjectsView.vue field configuration dialog could not be located')

const schemaDialogSource = projectsSource.slice(schemaDialogStart, schemaDialogEnd)
if (!schemaDialogSource.includes('persistence-readiness-panel')) {
  fail('persistence readiness panel must live inside the field configuration dialog')
}

const operationsStart = projectsSource.indexOf('<ElTableColumn label="操作"')
const operationsEnd = projectsSource.indexOf('</ElTableColumn>', operationsStart)
if (operationsStart >= 0 && operationsEnd > operationsStart) {
  const operationColumnSource = projectsSource.slice(operationsStart, operationsEnd)
  if (operationColumnSource.includes('持久化准备') || operationColumnSource.includes('persistence-readiness-panel')) {
    fail('persistence readiness must stay in the configuration dialog, not another row operation')
  }
}

console.log('[OK] Vue project persistence readiness is wired.')
