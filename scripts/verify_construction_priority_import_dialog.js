import assert from 'node:assert/strict'
import fs from 'node:fs'

const dialog = fs.readFileSync('v2-web/src/components/ConstructionPriorityImportDialog.vue', 'utf8')
const view = fs.readFileSync('v2-web/src/views/ClaimTasksView.vue', 'utf8')
const services = fs.readFileSync('v2-web/src/api/services.ts', 'utf8')

assert.match(dialog, /const pageSize = 20/)
assert.match(dialog, /downloadConstructionPriorityTemplate/)
assert.match(dialog, /previewConstructionPriorityImport/)
assert.match(dialog, /confirmConstructionPriorityImport/)
assert.match(dialog, /valid|duplicate|conflict|unknown|completed|unchanged|malformed/)
assert.match(dialog, /ElPagination|el-pagination/)
assert.match(dialog, /items\.value\.slice/)
assert.match(dialog, /counts\.conflict.*counts\.malformed/)
assert.match(dialog, /@closed="reset"/)
assert.match(dialog, /emit\('imported'\)/)
assert.match(view, /ConstructionPriorityImportDialog/)
assert.match(view, /批量标记/)
assert.match(view, /taskRequestEpoch\.invalidate\(\)/)
assert.match(view, /sessionStorage\.removeItem\(claimTasksCacheKey\(\)\)/)
assert.match(services, /new FormData\(\)/)
assert.match(services, /confirm=\$\{confirm \? 'true' : 'false'\}/)

console.log('Construction priority import dialog verification passed.')
