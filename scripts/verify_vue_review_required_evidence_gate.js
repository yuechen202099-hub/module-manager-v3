const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const reviewPath = path.join(root, 'v2-web', 'src', 'views', 'ReviewView.vue')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

if (!fs.existsSync(reviewPath)) fail('ReviewView.vue must exist')

const review = fs.readFileSync(reviewPath, 'utf8')
const compactReview = review.replace(/\s+/g, '')

const requiredTokens = [
  'reviewEvidenceGapGroups',
  'reviewApproveBlocked',
  'missingReviewFieldLabels',
  'missingReviewPhotoLabels',
  '审阅证据缺口',
  '缺少字段',
  '缺少照片',
  'platform-review-gap',
  "action === 'approved' && reviewApproveBlocked",
]

for (const token of requiredTokens) {
  if (!review.includes(token)) fail(`ReviewView.vue missing review evidence gate token: ${token}`)
}

const behaviorSnippets = [
  'reviewConditionMatches(field, values)',
  'field.collectedValue || field.initialValue',
  'slot.covered',
]

for (const snippet of behaviorSnippets) {
  if (!review.includes(snippet)) fail(`ReviewView.vue missing review evidence gate behavior: ${snippet}`)
}

if (!compactReview.includes('activeReviewFieldReviews.value.filter')) {
  fail('ReviewView.vue must derive missing field evidence from active review fields.')
}

if (!compactReview.includes('activeReviewPhotoSlotReviews.value.filter')) {
  fail('ReviewView.vue must derive missing photo evidence from active review photo slots.')
}

console.log('[OK] Vue review required evidence gate is wired.')
