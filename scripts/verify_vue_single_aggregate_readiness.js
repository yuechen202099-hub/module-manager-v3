const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const projectsPath = path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const projectsSource = fs.readFileSync(projectsPath, 'utf8')

const tokens = [
  ['single_aggregate_field', 'ProjectsView must map the single aggregate readiness check'],
  ['聚合口径唯一', 'ProjectsView must label the single aggregate readiness check for operators'],
  ['fix_aggregate_field', 'ProjectsView must map the single aggregate fix action'],
  ['请只保留一个聚合字段', 'ProjectsView must explain the one-active-aggregate fix'],
]

for (const [token, message] of tokens) {
  if (!projectsSource.includes(token)) fail(message)
}

console.log('[OK] Vue single aggregate readiness labels are wired.')
