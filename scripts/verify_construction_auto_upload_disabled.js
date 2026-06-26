#!/usr/bin/env node

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..')
const constructionView = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ConstructionView.vue'), 'utf8')

assert.match(
  constructionView,
  /async function uploadCurrentDraft\(\)/,
  'manual current draft upload must remain available',
)
assert.match(
  constructionView,
  /async function uploadAllCached\(\)/,
  'manual cached draft batch upload must remain available',
)
assert.match(
  constructionView,
  /async function uploadDraft\(draft: CacheDraft\)/,
  'shared uploadDraft implementation must remain available for manual upload',
)

assert.doesNotMatch(
  constructionView,
  /setInterval\(\s*\(\)\s*=>\s*\{[\s\S]*autoUploadCachedDrafts\(\)[\s\S]*?\}\s*,\s*AUTO_UPLOAD_INTERVAL_MS\s*\)/,
  'construction page must not schedule automatic cached draft uploads',
)
assert.doesNotMatch(
  constructionView,
  /async function autoUploadCachedDrafts\(\)/,
  'automatic cached draft upload worker must be removed while production auto upload is disabled',
)
assert.doesNotMatch(
  constructionView,
  /AUTO_UPLOAD_INTERVAL_MS\s*=\s*5\s*\*\s*60_000/,
  'five-minute automatic upload interval must be removed while production auto upload is disabled',
)

console.log('construction auto upload disabled checks passed')
