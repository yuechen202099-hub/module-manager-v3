#!/usr/bin/env node

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..')
const constructionView = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ConstructionView.vue'), 'utf8')
const photoBuildMatch = constructionView.match(
  /const photos = Object\.entries\(selectedFiles\.value\)([\s\S]*?)\n\s*\.filter\(Boolean\) as DraftPhoto\[\]/,
)
assert.ok(photoBuildMatch, 'buildCurrentDraft must construct DraftPhoto records from selectedFiles')
const photoBuildBlock = photoBuildMatch[1]

assert.match(
  constructionView,
  /type DraftPhoto = \{[\s\S]*blob\?: Blob[\s\S]*filename\?: string[\s\S]*mime_type\?: string[\s\S]*size\?: number[\s\S]*\}/,
  'cached draft photos must keep stable Blob payload and metadata fields',
)
assert.match(
  constructionView,
  /blob: file\.slice\(0, file\.size, file\.type \|\| 'image\/jpeg'\)/,
  'cached draft photos must store a plain Blob copy for mobile WebView IndexedDB compatibility',
)
assert.doesNotMatch(
  photoBuildBlock,
  /\n\s*file,/,
  'new cached draft photos must not rely on direct File persistence only',
)
assert.match(
  constructionView,
  /const source = photo\.blob \|\| photo\.file/,
  'cached photo restore must prefer the stable Blob payload while remaining compatible with old File caches',
)
assert.match(
  constructionView,
  /photo\.mime_type \|\| source\.type \|\| 'image\/jpeg'/,
  'cached photo restore must preserve MIME type when recreating upload files',
)

console.log('construction draft photo cache checks passed')
