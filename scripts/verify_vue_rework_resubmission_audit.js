const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const constructionPath = path.join(root, 'v2-web', 'src', 'views', 'ConstructionView.vue')
const reviewPath = path.join(root, 'v2-web', 'src', 'views', 'ReviewView.vue')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

for (const filePath of [constructionPath, reviewPath]) {
  if (!fs.existsSync(filePath)) fail(`${path.basename(filePath)} must exist`)
}

const construction = fs.readFileSync(constructionPath, 'utf8')
const review = fs.readFileSync(reviewPath, 'utf8')

const requiredTokens = [
  [construction, 'platformWasReworkResubmitted', 'ConstructionView must detect rework resubmission history'],
  [construction, '返工已重新提交审阅', 'ConstructionView must tell field users rework is back in review'],
  [construction, 'rework_submitted', 'ConstructionView must inspect the backend rework_submitted event'],
  [review, 'platformReviewHistoryActionLabel', 'ReviewView must translate platform review history actions'],
  [review, 'rework_submitted', 'ReviewView must know the rework_submitted action'],
  [review, '返工重新提交', 'ReviewView must show an operator-readable rework-submitted label'],
  [review, 'returned_rework_resubmitted', 'ReviewView must keep the machine-readable resubmission reason visible or mapped'],
]

for (const [source, token, message] of requiredTokens) {
  if (!source.includes(token)) fail(`${message}: ${token}`)
}

if (review.includes('<span>{{ event.action }}</span>')) {
  fail('ReviewView must not render raw review history action codes.')
}

console.log('[OK] Vue rework resubmission audit trail is wired.')
