#!/usr/bin/env node

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const EXPECTED_VERSION = '3.0.38'
const EXPECTED_LABEL = `V${EXPECTED_VERSION}`
const escapedVersion = EXPECTED_VERSION.replaceAll('.', '\\.')

const root = path.resolve(__dirname, '..')
const read = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8')

const releaseNotesPath = path.join(root, 'v2-web', 'src', 'constants', 'releaseNotes.ts')
assert.equal(fs.existsSync(releaseNotesPath), true, 'release notes data file must exist')

const releaseNotes = fs.readFileSync(releaseNotesPath, 'utf8')
assert.match(releaseNotes, new RegExp(`APP_VERSION\\s*=\\s*'${escapedVersion}'`), `APP_VERSION must be ${EXPECTED_VERSION}`)
assert.match(releaseNotes, new RegExp(`version:\\s*'${EXPECTED_LABEL.replaceAll('.', '\\.')}'`), `release notes must include ${EXPECTED_LABEL}`)
assert.match(releaseNotes, /施工采集 00000000 工单修复/, 'release notes must describe the construction 00000000 fix in Chinese')
assert.match(releaseNotes, /每 5 分钟自动上传缓存/, 'release notes must describe the construction auto upload shutdown in Chinese')
assert.match(releaseNotes, /测试资料组/, 'release notes must describe the mock group fallback root cause in Chinese')
assert.match(releaseNotes, /00000000/, 'release notes must describe the construction 00000000 fix')
assert.match(releaseNotes, /version:\s*'V3\.0\.26'/, 'release notes must include V3.0.26')
assert.match(releaseNotes, /version:\s*'V3\.0\.25'/, 'release notes must include V3.0.25')
assert.match(releaseNotes, /version:\s*'V3\.0\.24'/, 'release notes must include V3.0.24')
assert.match(releaseNotes, /KPI 效率计时口径修正/, 'release notes must describe the KPI efficiency timing update in Chinese')
assert.match(releaseNotes, /在线时长融合 KPI/, 'release notes must describe the KPI online fusion update in Chinese')
assert.match(releaseNotes, /00000000/, 'release notes must keep the construction placeholder fix')
assert.doesNotMatch(releaseNotes, /TODO|TBD|placeholder/i, 'release notes must not contain placeholders')

const appLayout = read('v2-web/src/layouts/AppLayout.vue')
assert.match(appLayout, /releaseNotesVisible/, 'AppLayout must own the release notes dialog state')
assert.match(appLayout, /isAdmin/, 'AppLayout must gate the entry to administrators')
assert.match(appLayout, /v-if="isAdmin"/, 'release notes entry must be admin-only')
assert.match(appLayout, /更新内容|鏇存柊鍐呭/, 'AppLayout must render a Chinese update entry')
assert.match(appLayout, /<ElDialog[\s\S]*(更新内容|鏇存柊鍐呭)/, 'AppLayout must render the update dialog')

const loginView = read('v2-web/src/views/LoginView.vue')
assert.match(loginView, /APP_VERSION/, 'LoginView must read the shared APP_VERSION')
assert.doesNotMatch(loginView, /V3\.0\.24/, 'LoginView must not hard-code the old version')

const webIndex = read('v2-web/index.html')
assert.match(webIndex, new RegExp(`Module Manager V${escapedVersion}`), `web HTML title must be ${EXPECTED_VERSION}`)

const legacyLayout = read('v2-web/src/components/AppLayout.vue')
assert.doesNotMatch(legacyLayout, /V3\.0\.24/, 'legacy layout must not show the old version')
assert.match(legacyLayout, new RegExp(`V${escapedVersion}`), 'legacy layout must show the new version')

const packageJson = JSON.parse(read('v2-web/package.json'))
assert.equal(packageJson.version, EXPECTED_VERSION, `web package version must be ${EXPECTED_VERSION}`)

const pyproject = read('v2-api/pyproject.toml')
assert.match(pyproject, new RegExp(`version = "${escapedVersion}"`), `API package version must be ${EXPECTED_VERSION}`)
assert.match(pyproject, new RegExp(`V${escapedVersion}`), `API description must mention V${EXPECTED_VERSION}`)

const mainPy = read('v2-api/app/main.py')
assert.match(mainPy, new RegExp(`version="${escapedVersion}"`), `FastAPI version must be ${EXPECTED_VERSION}`)

const opsStatus = read('v2-api/app/services/ops_status.py')
assert.match(opsStatus, new RegExp(`return "${escapedVersion}"`), `ops status version must be ${EXPECTED_VERSION}`)

console.log('admin release notes checks passed')
