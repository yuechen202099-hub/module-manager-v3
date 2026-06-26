const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const viewPath = path.join(root, 'v2-web', 'src', 'views', 'GlobalSearchView.vue')
const typesPath = path.join(root, 'v2-web', 'src', 'api', 'types.ts')
const servicesPath = path.join(root, 'v2-web', 'src', 'api', 'services.ts')

function read(file) {
  return fs.readFileSync(file, 'utf8')
}

function assertContains(source, needle, label) {
  if (!source.includes(needle)) {
    console.error(`[FAIL] ${label}: missing ${needle}`)
    process.exitCode = 1
    return
  }
  console.log(`[OK] ${label}`)
}

const view = read(viewPath)
const types = read(typesPath)
const services = read(servicesPath)

assertContains(types, 'installer?: string', 'MaterialGroup exposes installer')
assertContains(services, 'installer: raw.installer ||', 'mapGroup maps installer')
assertContains(view, 'label="安装人员"', 'table shows installer column')
assertContains(view, 'label="照片缩略图"', 'table shows readonly photo thumbnail column')
assertContains(view, 'type="selection"', 'table supports selecting groups')
assertContains(view, '批量归档', 'table exposes bulk archive action')
assertContains(view, 'photo-thumb-list', 'thumbnail list styling exists')
assertContains(view, ':preview-src-list', 'thumbnails support readonly preview')
assertContains(view, 'thumbnailUrl || photo.previewUrl || photo.imageUrl || photo.url', 'thumbnail URL fallback exists')
assertContains(services, 'bulkArchiveAdminGroups', 'admin bulk archive API client exists')

if (view.includes('lazy\n') || view.includes(' lazy ')) {
  console.error('[FAIL] thumbnails should not use lazy loading inside the table')
  process.exitCode = 1
} else {
  console.log('[OK] thumbnails load eagerly inside the table')
}

if (process.exitCode) process.exit(process.exitCode)
