#!/usr/bin/env node

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..')
const read = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8')

const releaseNotesPath = path.join(root, 'v2-web', 'src', 'constants', 'releaseNotes.ts')
assert.equal(fs.existsSync(releaseNotesPath), true, 'release notes data file must exist')

const releaseNotes = fs.readFileSync(releaseNotesPath, 'utf8')
assert.match(releaseNotes, /APP_VERSION\s*=\s*'3\.0\.26'/, 'APP_VERSION must be 3.0.26')
assert.match(releaseNotes, /version:\s*'V3\.0\.26'/, 'release notes must include V3.0.26')
assert.match(releaseNotes, /version:\s*'V3\.0\.25'/, 'release notes must include V3.0.25')
assert.match(releaseNotes, /version:\s*'V3\.0\.24'/, 'release notes must include V3.0.24')
assert.match(releaseNotes, /管理员顶部新增“更新内容”入口/, 'release notes must be written in Chinese')
assert.match(releaseNotes, /00000000/, 'release notes must describe the construction placeholder fix')
assert.doesNotMatch(releaseNotes, /TODO|TBD|placeholder/i, 'release notes must not contain placeholders')

const appLayout = read('v2-web/src/layouts/AppLayout.vue')
assert.match(appLayout, /releaseNotesVisible/, 'AppLayout must own the release notes dialog state')
assert.match(appLayout, /isAdmin/, 'AppLayout must gate the entry to administrators')
assert.match(appLayout, /v-if="isAdmin"/, 'release notes entry must be admin-only')
assert.match(appLayout, /更新内容/, 'AppLayout must render a Chinese update entry')
assert.match(appLayout, /<ElDialog[\s\S]*更新内容/, 'AppLayout must render the update dialog')

const loginView = read('v2-web/src/views/LoginView.vue')
assert.match(loginView, /APP_VERSION/, 'LoginView must read the shared APP_VERSION')
assert.doesNotMatch(loginView, /V3\.0\.24/, 'LoginView must not hard-code the old version')

const webIndex = read('v2-web/index.html')
assert.match(webIndex, /Module Manager V3\.0\.26/, 'web HTML title must be 3.0.26')

const legacyLayout = read('v2-web/src/components/AppLayout.vue')
assert.doesNotMatch(legacyLayout, /V3\.0\.24/, 'legacy layout must not show the old version')
assert.match(legacyLayout, /V3\.0\.26/, 'legacy layout must show the new version')

const packageJson = JSON.parse(read('v2-web/package.json'))
assert.equal(packageJson.version, '3.0.26', 'web package version must be 3.0.26')

const pyproject = read('v2-api/pyproject.toml')
assert.match(pyproject, /version = "3\.0\.26"/, 'API package version must be 3.0.26')
assert.match(pyproject, /V3\.0\.26/, 'API description must mention V3.0.26')

const mainPy = read('v2-api/app/main.py')
assert.match(mainPy, /version="3\.0\.26"/, 'FastAPI version must be 3.0.26')

const opsStatus = read('v2-api/app/services/ops_status.py')
assert.match(opsStatus, /return "3\.0\.26"/, 'ops status version must be 3.0.26')

console.log('admin release notes checks passed')
