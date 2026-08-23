import assert from 'node:assert/strict'
import test from 'node:test'

import { encodeCode128B } from '../src/features/collectorTransfer/code128.ts'
import {
  inventoryResultPresentation,
  nextWorkbenchItemIndex,
  workbenchItemsForMode,
} from '../src/features/collectorTransfer/state.ts'


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


test('workbench mode keeps meter installs and collector removals separate', () => {
  const items = [
    { id: 'meter-1', kind: 'meter_install' as const },
    { id: 'collector-1', kind: 'collector_removal' as const },
    { id: 'meter-2', kind: 'meter_install' as const },
  ]

  assert.deepEqual(workbenchItemsForMode(items, 'install').map((item) => item.id), ['meter-1', 'meter-2'])
  assert.deepEqual(workbenchItemsForMode(items, 'removal').map((item) => item.id), ['collector-1'])
})


test('next workbench navigation clamps at both ends', () => {
  assert.equal(nextWorkbenchItemIndex(3, 0, -1), 0)
  assert.equal(nextWorkbenchItemIndex(3, 1, 1), 2)
  assert.equal(nextWorkbenchItemIndex(3, 2, 1), 2)
  assert.equal(nextWorkbenchItemIndex(0, 0, 1), 0)
})


test('Code 128 B encoding preserves the exact scanned text and checksum', () => {
  assert.deepEqual(encodeCode128B('1234'), [104, 17, 18, 19, 20, 88, 106])
  assert.throws(() => encodeCode128B('采集器'), /Code 128 B/)
})
