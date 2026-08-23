import assert from 'node:assert/strict'
import test from 'node:test'

import { encodeCode128B } from '../src/features/collectorTransfer/code128.ts'
import { inventoryResultPresentation } from '../src/features/collectorTransfer/state.ts'


test('same-number reusable photo is confirmed without camera or pool admission', () => {
  const result = inventoryResultPresentation({
    decision: 'direct_reuse',
    requiresPhoto: false,
    addToPool: false,
  })

  assert.deepEqual(result, {
    tone: 'success',
    title: '无需拍照，已登记',
    description: '同号采集器照片可复用，不加入替换池。',
    primaryAction: '继续扫码',
  })
})


test('pool candidate tells the mobile operator to photograph but never to enter customer platform data', () => {
  const result = inventoryResultPresentation({
    decision: 'pool_needs_photo',
    requiresPhoto: true,
    addToPool: true,
  })

  assert.equal(result.title, '需要补拍')
  assert.equal(result.description, '没有同号，补图后加入替换池。')
  assert.equal(result.primaryAction, '立即补拍')
  assert.doesNotMatch(Object.values(result).join(''), /甲方.*录入|上传甲方/)
})


test('an existing assignment is shown as reuse and can never re-enter the pool', () => {
  const result = inventoryResultPresentation({
    decision: 'assignment_reuse',
    requiresPhoto: false,
    addToPool: false,
  })

  assert.deepEqual(result, {
    tone: 'success',
    title: '已有分配',
    description: '该采集器已有分配记录，不重复入池。',
    primaryAction: '继续扫码',
  })
})


test('a photographed pool collector transitions to a completed result and next-scan action', () => {
  const result = inventoryResultPresentation({
    decision: 'pool_needs_photo',
    requiresPhoto: false,
    addToPool: true,
  })

  assert.deepEqual(result, {
    tone: 'success',
    title: '已加入替换池',
    description: '照片已保存，采集器已作为一次性替换资源登记。',
    primaryAction: '继续扫码',
  })
})


test('Code 128 B encoding preserves the exact scanned text and checksum', () => {
  assert.deepEqual(encodeCode128B('1234'), [104, 17, 18, 19, 20, 88, 106])
  assert.throws(() => encodeCode128B('采集器'), /Code 128 B/)
})
