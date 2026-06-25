#!/usr/bin/env node

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')

const root = path.resolve(__dirname, '..')
const helperPath = path.join(root, 'v2-web', 'src', 'utils', 'constructionDraftGuards.ts')

if (!fs.existsSync(helperPath)) {
  throw new Error(`missing guard module: ${path.relative(root, helperPath)}`)
}

const ts = require(path.join(root, 'v2-web', 'node_modules', 'typescript'))
const source = fs.readFileSync(helperPath, 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
  },
}).outputText

const sandbox = { module: { exports: {} } }
sandbox.exports = sandbox.module.exports
vm.runInNewContext(compiled, sandbox, { filename: helperPath })
const guards = sandbox.module.exports

const placeholderDraftWithPhotos = {
  client_batch_id: 'task-00000000',
  taskId: 'task-1',
  groupId: '00000000',
  meter_no: '00000000',
  terminal: 'T-001',
  address: '待导入总清单地址',
  collector: '',
  module_asset_no: 'MOD-001',
  covered_slots: ['before_box', 'module_meter', 'after_box'],
  photos: [
    { slot: 'before_box' },
    { slot: 'module_meter' },
    { slot: 'after_box' },
  ],
}

const normalDraft = {
  client_batch_id: 'task-G001',
  taskId: 'task-1',
  groupId: 'G001',
  meter_no: 'A12345678',
  terminal: 'T-001',
  address: '1栋101',
  collector: 'COL-001',
  module_asset_no: 'MOD-001',
  covered_slots: ['before_box', 'module_meter', 'after_box'],
  photos: [{ slot: 'module_meter' }],
}

const placeholderGroup = {
  id: '00000000',
  taskId: 'task-1',
  meterNo: '00000000',
  meterMatchKey: '00000000',
  terminal: 'T-001',
  address: '待导入总清单地址',
  status: 'pending',
  photoCount: 0,
}

const normalGroup = {
  id: 'G001',
  taskId: 'task-1',
  meterNo: 'A12345678',
  terminal: 'T-001',
  address: '1栋101',
  status: 'pending',
  photoCount: 0,
}

const numericZeroGroup = {
  id: 0,
  taskId: 'task-1',
  meterNo: 0,
  meterMatchKey: 0,
  terminal: 'T-001',
  address: '',
  status: 'pending',
  photoCount: 0,
}

assert.equal(guards.isPlaceholderConstructionDraft(placeholderDraftWithPhotos), true)
assert.equal(guards.isEmptyPlaceholderConstructionDraft(placeholderDraftWithPhotos), false)
assert.equal(guards.isUploadableConstructionDraft(placeholderDraftWithPhotos), false)
assert.match(guards.constructionDraftUploadBlockReason(placeholderDraftWithPhotos), /00000000/)

assert.equal(guards.isPlaceholderConstructionDraft(normalDraft), false)
assert.equal(guards.isUploadableConstructionDraft(normalDraft), true)
assert.equal(guards.constructionDraftUploadBlockReason(normalDraft), '')

assert.equal(guards.isPlaceholderConstructionGroup(placeholderGroup), true)
assert.equal(guards.isCollectableConstructionGroup(placeholderGroup), false)
assert.match(guards.constructionGroupOpenBlockReason(placeholderGroup), /无工单/)

assert.equal(guards.isPlaceholderConstructionGroup(normalGroup), false)
assert.equal(guards.isCollectableConstructionGroup(normalGroup), true)
assert.equal(guards.constructionGroupOpenBlockReason(normalGroup), '')

assert.equal(guards.isAllZeroConstructionCode(0), true)
assert.equal(guards.isPlaceholderConstructionGroup(numericZeroGroup), true)
assert.equal(guards.isCollectableConstructionGroup(numericZeroGroup), false)

const constructionView = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ConstructionView.vue'), 'utf8')
assert.match(
  constructionView,
  /visibleUnmatchedTaskCards[\s\S]*isCollectableConstructionGroup[\s\S]*unmatchedRecordToConstructionGroup/,
  'unmatched construction task cards must filter placeholder records',
)

console.log('construction placeholder draft guard checks passed')
