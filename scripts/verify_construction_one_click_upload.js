#!/usr/bin/env node

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..')
const constructionView = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ConstructionView.vue'), 'utf8')
const uploadDraftMatch = constructionView.match(/async function uploadDraft\(draft: CacheDraft\) \{([\s\S]*?)\n\}/)
assert.ok(uploadDraftMatch, 'uploadDraft implementation must exist')
const uploadDraftBlock = uploadDraftMatch[1]

assert.match(
  constructionView,
  /async function uploadAllCached\(\)/,
  'construction page must keep the manual one-click cached upload entry',
)
assert.doesNotMatch(
  constructionView,
  /:disabled="!readyCachedDrafts\.length"/,
  'one-click upload buttons must not be disabled only because cached drafts are not pre-classified as ready',
)
assert.match(
  constructionView,
  /:disabled="uploading \|\| !cachedTaskDrafts\.length"/,
  'one-click upload buttons should remain clickable whenever the current task has cached drafts',
)
assert.match(
  constructionView,
  /for \(const draft of \[\.\.\.cachedTaskDrafts\.value\]\)/,
  'manual one-click upload should attempt cached drafts one by one and let uploadDraft keep per-draft safety checks',
)
assert.match(
  uploadDraftBlock,
  /constructionDraftUploadBlockReason\(draft\)/,
  'manual upload must keep the 00000000 and no-work-order guard before each draft upload',
)
assert.match(
  uploadDraftBlock,
  /!draft\.module_asset_no\?\.trim\(\)/,
  'manual upload must keep the missing module asset number guard before each draft upload',
)
assert.match(
  uploadDraftBlock,
  /missingSlotsForDraft\(draft\)/,
  'manual upload must keep the required-photo guard before each draft upload',
)
assert.match(
  uploadDraftBlock,
  /uploadConstructionBatch\(groupId,/,
  'manual upload must send only drafts that passed uploadDraft safety checks',
)
assert.doesNotMatch(
  constructionView,
  /autoUploadCachedDrafts|AUTO_UPLOAD_INTERVAL_MS/,
  'fix must not restore automatic cached draft upload',
)

console.log('construction one-click upload checks passed')
