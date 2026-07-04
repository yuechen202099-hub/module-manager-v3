const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const typesPath = path.join(root, 'v2-web', 'src', 'api', 'types.ts')
const servicesPath = path.join(root, 'v2-web', 'src', 'api', 'services.ts')
const constructionPath = path.join(root, 'v2-web', 'src', 'views', 'ConstructionView.vue')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

for (const filePath of [typesPath, servicesPath, constructionPath]) {
  if (!fs.existsSync(filePath)) fail(`${path.basename(filePath)} must exist`)
}

const types = fs.readFileSync(typesPath, 'utf8')
const services = fs.readFileSync(servicesPath, 'utf8')
const construction = fs.readFileSync(constructionPath, 'utf8')

const requiredTokens = [
  [types, 'PlatformReworkEvidenceGapGroup', 'types must expose rework evidence gap groups'],
  [types, 'reworkEvidenceGapGroups', 'construction work order type must expose rework evidence gap groups'],
  [services, 'rework_evidence_gap_groups', 'services must read backend rework evidence gap groups'],
  [services, 'reworkEvidenceGapGroups', 'services must map rework evidence gap groups'],
  [construction, 'platformReworkEvidenceGapGroups', 'ConstructionView must compute active rework gap groups'],
  [construction, 'platformReworkGapSummary', 'ConstructionView must summarize returned gap groups in task cards'],
  [construction, 'platform-rework-gap-panel', 'ConstructionView must render a structured rework gap panel'],
  [construction, '\u9000\u56de\u8865\u91c7\u6e05\u5355', 'ConstructionView must label the returned collection gap list'],
]

for (const [source, token, message] of requiredTokens) {
  if (!source.includes(token)) fail(`${message}: ${token}`)
}

if (!construction.includes('group.items.join')) {
  fail('ConstructionView must show the concrete fields/photos to recollect.')
}

console.log('[OK] Vue construction rework gap panel is wired.')
