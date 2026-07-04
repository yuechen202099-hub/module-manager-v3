const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const reviewPath = path.join(root, 'v2-web', 'src', 'views', 'ReviewView.vue')
const typesPath = path.join(root, 'v2-web', 'src', 'api', 'types.ts')
const servicesPath = path.join(root, 'v2-web', 'src', 'api', 'services.ts')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

for (const filePath of [reviewPath, typesPath, servicesPath]) {
  if (!fs.existsSync(filePath)) fail(`${path.basename(filePath)} must exist`)
}

const review = fs.readFileSync(reviewPath, 'utf8')
const types = fs.readFileSync(typesPath, 'utf8')
const services = fs.readFileSync(servicesPath, 'utf8')

const requiredTokens = [
  [types, 'PlatformReviewHierarchyGapItem', 'types must define review hierarchy gap items'],
  [types, 'reviewHierarchyGapItems', 'review work order type must include hierarchy gap items'],
  [services, 'review_hierarchy_gap_items', 'services must read backend review hierarchy gap payload'],
  [services, 'reviewHierarchyGapItems', 'services must map backend hierarchy gaps to frontend camelCase'],
  [review, 'importedReviewHierarchyGapItems', 'ReviewView must compute imported hierarchy gaps'],
  [review, '导入层级缺口', 'ReviewView must show imported hierarchy gaps in evidence gap groups'],
  [review, 'reviewHierarchyGapItems', 'ReviewView must consume hierarchy gap items from selected work order'],
]

for (const [source, token, message] of requiredTokens) {
  if (!source.includes(token)) fail(`${message}: ${token}`)
}

console.log('[OK] Vue review hierarchy gap follow-up is wired.')
