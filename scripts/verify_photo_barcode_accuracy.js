const fs = require('fs')

function read(path) {
  return fs.readFileSync(path, 'utf8')
}

function assertContains(source, pattern, message) {
  if (!source.includes(pattern)) {
    throw new Error(message)
  }
}

const types = read('v2-web/src/api/types.ts')
const services = read('v2-web/src/api/services.ts')
const board = read('v2-web/src/views/ProjectBoardView.vue')
const releaseNotes = read('v2-web/src/constants/releaseNotes.ts')
const apiMain = read('v2-api/app/main.py')
const opsStatus = read('v2-api/app/services/ops_status.py')

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
assertContains(board, '资料组条码准确率', 'ProjectBoardView must show the group barcode accuracy label in Chinese')
assertContains(board, '条码无法识别清单', 'ProjectBoardView must show the unreadable barcode review dialog in Chinese')
assertContains(board, 'fetchGroupPhotoObjectUrl', 'ProjectBoardView must load review dialog photos with authenticated fetch')
assertContains(board, 'clearPhotoBarcodeObjectUrls', 'ProjectBoardView must release barcode review object URLs')
assertContains(board, 'photoAccuracyRate', 'ProjectBoardView must use the mapped accuracy rate')
assertContains(board, 'groupBarcodeAccuracyPassed', 'ProjectBoardView must show group-level passed count')
assertContains(releaseNotes, 'V3.0.40', 'Release notes must include V3.0.40')
assertContains(releaseNotes, '资料组条码准确率', 'Release notes must describe the group barcode accuracy feature in Chinese')
assertContains(apiMain, 'version="3.0.40"', 'FastAPI app version must be 3.0.40')
assertContains(opsStatus, 'return "3.0.40"', 'system status version must be 3.0.40')

console.log('photo barcode accuracy checks passed')
