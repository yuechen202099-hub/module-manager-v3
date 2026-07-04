const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const typesSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'api', 'types.ts'), 'utf8')
const servicesSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'api', 'services.ts'), 'utf8')
const projectsSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

for (const token of [
  'PlatformConfigPreflight',
  'PlatformConfigPreflightProject',
  'PlatformConfigPreflightIssue',
  'readyForConfigLoad',
  'blockedProjects',
]) {
  if (!typesSource.includes(token)) fail(`types.ts missing config preflight token: ${token}`)
}

for (const token of [
  'type BackendPlatformConfigPreflight',
  'function mapPlatformConfigPreflight',
  'export async function fetchProjectConfigPreflight',
  '/projects/persistence/config-preflight',
  'ready_for_config_load',
  'blocked_projects',
]) {
  if (!servicesSource.includes(token)) fail(`services.ts missing config preflight token: ${token}`)
}

for (const token of [
  'fetchProjectConfigPreflight',
  'PlatformConfigPreflight',
  'projectConfigPreflight',
  'loadingProjectConfigPreflight',
  'loadProjectConfigPreflight',
  'configPreflightStatusText',
  'configPreflightIssueText',
  'config-preflight-panel',
  '配置预检',
  '历史草稿',
  '阻断项目',
  '只读预检',
]) {
  if (!projectsSource.includes(token)) fail(`ProjectsView.vue missing config preflight token: ${token}`)
}

const schemaDialogStart = projectsSource.indexOf(':title="schemaProject ? `字段配置')
const schemaDialogEnd = projectsSource.indexOf('</ElDialog>', schemaDialogStart)
if (schemaDialogStart < 0 || schemaDialogEnd < 0) fail('ProjectsView.vue field configuration dialog could not be located')
const schemaDialogSource = projectsSource.slice(schemaDialogStart, schemaDialogEnd)
if (!schemaDialogSource.includes('config-preflight-panel')) {
  fail('config preflight panel must live inside the field configuration dialog')
}

console.log('[OK] Vue project config preflight is wired.')
