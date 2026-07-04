const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const servicesSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'api', 'services.ts'), 'utf8')
const workspaceSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'stores', 'workspace.ts'), 'utf8')
const projectsViewSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requirements = [
  [servicesSource, 'BackendProjectListResponse', 'services must model the project-list response metadata'],
  [servicesSource, 'config_preflight?: BackendPlatformConfigPreflight', 'project list response must accept config_preflight'],
  [servicesSource, 'lastProjectListConfigPreflight', 'services must keep the last project-list preflight'],
  [servicesSource, 'export function getLastProjectListConfigPreflight', 'services must expose the last project-list preflight'],
  [workspaceSource, 'projectListConfigPreflight', 'workspace store must hold project-list preflight state'],
  [workspaceSource, 'getLastProjectListConfigPreflight', 'workspace store must import last preflight state'],
  [projectsViewSource, 'projectListConfigPreflightText', 'projects view must summarize project-list preflight'],
  [projectsViewSource, 'project-list-config-preflight', 'projects view must render project-list preflight status'],
  [projectsViewSource, '项目列表预检', 'projects view must use operator-facing project-list preflight language'],
  [projectsViewSource, 'fix_config_preflight_blockers', 'projects view must label project-list preflight repair action'],
]

for (const [source, token, message] of requirements) {
  if (!source.includes(token)) fail(message)
}

console.log('[OK] Vue project-list config preflight fallback is wired.')
