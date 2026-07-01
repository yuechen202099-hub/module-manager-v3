#!/usr/bin/env node

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..')
const services = fs.readFileSync(path.join(root, 'v2-web', 'src', 'api', 'services.ts'), 'utf8')
const authStore = fs.readFileSync(path.join(root, 'v2-web', 'src', 'stores', 'auth.ts'), 'utf8')

assert.match(services, /response\.status === 401/, 'services.ts must handle 401 auth expiry responses')
assert.match(services, /redirectToLogin/, 'services.ts must redirect expired auth sessions to login')
assert.match(services, /response\.status === 429/, 'services.ts must preserve and surface rate-limit responses')
assert.match(authStore, /isTokenExpired/, 'auth store must reject expired stored tokens')
assert.match(authStore, /clearStoredAuth/, 'auth store must clear expired stored auth state')

console.log('frontend auth expiry and error handling checks passed')
