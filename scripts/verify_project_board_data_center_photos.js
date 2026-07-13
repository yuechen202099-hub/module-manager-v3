const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), 'utf8')
}

function assertContains(source, needle, message) {
  if (!source.includes(needle)) {
    throw new Error(message)
  }
}

function assertNotContains(source, needle, message) {
  if (source.includes(needle)) {
    throw new Error(message)
  }
}

const projectBoard = read('v2-web/src/views/ProjectBoardView.vue')
const globalSearch = read('v2-web/src/views/GlobalSearchView.vue')
const releaseNotes = read('v2-web/src/constants/releaseNotes.ts')
const opsStatus = read('v2-api/app/services/ops_status.py')
const apiMain = read('v2-api/app/main.py')
const packageJson = JSON.parse(read('v2-web/package.json'))
const webIndex = read('v2-web/index.html')
const legacyLayout = read('v2-web/src/components/AppLayout.vue')
const expectedVersion = packageJson.version

assertNotContains(projectBoard, 'fetchSystemStatus', 'project board must not fetch unrelated system status')
assertNotContains(projectBoard, 'systemRows', 'project board must not compute system status rows')
assertNotContains(projectBoard, 'systemStatus', 'project board must not keep system status state')
assertNotContains(projectBoard, 'class="panel system-status"', 'project board must not render the system status panel')
assertNotContains(projectBoard, '<h3>系统状态</h3>', 'project board must not show the system status title')

assertContains(globalSearch, 'groupPhotoErrors', 'data center photo dialog must expose per-photo load errors')
assertContains(globalSearch, "fetchGroupPhotoObjectUrl(group.id, photo.id, 'preview')", 'data center photo dialog must first request preview images')
assertContains(globalSearch, "fetchGroupPhotoObjectUrl(group.id, photo.id, 'original')", 'data center photo dialog must retry with original images')
assertContains(globalSearch, 'isGroupPhotoLoadCurrent', 'data center photo dialog must guard stale async photo loads')
assertContains(globalSearch, '@error="handleGroupPhotoRenderedError(photoGroup, photo)"', 'data center photo dialog must handle rendered image failures')
assertContains(globalSearch, '<img', 'data center photo dialog must render native images for reliable object URL display')
assertNotContains(globalSearch, '<el-image', 'data center photo dialog must not depend on Element Plus image rendering')

assertContains(releaseNotes, `APP_VERSION = '${expectedVersion}'`, `APP_VERSION must be ${expectedVersion}`)
assertContains(releaseNotes, "version: 'V3.0.78'", 'release notes must include V3.0.78')
assertContains(releaseNotes, '弹窗信息整合', 'release notes must describe the V3.0.78 dialog information integration in Chinese')
assertContains(releaseNotes, '20 条分页结构', 'release notes must describe the V3.0.78 dialog pagination update in Chinese')
assertContains(releaseNotes, '数据中台资料组照片弹窗新增终端', 'release notes must describe the V3.0.78 data center photo context update in Chinese')
assertContains(releaseNotes, "version: 'V3.0.77'", 'release notes must include V3.0.77')
assertContains(releaseNotes, '发布包验证脚本补齐', 'release notes must describe the V3.0.77 release package verifier update in Chinese')
assertContains(releaseNotes, 'verify_admin_release_notes.js 必备项', 'release notes must describe the V3.0.77 release package verifier guard in Chinese')
assertContains(releaseNotes, "version: 'V3.0.76'", 'release notes must keep V3.0.76')
assertContains(releaseNotes, '异常工单与远程图片重定向安全修复', 'release notes must keep the V3.0.76 exception order and remote image redirect security update in Chinese')
assertContains(releaseNotes, '禁止自动跟随 302/301 跳转', 'release notes must keep the V3.0.76 remote image redirect guard in Chinese')
assertContains(releaseNotes, "version: 'V3.0.75'", 'release notes must keep V3.0.75')
assertContains(releaseNotes, '上传与扫码安全加固', 'release notes must keep the V3.0.75 upload and barcode security update in Chinese')
assertContains(releaseNotes, "version: 'V3.0.74'", 'release notes must keep V3.0.74')
assertContains(releaseNotes, '网站安全防护加固', 'release notes must keep the V3.0.74 security hardening update in Chinese')
assertContains(releaseNotes, "version: 'V3.0.73'", 'release notes must include V3.0.73')
assertContains(releaseNotes, '今日完成量可见性修复', 'release notes must keep the V3.0.73 daily completion visibility fix in Chinese')
assertContains(releaseNotes, "version: 'V3.0.72'", 'release notes must include V3.0.72')
assertContains(releaseNotes, '施工缓存一键上传修复', 'release notes must describe the V3.0.72 construction upload fix in Chinese')
assertContains(releaseNotes, '保存稳定的 Blob 数据', 'release notes must describe the cached photo fix in Chinese')
assertContains(releaseNotes, '人工确认条码状态修复', 'release notes must keep the V3.0.71 barcode manual confirmation fix in Chinese')
assertContains(releaseNotes, '数据中台照片加载修复', 'release notes must describe the data center photo fix in Chinese')
assertContains(releaseNotes, '删除项目驾驶舱系统状态', 'release notes must describe removing system status in Chinese')
assertContains(opsStatus, `return "${expectedVersion}"`, `system status version must be ${expectedVersion}`)
assertContains(apiMain, `version="${expectedVersion}"`, `FastAPI app version must be ${expectedVersion}`)
assertContains(webIndex, `Module Manager V${expectedVersion}`, `web HTML title must be ${expectedVersion}`)
assertContains(legacyLayout, `V${expectedVersion}`, `legacy layout must show ${expectedVersion}`)

console.log('project board and data center photo checks passed')
