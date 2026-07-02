const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const reviewSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ReviewView.vue'), 'utf8')

const checks = [
  {
    ok:
      reviewSource.includes('fetchProjectReviewWorkOrders') &&
      reviewSource.includes('reviewProjectReviewWorkOrder') &&
      reviewSource.includes('PlatformReviewWorkOrder'),
    message: 'ReviewView must use the platform review API and work-order type.',
  },
  {
    ok:
      reviewSource.includes('platformReviewStatusFilter') &&
      reviewSource.includes('platformReviewStatusOptions') &&
      reviewSource.includes('filteredPlatformReviewWorkOrders') &&
      reviewSource.includes('platformReviewStatusCounts'),
    message: 'ReviewView must expose platform review status filters and counts.',
  },
  {
    ok:
      reviewSource.includes('loadPlatformReviewWorkOrders') &&
      reviewSource.includes('selectPlatformReviewWorkOrder') &&
      reviewSource.includes('submitPlatformReviewAction'),
    message: 'ReviewView must load, select, and submit platform review work orders.',
  },
  {
    ok:
      reviewSource.includes('platform-review-filter') &&
      reviewSource.includes('platform-review-work-order') &&
      reviewSource.includes('platform-review-actions') &&
      reviewSource.includes('platform-review-history'),
    message: 'ReviewView must render filter chips, work-order rows, action buttons, and review history.',
  },
]

const failures = checks.filter((check) => !check.ok)
if (failures.length) {
  console.error(failures.map((failure) => failure.message).join('\n'))
  process.exit(1)
}

console.log('[OK] Vue review page exposes platform review filters.')
