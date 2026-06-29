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
const packageJson = read('v2-web/package.json')
const expectedVersion = '3.0.70'

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
assertContains(releaseNotes, "version: 'V3.0.70'", 'release notes must include V3.0.70')
assertContains(releaseNotes, '数据中台照片加载修复', 'release notes must describe the data center photo fix in Chinese')
assertContains(releaseNotes, '删除项目驾驶舱系统状态', 'release notes must describe removing system status in Chinese')
assertContains(opsStatus, `return "${expectedVersion}"`, `system status version must be ${expectedVersion}`)
assertContains(apiMain, `version="${expectedVersion}"`, `FastAPI app version must be ${expectedVersion}`)
assertContains(packageJson, `"version": "${expectedVersion}"`, `web package version must be ${expectedVersion}`)

console.log('project board and data center photo checks passed')
