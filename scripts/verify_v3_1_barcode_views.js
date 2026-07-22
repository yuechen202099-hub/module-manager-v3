const fs = require('fs')

const read = (path) => fs.readFileSync(path, 'utf8')
const taskHall = read('v2-web/src/views/TaskHallView.vue')
const globalSearch = read('v2-web/src/views/GlobalSearchView.vue')
const projectBoard = read('v2-web/src/views/ProjectBoardView.vue')
const services = read('v2-web/src/api/services.ts')
const types = read('v2-web/src/api/types.ts')

function assertContains(source, pattern, message) {
  if (!pattern.test(source)) throw new Error(message)
}

function assertNotContains(source, pattern, message) {
  if (pattern.test(source)) throw new Error(message)
}

for (const [source, name] of [
  [taskHall, 'TaskHallView'],
  [globalSearch, 'GlobalSearchView'],
  [projectBoard, 'ProjectBoardView'],
]) {
  assertContains(source, /barcodeVerificationState\.mjs/, `${name} must use the shared durable verification mapper`)
}

assertContains(types, /BarcodeVerificationStatus/, 'API types must expose durable verification statuses')
assertContains(types, /barcodeVerification\??:/, 'MaterialGroup must expose durable verification details')
assertContains(services, /barcode_verification\??:/, 'backend group mapping must accept durable verification details')
assertContains(services, /recognition_source/, 'service mapping must preserve recognition source')
assertContains(services, /passed_count/, 'service mapping must preserve durable passed count')
assertContains(services, /photo_category_status/, 'service mapping must preserve category status')

assertContains(
  taskHall,
  /async function rescanSelectedPhotoBarcode\(\)[\s\S]*await rescanPhotoBarcode\(groupId, photoId, category\)[\s\S]*await refreshCurrentReviewGroup\(groupId\)[\s\S]*await refreshCurrentReviewPage\(\)/,
  'review rescan must enqueue, refresh the active group, and refresh only the current page',
)
assertNotContains(
  taskHall,
  /async function rescanSelectedPhotoBarcode\(\)[\s\S]{0,1600}result\.photo/,
  'review rescan must not treat the enqueue response as browser recognition',
)
assertContains(taskHall, /纠正分类/, 'review classification command must use the correction semantic')
assertContains(
  taskHall,
  /ElMessageBox\.confirm\([\s\S]*人工确认扫码[\s\S]*confirmGroupBarcodeManually\(groupId,\s*\{[\s\S]*reason,?[\s\S]*photoIds,?/,
  'manual confirmation must retain the second confirmation and send formal evidence',
)
assertNotContains(taskHall, /@zxing|BarcodeDetector|Tesseract/, 'review verification must not recognize barcode or OCR in the browser')
assertContains(taskHall, /const REVIEW_GROUP_PAGE_SIZE = 20/, 'review list must stay fixed at 20 rows')
assertContains(taskHall, /:page-size="REVIEW_GROUP_PAGE_SIZE"/, 'review pagination must use its fixed 20-row constant')

assertContains(globalSearch, /label="扫码状态"/, 'data center must expose the read-only verification column')
assertContains(globalSearch, /label="图片分类"/, 'data center must expose the read-only category column')
assertNotContains(globalSearch, /label="扫码状态"[\s\S]{0,500}(el-input|el-select|el-button)/, 'verification column must remain read-only')
assertContains(globalSearch, /const PAGE_SIZE = 20/, 'data-center list must stay fixed at 20 rows')

assertContains(projectBoard, /barcode-compact-cards/, 'dashboard must render compact barcode cards')
assertNotContains(projectBoard, /class="metric barcode-metric/, 'dashboard must not restore a large barcode metric card')
assertContains(projectBoard, /const DIALOG_PAGE_SIZE = 20/, 'dashboard dialogs must stay fixed at 20 rows')
assertContains(projectBoard, /:page-size="DIALOG_PAGE_SIZE"/, 'dashboard dialog pagination must use 20 rows')
assertNotContains(projectBoard, /:page-sizes="\[10, 20, 50, 100\]"/, 'barcode review dialog must not expose non-20 page sizes')
assertNotContains(projectBoard, /barcode-review-table[\s\S]{0,1400}<img/, 'barcode review list rows must not render thumbnails')

console.log('V3.1 barcode view source checks passed')
