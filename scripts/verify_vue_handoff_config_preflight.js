const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const typesSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'api', 'types.ts'), 'utf8')
const servicesSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'api', 'services.ts'), 'utf8')
const projectsViewSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requirements = [
  [typesSource, 'configPreflight: PlatformConfigPreflight', 'handoff type must expose config preflight'],
  [servicesSource, 'config_preflight?: BackendPlatformConfigPreflight', 'backend handoff mapping must accept config_preflight'],
  [servicesSource, 'configPreflight: mapPlatformConfigPreflight', 'handoff mapper must map config preflight'],
  [projectsViewSource, 'handoffConfigPreflight', 'projects view must compute handoff config preflight'],
  [projectsViewSource, 'handoffConfigPreflightText', 'projects view must summarize handoff config preflight'],
  [projectsViewSource, 'fix_config_preflight_blockers', 'projects view must label config preflight fix action'],
  [projectsViewSource, 'config-preflight-handoff-status', 'projects view must render a top-level config preflight status'],
  [projectsViewSource, '配置预检', 'projects view must show config preflight in operator language'],
]

for (const [source, token, message] of requirements) {
  if (!source.includes(token)) fail(message)
}

console.log('[OK] Vue handoff config preflight summary is wired.')
