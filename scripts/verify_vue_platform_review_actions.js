const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const checks = [
  {
    file: 'v2-web/src/api/types.ts',
    verify: (source) =>
      source.includes('export type PlatformReviewActionPayload') &&
      source.includes("action: 'approved' | 'returned' | 'exception'") &&
      source.includes('reviewedBy: string') &&
      source.includes('reviewNote: string') &&
      source.includes('export type PlatformReviewHistoryEvent') &&
      source.includes('reviewHistory: PlatformReviewHistoryEvent[]'),
    message: 'Platform review action payload and metadata types are missing.',
  },
  {
    file: 'v2-web/src/api/services.ts',
    verify: (source) =>
      source.includes('type BackendPlatformReviewActionPayload') &&
      source.includes('export async function reviewProjectReviewWorkOrder') &&
      source.includes('/review/work-orders/${encodeURIComponent(workOrderId)}/actions'),
    message: 'Platform review action service is missing.',
  },
  {
    file: 'v2-web/src/views/TaskHallView.vue',
    verify: (source) =>
      source.includes('reviewProjectReviewWorkOrder') &&
      source.includes('submitPlatformReviewAction') &&
      source.includes('通过') &&
      source.includes('退回') &&
      source.includes('标异常'),
    message: 'Task Hall platform review action buttons are missing.',
  },
]

checks.push({
  file: 'v2-web/src/views/TaskHallView.vue',
  verify: (source) =>
    source.includes('platformReviewStatusFilter') &&
    source.includes('filteredPlatformReviewWorkOrders') &&
    source.includes('platformReviewStatusOptions') &&
    source.includes('selectedPlatformReviewWorkOrder.reviewHistory') &&
    source.includes('platform-review-history'),
  message: 'Task Hall platform review status filters are missing.',
})

const failures = []
for (const check of checks) {
  const source = fs.readFileSync(path.join(root, check.file), 'utf8')
  if (!check.verify(source)) {
    failures.push(`${check.file}: ${check.message}`)
  }
}

if (failures.length) {
  console.error(failures.join('\n'))
  process.exit(1)
}

console.log('[OK] Vue task hall exposes platform review actions.')
