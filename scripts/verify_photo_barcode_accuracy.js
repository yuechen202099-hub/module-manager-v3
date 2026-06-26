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
]) {
  assertContains(types, field, `ProjectSummary must expose ${field}`)
  assertContains(services, field, `mapSummary must map ${field}`)
}

assertContains(services, 'photo_accuracy_checked', 'BackendSummary must include photo accuracy snake_case fields')
assertContains(board, '图片准确率', 'ProjectBoardView must show the image accuracy label in Chinese')
assertContains(board, 'photoAccuracyRate', 'ProjectBoardView must use the mapped accuracy rate')
assertContains(board, 'photoAccuracyPassed', 'ProjectBoardView must show passed count')
assertContains(releaseNotes, 'V3.0.38', 'Release notes must include V3.0.38')
assertContains(releaseNotes, '图片准确率', 'Release notes must describe the photo accuracy feature in Chinese')
assertContains(apiMain, 'version="3.0.38"', 'FastAPI app version must be 3.0.38')
assertContains(opsStatus, 'return "3.0.38"', 'system status version must be 3.0.38')

console.log('photo barcode accuracy checks passed')
