#!/usr/bin/env node

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..')
const read = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8')

const authStore = read('v2-web/src/stores/auth.ts')
assert.match(authStore, /function\s+isTokenExpired/, 'auth store must detect expired JWT tokens before reuse')
assert.match(authStore, /Date\.now\(\)/, 'auth store expiry check must compare token exp with current time')
assert.match(authStore, /clearStoredAuth\(\)/, 'auth store must clear expired local sessions')
assert.match(authStore, /readStoredToken[\s\S]*isTokenExpired/, 'stored tokens must be rejected when expired')

const services = read('v2-web/src/api/services.ts')
assert.match(services, /function\s+redirectToLogin/, 'API service must centralize login redirect')
assert.match(services, /function\s+handleUnauthorizedResponse/, 'API service must handle HTTP 401 centrally')
assert.match(services, /response\.status\s*===\s*401/, 'API service must treat 401 as an expired login')
assert.match(services, /localStorage\.removeItem\('v2-web-token'\)/, '401 handling must clear Vue auth token')
assert.match(services, /localStorage\.removeItem\('module_manager_session'\)/, '401 handling must clear legacy session')
assert.match(services, /window\.location\.assign/, '401 handling must navigate to login page')
assert.match(services, /fetchWithAuth/, 'authenticated fetch operations must go through the 401-aware wrapper')
assert.match(services, /fetchGroupPhotoObjectUrl[\s\S]*fetchWithAuth/, 'photo fetch must redirect on expired login')
assert.match(services, /downloadExcel[\s\S]*fetchWithAuth/, 'export fetch must redirect on expired login')
assert.match(services, /exportExceptionMeters[\s\S]*fetchWithAuth/, 'exception export fetch must redirect on expired login')
assert.match(
  services,
  /const response = sameOrigin[\s\S]*\? await fetchWithAuth\(requestUrl\.href,\s*\{\s*headers:\s*formHeaders\(\)\s*\}\)[\s\S]*: await fetch\(requestUrl\.href\)/,
  'cross-origin image fetch must not clear the app login session on third-party 401',
)
assert.match(
  services,
  /fetchWithAuth\(`\/local-test\/photo-proxy\?url=/,
  'same-origin image proxy fallback must still redirect on expired login',
)

const constructionView = read('v2-web/src/views/ConstructionView.vue')
assert.match(constructionView, /APP_VERSION/, 'construction page must import and render APP_VERSION')
assert.match(constructionView, /construction-version/, 'construction page must expose a visible version label')
assert.match(constructionView, /V\{\{\s*APP_VERSION\s*\}\}/, 'construction page must render the version number')

console.log('daily login and construction version checks passed')
