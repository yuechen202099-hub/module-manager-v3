const fs = require('fs')

const types = fs.readFileSync('v2-web/src/api/types.ts', 'utf8')
const services = fs.readFileSync('v2-web/src/api/services.ts', 'utf8')
const board = fs.readFileSync('v2-web/src/views/ProjectBoardView.vue', 'utf8')
const dialog = fs.readFileSync('v2-web/src/components/UnmatchedReviewDialog.vue', 'utf8')

function assertContains(source, pattern, message) {
  if (!source.includes(pattern)) throw new Error(message)
}

function assertNotContains(source, pattern, message) {
  if (source.includes(pattern)) throw new Error(message)
}

function section(source, start, end) {
  const startIndex = source.indexOf(start)
  const endIndex = source.indexOf(end, startIndex)
  if (startIndex < 0 || endIndex < 0) throw new Error(`cannot find contract section ${start}`)
  return source.slice(startIndex, endIndex)
}

for (const token of [
  'UnmatchedReviewDetail',
  'UnmatchedReviewPhoto',
  'UnmatchedMatchCandidate',
  'fetchUnmatchedReview',
  'saveUnmatchedReview',
  'rescanUnmatchedReviewPhoto',
  'confirmUnmatchedReview',
  'fetchUnmatchedMatchCandidates',
  'fetchUnmatchedReviewPhotoObjectUrl',
  'finalizeUnmatchedMatch',
]) {
  if (!types.includes(token) && !services.includes(token)) throw new Error(`missing ${token}`)
}

for (const route of [
  '/review',
  '/photos/${encodeURIComponent(photoId)}/content',
  '/photos/${encodeURIComponent(photoId)}/rescan',
  '/confirm',
  '/candidates',
  '/finalize-match',
]) {
  assertContains(services, route, `missing route ${route}`)
}

const candidateContract = section(services, 'type BackendUnmatchedMatchCandidate', 'type BackendReplacementRecord')
assertContains(candidateContract, 'type BackendUnmatchedMatchCandidates', 'candidates must model the server envelope')
assertContains(services, 'api<BackendUnmatchedMatchCandidates>', 'candidates must request the server envelope')
assertContains(services, 'return (data.items || []).map(mapUnmatchedMatchCandidate)', 'candidates must map envelope items')
assertNotContains(services, 'api<BackendUnmatchedMatchCandidate[]>', 'candidates must not treat the envelope as an array')

const rescanContract = section(services, 'export async function rescanUnmatchedReviewPhoto', 'export async function confirmUnmatchedReview')
assertContains(rescanContract, 'expectedVersion: number', 'rescan must require an expected version')
assertContains(rescanContract, 'expected_version: expectedVersion', 'rescan must send expected_version')

const reviewPhotoType = section(types, 'export type UnmatchedReviewPhoto', 'export type UnmatchedReviewDetail')
const reviewPhotoBackendType = section(services, 'type BackendUnmatchedReviewPhoto', 'type BackendUnmatchedReview =')
assertNotContains(reviewPhotoType, 'sourceUrl', 'review photos must not expose source URLs')
assertNotContains(reviewPhotoBackendType, 'source_url', 'review photo mapping must not receive source URLs')

const reviewPhotoFetch = section(services, 'export async function fetchUnmatchedReviewPhotoObjectUrl', 'export async function rescanUnmatchedReviewPhoto')
assertContains(reviewPhotoFetch, 'encodeURIComponent(unmatchedId)', 'photo content path must use unmatched ID')
assertContains(reviewPhotoFetch, 'encodeURIComponent(photoId)', 'photo content path must use server-owned photo ID')
assertNotContains(reviewPhotoFetch, 'url:', 'must not proxy caller supplied URLs')
assertNotContains(reviewPhotoFetch, 'sourceUrl', 'must not fetch caller supplied URLs')
assertContains(reviewPhotoFetch, 'createVerifiedImageObjectUrl(blob)', 'photo content must verify server-owned image blobs')

for (const token of [
  '@row-click="openUnmatchedReviewRow"',
  '<UnmatchedReviewDialog',
  '@click.stop',
  'DIALOG_PAGE_SIZE',
]) {
  assertContains(board, token, `board missing ${token}`)
}

for (const token of [
  '重新扫码',
  '人工确认',
  '完成审阅并匹配清单',
  'fetchUnmatchedReviewPhotoObjectUrl',
  'URL.revokeObjectURL',
  'candidatePageSize = 20',
]) {
  assertContains(dialog, token, `dialog missing ${token}`)
}

assertNotContains(dialog, '<el-image', 'dialog must use verified object URLs with native img')

console.log('project board unmatched review checks passed')
