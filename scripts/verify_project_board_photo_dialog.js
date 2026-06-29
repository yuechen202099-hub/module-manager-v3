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

const board = read('v2-web/src/views/ProjectBoardView.vue')
const services = read('v2-web/src/api/services.ts')

assertContains(board, 'class="barcode-photo-detail-image barcode-photo-image-button"', 'photo dialog must render a direct image button')
assertContains(board, '<img', 'photo dialog must render a native img element')
assertContains(board, '@error="handlePhotoBarcodeRenderedError(activePhotoBarcodeGroup, photo)"', 'photo dialog must handle rendered image failures')
assertContains(board, 'barcode-image-preview-dialog', 'photo dialog must keep a large single-image preview dialog')
assertContains(board, 'photoBarcodeLoadSerial', 'photo dialog must invalidate stale object URL loads')
assertContains(board, 'isPhotoBarcodeLoadCurrent', 'photo dialog must guard async image writes by the active load')
assertContains(board, 'URL.revokeObjectURL(objectUrl)', 'stale image object URLs must be revoked')
assertNotContains(board, '<el-image', 'photo dialog must not rely on Element Plus el-image for barcode review photos')

assertContains(services, 'createVerifiedImageObjectUrl(blob)', 'group photo fetch must verify image blobs before display')
assertContains(services, 'image.naturalWidth > 0 && image.naturalHeight > 0', 'image verification must reject zero-dimension images')
assertContains(services, 'looksLikeBlankOrPlaceholderImage(image)', 'image verification must reject blank or placeholder images')
assertContains(services, "new Error('图片内容疑似空白')", 'image verification must report blank image content')
assertContains(services, "new Error('图片无法解码')", 'image verification must report decode failures')

console.log('project board photo dialog checks passed')
