const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const source = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requiredTokens = [
  ['hierarchyGapCount', 'import draft summary must expose hierarchy gap count'],
  ['hierarchyGapItems', 'import draft summary must expose hierarchy gap items'],
  ['层级缺口', 'import draft preview must show hierarchy gap label'],
  ['import-draft-hierarchy-gaps', 'import draft preview must render hierarchy gap list'],
  ['hierarchy_gap_items', 'frontend must read backend hierarchy gap items'],
  ['hierarchy_gap_count', 'frontend must read backend hierarchy gap count'],
]

for (const [token, message] of requiredTokens) {
  if (!source.includes(token)) fail(message)
}

console.log('[OK] Vue import draft hierarchy gap summary is visible.')
