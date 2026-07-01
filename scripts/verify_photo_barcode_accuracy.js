const fs = require('fs')

function read(path) {
  return fs.readFileSync(path, 'utf8')
}

function assertContains(source, pattern, message) {
  if (!source.includes(pattern)) {
    throw new Error(message)
  }
}

function assertNotContains(source, pattern, message) {
  if (source.includes(pattern)) {
    throw new Error(message)
  }
}

function assertOrdered(source, before, after, message) {
  const beforeIndex = source.indexOf(before)
  const afterIndex = source.indexOf(after)
  if (beforeIndex < 0 || afterIndex < 0 || beforeIndex >= afterIndex) {
    throw new Error(message)
  }
}

const types = read('v2-web/src/api/types.ts')
const services = read('v2-web/src/api/services.ts')
const board = read('v2-web/src/views/ProjectBoardView.vue')
const releaseNotes = read('v2-web/src/constants/releaseNotes.ts')
const apiMain = read('v2-api/app/main.py')
const opsStatus = read('v2-api/app/services/ops_status.py')
const expectedVersion = '3.0.74'

for (const field of [
  'photoAccuracyChecked',
  'photoAccuracyPassed',
  'photoAccuracyFailed',
  'photoAccuracyUnreadable',
  'photoAccuracyNotRequired',
  'photoAccuracyRate',
  'groupBarcodeAccuracyChecked',
  'groupBarcodeAccuracyPassed',
  'groupBarcodeAccuracyFailed',
  'groupBarcodeAccuracyUnreadable',
  'groupBarcodeAccuracyNotRequired',
  'groupBarcodeAccuracyRate',
]) {
  assertContains(types, field, `ProjectSummary must expose ${field}`)
  assertContains(services, field, `mapSummary must map ${field}`)
}

assertContains(services, 'photo_accuracy_checked', 'BackendSummary must include photo accuracy snake_case fields')
assertContains(services, 'group_barcode_accuracy_checked', 'BackendSummary must include group barcode accuracy snake_case fields')
assertContains(services, 'fetchPhotoBarcodeReviewGroups', 'services must expose the photo barcode review list API')
assertContains(services, 'page = 1', 'photo barcode review list API must accept a page argument')
assertContains(services, 'pageSize = 20', 'photo barcode review list API must default to a small page size')
assertContains(services, 'offset: String((safePage - 1) * safePageSize)', 'photo barcode review list API must send an offset')
assertContains(board, '条码准确率', 'ProjectBoardView must show the top barcode accuracy label in Chinese')
assertContains(board, '条码复核清单', 'ProjectBoardView must show the barcode review dialog in Chinese')
assertContains(board, 'fetchGroupPhotoObjectUrl', 'ProjectBoardView must load review dialog photos with authenticated fetch')
assertContains(board, 'clearPhotoBarcodeObjectUrls', 'ProjectBoardView must release barcode review object URLs')
assertContains(board, '<el-pagination', 'ProjectBoardView must paginate barcode review details')
assertContains(board, 'exportPhotoBarcodeReviewGroups', 'ProjectBoardView must export barcode review details')
assertContains(board, 'openPhotoBarcodePhotos', 'ProjectBoardView must open photos on demand instead of rendering thumbnails in the list')
assertContains(board, 'photoBarcodePageSize', 'ProjectBoardView must keep a small barcode review page size')
assertOrdered(
  board,
  'title="条码复核清单"',
  'v-model:current-page="photoBarcodePage"',
  'barcode review pagination must stay inside the barcode review dialog',
)
assertContains(board, 'photoAccuracyRate', 'ProjectBoardView must use the mapped accuracy rate')
assertContains(board, 'groupBarcodeAccuracyPassed', 'ProjectBoardView must show group-level passed count')
assertContains(board, 'barcode-metric', 'ProjectBoardView must promote barcode accuracy into the top metric strip')
assertContains(board, 'barcode-metric-mini-grid', 'ProjectBoardView must show compact barcode accuracy parameter cards')
assertContains(board, 'groupBarcodeAccuracyUnreadable', 'ProjectBoardView must show group-level unreadable count')
assertNotContains(board, '<span>资料组条码准确率</span>', 'ProjectBoardView must not keep the duplicate barcode accuracy risk card in project progress')
assertContains(board, "photoBarcodePhotoErrors", 'ProjectBoardView must expose photo loading failures instead of blank image cards')
assertContains(board, "fetchGroupPhotoObjectUrl(row.groupId, photo.id, 'original')", 'ProjectBoardView must retry barcode dialog photo loading with original images')
assertContains(releaseNotes, 'V3.0.52', 'Release notes must include V3.0.52')
assertContains(releaseNotes, '条码准确率', 'Release notes must describe the dashboard barcode accuracy metric in Chinese')
assertContains(releaseNotes, '每次最多 20 组', 'Release notes must describe slow 20-group barcode slices')
assertContains(releaseNotes, 'V3.0.50', 'Release notes must include V3.0.50')
assertContains(releaseNotes, '整组采集条码证据', 'Release notes must describe group-wide barcode evidence collection')
assertContains(releaseNotes, '累计识别到表号、模块号、采集器号三项即判定通过', 'Release notes must describe the group barcode pass rule')
assertContains(releaseNotes, 'V3.0.49', 'Release notes must keep V3.0.49')
assertContains(releaseNotes, '每次按 50 个资料组处理', 'Release notes must describe 50-group backend maintenance batches')
assertContains(releaseNotes, '自动归档', 'Release notes must describe barcode passed auto archive')
assertContains(releaseNotes, 'V3.0.45', 'Release notes must include V3.0.45')
assertContains(releaseNotes, '4 张有效照片完整', 'Release notes must describe the complete four-photo barcode rule')
assertContains(releaseNotes, '不计入准确率分母', 'Release notes must state incomplete groups are excluded from the denominator')
assertContains(releaseNotes, 'V3.0.44', 'Release notes must include V3.0.44')
assertContains(releaseNotes, '后台静默条码重算', 'Release notes must describe the backend silent recompute in Chinese')
assertContains(releaseNotes, '资料组条码准确率', 'Release notes must describe the group barcode accuracy feature in Chinese')
assertContains(apiMain, `version="${expectedVersion}"`, `FastAPI app version must be ${expectedVersion}`)
assertContains(opsStatus, `return "${expectedVersion}"`, `system status version must be ${expectedVersion}`)

console.log('photo barcode accuracy checks passed')
