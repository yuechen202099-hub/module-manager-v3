const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const boardSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ProjectBoardView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requiredTokens = [
  ['platformArchiveManifestBlockerRows', 'board must compute blocker work order rows'],
  ['archiveManifestSectionReasonLabel', 'board must label blocker reasons from manifest sections'],
  ['阻塞工单明细', 'board must show blocker work order detail title'],
  ['工单对象', 'board must show primary work object label'],
  ['聚合口径', 'board must show aggregate label'],
  ['处理说明', 'board must show blocker handling detail'],
  ['section.items.map', 'board must flatten section blocker items'],
  ['item.primaryValue', 'board must render blocker primary value'],
  ['item.aggregateValue', 'board must render blocker aggregate value'],
  ['item.detail', 'board must render blocker detail'],
  ['platform-archive-blocker-details', 'board must style blocker details'],
]

for (const [token, message] of requiredTokens) {
  if (!boardSource.includes(token)) fail(message)
}

console.log('[OK] Vue delivery archive manifest blocker details are visible.')
