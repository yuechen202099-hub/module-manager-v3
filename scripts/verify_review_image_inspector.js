import assert from 'node:assert/strict'
import fs from 'node:fs'

const source = fs.readFileSync('v2-web/src/components/ReviewImageInspector.vue', 'utf8')
assert.match(source, /type BarcodeType = 'meter' \| 'module' \| 'collector'/)
assert.match(source, /const MAGNIFIER_SCALE = 2\.5/)
assert.match(source, /naturalWidth/)
assert.match(source, /naturalHeight/)
assert.match(source, /object-fit:\s*contain/)
assert.match(source, /emit\('scan'/)
assert.match(source, /emit\('open'/)
assert.match(source, /0\.\.1|Math\.min\(1/)
assert.match(source, /框选扫码/)
assert.match(source, /识别选区/)
assert.match(source, /取消框选/)
assert.doesNotMatch(source, /自动判断|自动分类/)
console.log('Review image inspector verification passed.')
