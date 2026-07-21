const fs = require('fs')

const hall = fs.readFileSync('v2-web/src/views/TaskHallView.vue', 'utf8')
const services = fs.readFileSync('v2-web/src/api/services.ts', 'utf8')
const types = fs.readFileSync('v2-web/src/api/types.ts', 'utf8')

function assertContains(source, pattern, message) {
  if (!source.includes(pattern)) throw new Error(message)
}

function assertNotContains(source, pattern, message) {
  if (source.includes(pattern)) throw new Error(message)
}

function section(source, start, end) {
  const startIndex = source.indexOf(start)
  const endIndex = source.indexOf(end, startIndex + start.length)
  if (startIndex < 0 || endIndex < 0) throw new Error(`cannot find contract section ${start}`)
  return source.slice(startIndex, endIndex)
}

for (const token of [
  'ReviewImageInspector',
  'scanGroupPhotoRegion',
  'let regionScanSerial = 0',
  'metadataDraft.meterNo',
  'metadataDraft.moduleAssetNo',
  'metadataDraft.collector',
  '原值',
  '识别值',
  '识别方式',
  '替换',
  '当前选区未识别到可用内容',
  'finishSubmission()',
  'resetSelection()',
  '<el-radio',
]) {
  assertContains(hall, token, `task hall region review missing ${token}`)
}

assertContains(types, "export type BarcodeType = 'meter' | 'module' | 'collector'", 'missing strict barcode type')
assertContains(types, 'export type NormalizedRegion = { x: number; y: number; width: number; height: number }', 'missing normalized region type')
assertContains(types, 'export type RegionScanRequest = { barcodeType: BarcodeType; region: NormalizedRegion }', 'missing region scan request type')
const resultType = section(types, 'export type RegionScanResult', 'export type ')
assertContains(resultType, 'barcodeType: BarcodeType', 'region scan result must retain the requested type')
assertContains(resultType, 'values: string[]', 'region scan result must expose raw values')
assertContains(resultType, 'normalizedValues: string[]', 'region scan result must expose normalized values')
assertContains(resultType, "method: 'barcode' | 'ocr' | 'none'", 'region scan result method must be strict')
assertContains(resultType, 'region: NormalizedRegion', 'region scan result must expose normalized region')

assertContains(services, 'function mapRegionScanResult(', 'region scan clients must share one response mapper')
assertContains(services, 'export async function scanGroupPhotoRegion', 'missing group region scan client')
assertContains(services, 'export async function scanUnmatchedPhotoRegion', 'missing unmatched region scan client')
assertContains(
  services,
  'groups/${encodeURIComponent(groupId)}/photos/${encodeURIComponent(photoId)}/region-scan',
  'group region scan must use group and photo ids',
)
const requestMapper = section(services, 'function regionScanRequestBody(', 'function mapRegionScanResult(')
assertContains(requestMapper, 'barcode_type: request.barcodeType', 'request mapper must map barcode_type')
assertContains(requestMapper, 'region: request.region', 'request mapper must map region')
for (const forbidden of ['imageUrl', 'sourceUrl', 'base64', 'path:']) {
  assertNotContains(requestMapper, forbidden, `region scan request body must not contain ${forbidden}`)
}

const hallRegionScan = section(hall, 'async function handleRegionScan(', 'function replaceRegionScanDraft')
assertContains(hallRegionScan, 'regionScanLoading.value', 'task hall region scan must enforce one in-flight request')
assertContains(hallRegionScan, 'requestSerial !== regionScanSerial', 'task hall region scan must reject stale responses')
assertContains(hallRegionScan, 'activeGroup.value?.id !== groupId', 'task hall region scan must bind the current group')
assertContains(hallRegionScan, 'selectedPhotoId.value !== photoId', 'task hall region scan must bind the current photo')
assertContains(hallRegionScan, 'regionScanDialogActive = true', 'recognized candidates must activate one confirmation cycle')
assertContains(hallRegionScan, 'finally', 'task hall region scan must restore inspector state in finally')
assertContains(hallRegionScan, 'finishSubmission()', 'task hall region scan must finish inspector submission')
for (const forbidden of ['saveReview(', 'rescanSelectedPhotoBarcode(', 'confirmSelectedPhotoBarcode(', 'archiveSelectedPhoto(']) {
  assertNotContains(hallRegionScan, forbidden, `task hall region scan must not call ${forbidden}`)
}
const hallRegionReplace = section(hall, 'function replaceRegionScanDraft()', 'function closeRegionScanDialog')
assertContains(hallRegionReplace, 'metadataDraft[field] =', 'replacement must update only the mapped task hall draft field')
assertContains(hallRegionReplace, 'closeRegionScanDialog()', 'replacement must close through the serial-invalidating path')
assertNotContains(hallRegionReplace, 'barcodeCheckStatus', 'replacement must not modify barcode scan status')
assertContains(hall, 'let regionScanDialogActive = false', 'task hall confirmation needs an active-cycle guard')
const hallRegionClose = section(hall, 'function closeRegionScanDialog()', 'function invalidateRegionScan')
assertContains(hallRegionClose, 'if (!regionScanDialogActive) return', 'duplicate closed events must be side-effect free')
assertContains(hallRegionClose, 'regionScanDialogActive = false', 'closing must consume the active confirmation cycle')
assertContains(hallRegionClose, 'regionScanSerial += 1', 'closing must invalidate the captured scan serial')
const hallRegionInvalidate = section(hall, 'function invalidateRegionScan()', 'function selectPhoto')
assertContains(hallRegionInvalidate, 'regionScanDialogActive = false', 'context invalidation must consume the active confirmation cycle')
assertNotContains(hallRegionInvalidate, 'closeRegionScanDialog()', 'context invalidation must not trigger duplicate close side effects')
assertContains(hall, '@click="closeRegionScanDialog">取消', 'cancel must use the serial-invalidating close path')
assertContains(hall, '@closed="closeRegionScanDialog"', 'system close must use the serial-invalidating close path')
if (/barcodeCheckStatus\s*=(?!=)/.test(hall)) throw new Error('task hall must not assign barcode scan status')

console.log('Task hall region scan verification passed.')
