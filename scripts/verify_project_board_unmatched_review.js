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

function assertBefore(source, first, second, message) {
  const firstIndex = source.indexOf(first)
  const secondIndex = source.indexOf(second)
  if (firstIndex < 0 || secondIndex < 0 || firstIndex >= secondIndex) throw new Error(message)
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

const unmatchedFetch = section(services, 'export async function fetchUnmatchedRecords', 'export async function fetchUnmatchedReview')
assertContains(types, 'export type UnmatchedListStats', 'unmatched list must expose full-filter server statistics')
assertContains(unmatchedFetch, 'page = 1', 'unmatched API must accept a server page')
assertContains(unmatchedFetch, 'pageSize = 20', 'unmatched API must accept a server page size')
assertContains(unmatchedFetch, 'offset', 'unmatched API must send a server offset')
assertContains(unmatchedFetch, 'stats:', 'unmatched API must map full-filter server statistics')
assertNotContains(unmatchedFetch, "limit: '500'", 'unmatched API must not truncate the list at 500 rows')
assertContains(board, 'const unmatchedTotal = ref(0)', 'project board must track the server unmatched total')
assertContains(board, 'const unmatchedStats = ref<UnmatchedListStats>', 'project board must retain full-filter server statistics')
assertContains(board, 'let unmatchedLoadSerial = 0', 'unmatched requests need a monotonic sequence')
assertContains(board, 'const requestSerial = ++unmatchedLoadSerial', 'each unmatched request must capture its sequence')
assertContains(board, 'requestSerial !== unmatchedLoadSerial', 'stale unmatched responses must be ignored')
assertContains(board, 'unmatchedRows.value = result.items', 'project board must render the server page')
assertContains(board, 'unmatchedTotal.value = result.total', 'project board must retain the server total')
assertContains(board, 'unmatchedStats.value = result.stats', 'project board statistics must use the full filtered result')
assertContains(board, ':data="unmatchedRows"', 'project board must not paginate a truncated client list')
assertContains(board, ':total="unmatchedTotal"', 'project board pagination must use the server total')
assertContains(board, '@current-change="handleUnmatchedPageChange"', 'page changes must load the requested server page')
assertNotContains(board, ':data="pagedUnmatchedRows"', 'project board must not present client slicing as full pagination')
const unmatchedExport = section(board, 'async function exportUnmatchedCsv()', 'async function deleteUnmatchedRow')
assertContains(unmatchedExport, 'exportUnmatchedRecords(unmatchedQuery.value)', 'unmatched export must use the administrator-only snapshot endpoint')
assertNotContains(unmatchedExport, 'fetchAllUnmatchedRecords(', 'project board export must not use the shared field-page loader')
const fetchAllUnmatched = section(services, 'export async function fetchAllUnmatchedRecords', 'export async function exportUnmatchedRecords')
assertContains(fetchAllUnmatched, 'fetchUnmatchedRecords(query, page, pageSize)', 'shared field-page loader must retain paginated non-admin access')
assertNotContains(fetchAllUnmatched, "'/local-test/unmatched/export'", 'shared field-page loader must not call an administrator-only endpoint')
const exportUnmatched = section(services, 'export async function exportUnmatchedRecords', 'export async function fetchUnmatchedReview')
assertContains(exportUnmatched, "'/local-test/unmatched/export'", 'complete export must use one server snapshot endpoint')
assertNotContains(exportUnmatched, 'for (let page =', 'complete export must not stitch mutable offset pages')
assertContains(board, '导出完整清单', 'unmatched export must state that it exports the complete list')

assertNotContains(board, 'dedupeUnmatchedRecords', 'project board must not import retired unmatched dedupe')
assertNotContains(board, 'cleanupDuplicateUnmatchedRows', 'project board must not expose retired unmatched dedupe')
assertNotContains(board, 'unmatchedDeduping', 'project board must not retain retired unmatched dedupe state')
assertNotContains(board, '删除重复项', 'project board must not render the retired unmatched dedupe action')
assertNotContains(services, 'dedupeUnmatchedRecords', 'API services must not expose retired unmatched dedupe')
assertNotContains(services, '/local-test/unmatched/dedupe', 'API services must not call retired unmatched dedupe')
assertNotContains(types, 'UnmatchedDedupeResult', 'API types must not model retired unmatched dedupe')
assertNotContains(services, 'rematchUnmatchedRecord', 'API services must not expose retired unmatched rematch')
assertNotContains(services, '/local-test/unmatched/${encodeURIComponent(unmatchedId)}/rematch', 'API services must not call retired unmatched rematch')

for (const token of [
  '重新扫码',
  '人工确认',
  '完成审阅并匹配清单',
  'fetchUnmatchedReviewPhotoObjectUrl',
  'URL.revokeObjectURL',
  'candidatePageSize = 20',
  ':preview-src-list="[imageObjectUrl]"',
]) {
  assertContains(dialog, token, `dialog missing ${token}`)
}

assertContains(dialog, '<el-image', 'dialog must expose the verified object URL through the controlled preview component')
assertContains(elementPlus, "import { ElImage } from 'element-plus/es/components/image/index'", 'ElImage must be imported for global registration')
assertContains(elementPlus, '  ElImage,', 'ElImage must be installed with the other Element Plus components')
assertContains(dialog, '.unmatched-photo-stage :deep(.el-image)', 'the ElImage host must have stable preview dimensions')
assertNotContains(types, 'targetGroupId: string', 'candidate DTO must not expose internal group ids')
assertNotContains(candidateContract, 'target_group_id?: string', 'candidate backend DTO must not receive internal group ids')
assertNotContains(dialog, 'prop="targetGroupId"', 'candidate table must not render internal group ids')

const rescanAction = section(dialog, 'async function rescanPhoto()', 'async function confirmReview()')
assertContains(rescanAction, 'persistReview(detail.value.state, false)', 'rescan must persist the current draft and state first')
assertContains(rescanAction, 'saved.version', 'rescan must use the saved review version')
assertBefore(
  rescanAction,
  'persistReview(detail.value.state, false)',
  'rescanUnmatchedReviewPhoto(',
  'rescan must persist the current draft before starting barcode recognition',
)
assertNotContains(rescanAction, 'detail.value.version', 'rescan must not submit the stale detail version')

const confirmAction = section(dialog, 'async function confirmReview()', 'async function openMatchMode()')
assertContains(confirmAction, 'const unmatchedId = props.unmatchedId', 'confirmation must capture the record id before saving')
assertContains(confirmAction, 'persistReview(detail.value.state, false)', 'confirmation must persist the current draft and state first')
assertContains(confirmAction, 'saved.version', 'confirmation must use the saved review version')
assertContains(confirmAction, 'confirmUnmatchedReview(unmatchedId, saved.version)', 'confirmation must use the captured record id')
assertNotContains(confirmAction, 'confirmUnmatchedReview(props.unmatchedId', 'confirmation must not re-read a changed prop after saving')
assertBefore(
  confirmAction,
  'persistReview(detail.value.state, false)',
  'confirmUnmatchedReview(',
  'confirmation must persist the current draft before confirming',
)
assertNotContains(confirmAction, 'detail.value.version', 'confirmation must not submit the stale detail version')

const openMatchAction = section(dialog, 'async function openMatchMode()', 'async function loadMatchCandidates()')
assertContains(openMatchAction, 'if (!saved.manualConfirmed)', 'matching must re-check confirmation after saving')
assertContains(openMatchAction, "ElMessage.warning('请先完成人工确认')", 'matching must explain the confirmation requirement')
assertBefore(
  openMatchAction,
  'if (!saved.manualConfirmed)',
  "mode.value = 'match'",
  'matching must enforce confirmation before entering candidate mode',
)

assertContains(services, 'export class ApiRequestError extends Error', 'API errors must preserve HTTP status')
assertContains(services, 'readonly status: number', 'API errors must expose an HTTP status')
assertContains(services, 'export function getApiErrorStatus', 'components need a structured API status helper')
assertContains(services, 'new ApiRequestError(', 'API failures must use the structured error')

assertContains(dialog, 'return getApiErrorStatus(error) === 409', '409 handling must use the structured status')
assertContains(dialog, 'function handleUnavailableRecord(', '404 handling must use one record invalidation path')
const unavailableHandler = section(dialog, 'function handleUnavailableRecord(', 'async function loadDetail')
assertContains(unavailableHandler, 'getApiErrorStatus(error) !== 404', 'missing-record handling must use HTTP status 404')
assertContains(unavailableHandler, "emit('updated')", 'missing-record handling must refresh the parent list')
assertContains(unavailableHandler, "emit('update:modelValue', false)", 'missing-record handling must close the stale dialog')
const photoLoadAction = section(dialog, 'async function loadSelectedPhoto()', 'function selectPhoto')
assertNotContains(photoLoadAction, 'handleUnavailableRecord(', 'a missing photo must not invalidate an otherwise available record')
assertContains(photoLoadAction, "getApiErrorStatus(error) === 404", 'missing photo handling must use the structured status')
assertContains(photoLoadAction, '可继续审阅其他照片', 'missing photo handling must keep the review workflow available')
assertNotContains(dialog, "message.includes('409')", '409 handling must not inspect error text')
assertNotContains(dialog, "message.includes('版本')", '409 handling must not inspect localized error text')
assertContains(dialog, 'let candidateRequestSerial = 0', 'candidate requests need a monotonic sequence')
assertContains(dialog, 'function isCurrentReviewRecord', 'review mutations must verify the active record')
assertContains(dialog, 'let mutationSessionSerial = 0', 'review mutations need a non-reusable dialog session sequence')
assertContains(dialog, 'function invalidateMutationSession()', 'record switches must invalidate the prior mutation session')
assertContains(dialog, 'mutationSessionSerial += 1', 'mutation invalidation must advance the dialog session sequence')
assertContains(dialog, 'function isCurrentMutation(', 'review mutations must verify their captured dialog session')
assertContains(dialog, 'function resetReviewContent()', 'record switches must clear stale review content')
const resetReviewContent = section(dialog, 'function resetReviewContent()', 'function invalidateCandidateRequest()')
assertContains(resetReviewContent, 'detail.value = null', 'record switches must clear stale detail')
assertContains(resetReviewContent, "draft.meterNo = ''", 'record switches must clear the stale meter draft')
assertContains(resetReviewContent, "draft.collector = ''", 'record switches must clear the stale collector draft')
assertContains(resetReviewContent, "draft.moduleAssetNo = ''", 'record switches must clear the stale module draft')
const resetReviewContentOccurrences = dialog.split('resetReviewContent()').length - 1
if (resetReviewContentOccurrences < 3) throw new Error('close and record-switch branches must both clear stale review content')
const persistAction = section(dialog, 'async function persistReview(', 'async function saveReview')
assertContains(
  persistAction,
  'detail.value.record.unmatchedId !== props.unmatchedId',
  'save must reject detail that belongs to another unmatched record',
)
const finalizeAction = section(dialog, 'async function finalizeMatch()', 'function returnToReview()')
assertContains(finalizeAction, 'const groupId = await finalizeUnmatchedMatch', 'finalization must use the server result group id')
assertContains(finalizeAction, "emit('matched', groupId)", 'finalization must emit only the server result group id')
assertNotContains(finalizeAction, 'selected?.targetGroupId', 'finalization must not depend on a candidate internal group id')
for (const [name, action] of [
  ['save', persistAction],
  ['rescan', rescanAction],
  ['confirm', confirmAction],
  ['finalize', finalizeAction],
]) {
  assertContains(action, 'const mutationSession = mutationSessionSerial', `${name} must capture the dialog mutation session`)
  assertContains(action, 'isCurrentMutation(mutationSession, unmatchedId)', `${name} must reject stale ABA results`)
}
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
assertContains(
  dialog,
  "selectedCandidateKey.value = next.length === 1 ? next[0].candidateKey : ''",
  'a unique unmatched candidate must be selected by default',
)
assertNotContains(
  section(dialog, 'async function loadMatchCandidates()', 'async function finalizeMatch()'),
  'finalizeUnmatchedMatch(',
  'loading candidates must never auto-finalize a match',
)

console.log('project board unmatched review checks passed')
