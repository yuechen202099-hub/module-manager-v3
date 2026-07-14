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

function assertNotContains(source, needle, label) {
  if (source.includes(needle)) {
    console.error(`[FAIL] ${label}: found ${needle}`)
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
assertContains(view, 'type="selection"', 'table supports selecting groups')
assertContains(view, '批量归档', 'table exposes bulk archive action')
assertContains(view, 'prop="photoCount" label="照片数"', 'table shows readonly photo count')
assertContains(view, 'label="照片"', 'table exposes the on-demand photo action column')
assertContains(view, '@click="openGroupPhotos(row)"', 'table opens group photos on demand')
assertContains(view, '查看 {{ row.photoCount }} 张', 'table labels the on-demand photo action with its count')
assertContains(view, 'fetchGroupPhotoObjectUrl', 'photo dialog loads authenticated object URLs')
assertNotContains(view, 'label="照片缩略图"', 'table must not render the removed thumbnail column')
assertNotContains(view, 'photo-thumb-list', 'table must not keep thumbnail list styling')
assertNotContains(view, ':preview-src-list', 'table must not render inline preview thumbnails')
assertContains(services, 'bulkArchiveAdminGroups', 'admin bulk archive API client exists')

if (process.exitCode) process.exit(process.exitCode)
