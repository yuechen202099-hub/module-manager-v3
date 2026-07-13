const fs = require('fs')

const types = fs.readFileSync('v2-web/src/api/types.ts', 'utf8')
const services = fs.readFileSync('v2-web/src/api/services.ts', 'utf8')
const board = fs.readFileSync('v2-web/src/views/ProjectBoardView.vue', 'utf8')
const dialog = fs.readFileSync('v2-web/src/components/UnmatchedReviewDialog.vue', 'utf8')
const elementPlus = fs.readFileSync('v2-web/src/plugins/element-plus.ts', 'utf8')

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

assertContains(services, 'export class ApiRequestError extends Error', 'API errors must preserve HTTP status')
assertContains(services, 'readonly status: number', 'API errors must expose an HTTP status')
assertContains(services, 'export function getApiErrorStatus', 'components need a structured API status helper')
assertContains(services, 'new ApiRequestError(', 'API failures must use the structured error')

assertContains(dialog, 'return getApiErrorStatus(error) === 409', '409 handling must use the structured status')
assertNotContains(dialog, "message.includes('409')", '409 handling must not inspect error text')
assertNotContains(dialog, "message.includes('版本')", '409 handling must not inspect localized error text')
assertContains(dialog, 'let candidateRequestSerial = 0', 'candidate requests need a monotonic sequence')
assertContains(dialog, 'function invalidateCandidateRequest()', 'candidate requests need explicit invalidation')
assertContains(dialog, 'candidateAbortController?.abort()', 'candidate invalidation must abort the old request')
assertContains(dialog, 'fetchUnmatchedMatchCandidates(unmatchedId, controller.signal)', 'candidate request must receive an abort signal')
assertContains(dialog, 'function isCurrentCandidateRequest', 'candidate writes must check the active request')
assertContains(dialog, "mode.value === 'match'", 'candidate writes must remain in match mode')
assertContains(dialog, 'function clampCandidatePage()', 'candidate page must be clamped explicitly')
assertContains(dialog, 'Math.min(Math.max(1, candidatePage.value), candidateTotalPages.value)', 'candidate page clamp is incomplete')
assertContains(dialog, 'v-if="isAdmin"', 'finalization button must be admin only')
assertContains(dialog, 'if (!isAdmin.value || !detail.value', 'finalization handler must be admin only')
assertContains(dialog, '<el-radio', 'candidate rows must expose a selection control')
assertContains(elementPlus, 'ElRadio,', 'candidate radio control must be registered')

const candidateLoad = section(dialog, 'async function loadMatchCandidates()', 'async function finalizeMatch')
assertContains(dialog, 'function resetCandidateResults()', 'new candidate cycles must invalidate prior results')
assertContains(candidateLoad, 'resetCandidateResults()', 'candidate loading must invalidate prior results before fetching')
const resetIndex = candidateLoad.indexOf('resetCandidateResults()')
const fetchIndex = candidateLoad.indexOf('fetchUnmatchedMatchCandidates')
if (resetIndex < 0 || resetIndex > fetchIndex) throw new Error('candidate results must reset before fetching')

console.log('project board unmatched review checks passed')
