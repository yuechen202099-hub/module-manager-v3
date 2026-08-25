import assert from 'node:assert/strict'
import test from 'node:test'

import { encodeCode128B } from '../src/features/collectorTransfer/code128.ts'
import { inventoryResultPresentation } from '../src/features/collectorTransfer/state.ts'


test('same-number physical is confirmed without a website photo or pool admission', () => {
  const result = inventoryResultPresentation({
    decision: 'direct_reuse',
    requiresPhoto: false,
    addToPool: false,
  })

  assert.deepEqual(result, {
    tone: 'success',
    title: '无需拍照，已确认',
    description: '已确认手上有同号实物，无需在网站拍照，也不加入替换池。',
    primaryAction: '继续扫码',
  })
})


test('pool candidate tells the mobile operator to photograph but never to enter customer platform data', () => {
  const result = inventoryResultPresentation({
    decision: 'pool_needs_photo',
    requiresPhoto: true,
    addToPool: true,
  })

  assert.equal(result.title, '需要拍照')
  assert.equal(result.description, '没有同号，补图后加入替换池。')
  assert.equal(result.primaryAction, '立即拍照')
  assert.doesNotMatch(Object.values(result).join(''), /甲方.*录入|上传甲方/)
})


test('reserved inventory is blocked and can never re-enter the pool', () => {
  const result = inventoryResultPresentation({
    decision: 'existing_reserved',
    requiresPhoto: false,
    addToPool: false,
  })

  assert.deepEqual(result, {
    tone: 'warning',
    title: '已被占用',
    description: '该采集器已被任务预留，禁止重复使用。',
    primaryAction: '继续扫码',
  })
})


test('used inventory is a terminal blocking decision', () => {
  const result = inventoryResultPresentation({
    decision: 'existing_used',
    requiresPhoto: false,
    addToPool: false,
  })

  assert.deepEqual(result, {
    tone: 'danger',
    title: '已使用',
    description: '该采集器已经使用，禁止再次加入替换池。',
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
