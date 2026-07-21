import assert from 'node:assert/strict'
import fs from 'node:fs'

const source = fs.readFileSync('v2-web/src/components/ReviewImageInspector.vue', 'utf8')

function section(start, end) {
  const startIndex = source.indexOf(start)
  const endIndex = source.indexOf(end, startIndex + start.length)
  assert.notEqual(startIndex, -1, `missing section ${start}`)
  assert.notEqual(endIndex, -1, `missing section end ${end}`)
  return source.slice(startIndex, endIndex)
}

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
assert.match(source, /const isInteractionBlocked = computed\(\(\) => props\.loading \|\| props\.disabled \|\| mode\.value === 'submitting'\)/)
assert.match(source, /!isInteractionBlocked\.value/)
assert.match(source, /if \(isInteractionBlocked\.value\) \{\s*pointer\.value = null/)
assert.match(source, /:disabled="isInteractionBlocked"/)
assert.match(source, /watch\(\(\) => props\.loading, \(loading, previousLoading\) =>/)
assert.match(source, /previousLoading && !loading && mode\.value === 'submitting'/)
assert.match(source, /function finishSubmission\(\)/)
assert.match(source, /defineExpose\(\{ resetSelection, finishSubmission \}\)/)
assert.match(section('function resetSelection()', 'function beginSelection()'), /barcodeType\.value = null/)
assert.match(section('function finishSubmission()', 'watch(() => props.src'), /barcodeType\.value = null/)
console.log('Review image inspector verification passed.')
