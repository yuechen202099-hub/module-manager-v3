#!/usr/bin/env node

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..')
const read = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8')

function assertContains(source, needle, message) {
  assert.ok(source.includes(needle), message)
}

function assertNotContains(source, needle, message) {
  assert.ok(!source.includes(needle), message)
}

function assertCountAtLeast(source, needle, minCount, message) {
  const count = source.split(needle).length - 1
  assert.ok(count >= minCount, `${message}; found ${count}, expected at least ${minCount}`)
}

function assertOrdered(source, needles, message) {
  let cursor = -1
  for (const needle of needles) {
    const next = source.indexOf(needle, cursor + 1)
    assert.ok(next > cursor, `${message}: missing or out of order "${needle}"`)
    cursor = next
  }
}

const projectBoard = read('v2-web/src/views/ProjectBoardView.vue')
const dataCenter = read('v2-web/src/views/GlobalSearchView.vue')
const buildRelease = read('scripts/build-client-release.ps1')
const verifyRelease = read('scripts/verify-client-release.py')

assertContains(projectBoard, 'const DIALOG_PAGE_SIZE = 20', 'project board dialogs must share a 20-row page size')

for (const name of [
  'workloadPage',
  'exceptionPage',
  'replacementPage',
  'unmatchedPage',
  'workloadSegmentPage',
  'workloadExceptionPage',
]) {
  assertContains(projectBoard, `const ${name} = ref(1)`, `${name} must track dialog pagination`)
}

for (const name of [
  'pagedWorkloadRows',
  'pagedExceptionRows',
  'pagedReplacementRows',
  'pagedWorkloadSegmentAddresses',
  'pagedWorkloadExceptionGroups',
]) {
  assertContains(projectBoard, `const ${name} = computed`, `${name} must provide paged dialog data`)
}

assertContains(projectBoard, ':data="pagedWorkloadRows"', 'workload dialog table must use paged rows')
assertContains(projectBoard, ':data="pagedExceptionRows"', 'exception dialog table must use paged rows')
assertContains(projectBoard, ':data="pagedReplacementRows"', 'replacement dialog table must use paged rows')
assertContains(projectBoard, 'const unmatchedRows = ref<UnmatchedRecord[]>([])', 'unmatched dialog must store the current server page')
assertContains(projectBoard, 'const unmatchedTotal = ref(0)', 'unmatched dialog must store the server total')
assertContains(
  projectBoard,
  'fetchUnmatchedRecords(query, requestedPage, DIALOG_PAGE_SIZE)',
  'unmatched dialog must request the selected 20-row server page',
)
assertContains(projectBoard, 'requestSerial !== unmatchedLoadSerial', 'unmatched dialog must ignore stale server pages')
assertContains(projectBoard, ':data="unmatchedRows"', 'unmatched dialog table must render the current server page')
assertContains(projectBoard, ':total="unmatchedTotal"', 'unmatched dialog pagination must use the server total')
assertContains(
  projectBoard,
  '@current-change="handleUnmatchedPageChange"',
  'unmatched dialog page changes must request a new server page',
)
assertNotContains(projectBoard, 'const pagedUnmatchedRows = computed', 'unmatched dialog must not client-slice a partial server page')
assertContains(projectBoard, ':data="pagedWorkloadSegmentAddresses"', 'workload segment dialog table must use paged rows')
assertContains(projectBoard, ':data="pagedWorkloadExceptionGroups"', 'workload exception dialog table must use paged rows')
assertCountAtLeast(projectBoard, 'class="dialog-pagination"', 7, 'project board list dialogs must render standard pagination')

assertOrdered(
  projectBoard,
  [
    'prop="terminal"',
    'taskTotalGroups(row)',
    'taskUploadedCount(row)',
    'terminalInstallerText(row)',
    'terminalReviewerText(row)',
    'terminalStatusLabel(row)',
    'prop="address"',
  ],
  'terminal detail dialog fields must keep the unified field order',
)

assertOrdered(
  projectBoard,
  [
    'prop="terminal"',
    'row.meterNo',
    'prop="constructionModuleAssetNo"',
    'prop="constructionCollector"',
    'exceptionOrderFor(row)?.assignedTo',
    'exceptionReasonText(row)',
    'prop="address"',
  ],
  'exception dialog fields must keep the unified field order',
)

assertNotContains(projectBoard, 'type="info"\n        :closable="false"\n        title=', 'production dialogs must not keep explanatory info alerts')
assertNotContains(projectBoard, 'class="work-time-note"', 'KPI time dialog must not show long explanatory copy')

assertContains(dataCenter, 'groupPhotoContextItems', 'data center photo dialog must expose a unified group context list')
assertContains(dataCenter, 'class="group-photo-context"', 'data center photo dialog must render the group context before photos')
assertContains(dataCenter, 'photoGroup.value?.terminal', 'data center photo context must include terminal')
assertContains(dataCenter, 'photoGroup.value?.meterNo', 'data center photo context must include meter number')
assertContains(
  dataCenter,
  'photoGroup.value?.constructionModuleAssetNo || photoGroup.value?.moduleAssetNo',
  'data center photo context must include module number',
)
assertContains(
  dataCenter,
  'photoGroup.value?.constructionCollector || photoGroup.value?.collector',
  'data center photo context must include collector number',
)
assertContains(dataCenter, 'photoGroup.value?.creatorName', 'data center photo context must include installer name')
assertContains(dataCenter, 'photoGroup.value?.creator', 'data center photo context must include installer account fallback')
assertContains(dataCenter, 'photoGroup.value?.reviewerName || photoGroup.value?.reviewer', 'data center photo context must include reviewer')
assertContains(
  dataCenter,
  'photoGroup.value?.photoCount || photoGroup.value?.photos?.length',
  'data center photo context must include photo count',
)

assertContains(buildRelease, 'scripts\\verify_dialog_information_integration.js', 'release package must include the dialog integration verifier')
assertContains(verifyRelease, 'verify_dialog_information_integration.js', 'release verifier must require the dialog integration verifier')

console.log('dialog information integration checks passed')
