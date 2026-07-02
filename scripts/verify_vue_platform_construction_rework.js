const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const checks = [
  {
    file: 'v2-web/src/api/types.ts',
    verify: (source) =>
      source.includes('reviewStatus: string') &&
      source.includes('reviewReason: string') &&
      source.includes('reviewHistory: PlatformReviewHistoryEvent[]'),
    message: 'Platform construction work order review metadata types are missing.',
  },
  {
    file: 'v2-web/src/api/services.ts',
    verify: (source) =>
      source.includes('review_status?: string') &&
      source.includes('review_reason?: string') &&
      source.includes('reviewHistory: (raw.review_history || []).map'),
    message: 'Platform construction work order review metadata mapping is missing.',
  },
  {
    file: 'v2-web/src/views/ConstructionView.vue',
    verify: (source) =>
      source.includes('platformWorkOrderNeedsRework') &&
      source.includes('platformWorkOrderReworkReason') &&
      source.includes('platform-rework-note'),
    message: 'Construction view must surface returned platform work orders for rework.',
  },
  {
    file: 'v2-web/src/views/ConstructionView.vue',
    verify: (source) =>
      source.includes('platformReworkOnly') &&
      source.includes('platformConstructionReworkOrders') &&
      source.includes('platformConstructionDisplayOrders') &&
      source.includes('platform-rework-filter'),
    message: 'Construction view must let operators filter platform work orders to returned rework items.',
  },
]

const failures = []
for (const check of checks) {
  const source = fs.readFileSync(path.join(root, check.file), 'utf8')
  if (!check.verify(source)) failures.push(`${check.file}: ${check.message}`)
}

if (failures.length) {
  console.error(failures.join('\n'))
  process.exit(1)
}

console.log('[OK] Vue construction view surfaces platform review returns.')
