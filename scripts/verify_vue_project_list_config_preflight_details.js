const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const projectsViewSource = fs.readFileSync(
  path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue'),
  'utf8',
)

function requireIncludes(source, token, message) {
  if (!source.includes(token)) {
    console.error(`[FAIL] ${message}`)
    process.exit(1)
  }
}

[
  [
    'projectListConfigPreflightBlockedProjects',
    'projects view must compute blocked projects from project-list preflight',
  ],
  [
    'projectListConfigPreflightStoreIssues',
    'projects view must compute store-level issues from project-list preflight',
  ],
  [
    'showProjectListConfigPreflightDetails',
    'projects view must decide when to show project-list preflight details',
  ],
  [
    'project-list-config-preflight-details',
    'projects view must render a top-level project-list preflight detail block',
  ],
  [
    '项目列表预检阻断',
    'projects view must label list-level config blockers in operator language',
  ],
  [
    'configPreflightIssueText(project.issues[0])',
    'blocked project rows must reuse the config preflight issue text',
  ],
  [
    'fix_config_preflight_blockers',
    'projects view must keep the repair next action mapped',
  ],
].forEach(([token, message]) => requireIncludes(projectsViewSource, token, message))

console.log('[OK] Vue project-list config preflight details are visible.')
