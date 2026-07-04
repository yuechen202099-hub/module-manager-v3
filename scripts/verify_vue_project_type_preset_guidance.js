const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const projectsSource = fs.readFileSync(
  path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue'),
  'utf8',
)

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requiredTokens = [
  ['selectedProjectTypePresetGuidance', 'ProjectsView must compute selected project type preset guidance'],
  ['preset-hierarchy-guidance', 'create project dialog must render preset hierarchy guidance'],
  ['当前项目类型预设', 'guidance must name the selected preset'],
  ['任务对象下更换附属设备', 'guidance must explain module replacement as accessory under task object'],
  ['主设备更换后确认附属设备', 'guidance must explain terminal replacement as main-device replacement'],
  ['终端聚合口径', 'guidance must explain terminal aggregate options'],
  ['台区、地区或厂家', 'guidance must list common terminal aggregate dimensions'],
  ['同时仅保留一种聚合字段', 'guidance must keep the one-active-aggregate rule visible'],
  ['selectedProjectTypePresetId', 'guidance must follow the project type preset selector'],
]

for (const [token, message] of requiredTokens) {
  if (!projectsSource.includes(token)) fail(message)
}

console.log('[OK] Vue project type preset guidance is explicit for module and terminal projects.')
