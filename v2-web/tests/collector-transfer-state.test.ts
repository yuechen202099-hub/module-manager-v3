import assert from 'node:assert/strict'
import test from 'node:test'

import { encodeCode128B } from '../src/features/collectorTransfer/code128.ts'
import {
  candidateLabel,
  canReplaceMissing,
  canRefreshTerminal,
  completionBlockers,
  inventoryResultPresentation,
  isCurrentRequest,
  meterCompletionBlockers,
} from '../src/features/collectorTransfer/state.ts'


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

test('global terminal helpers label duplicates, protect present completion, and require replacement evidence', () => {
  assert.equal(candidateLabel({
    terminal_code: 'T-001',
    project_name: '城南项目',
    installation_address: '安装地址',
    needs_disambiguation: true,
  }), 'T-001 · 城南项目 · 安装地址')
  assert.deepEqual(completionBlockers({
    physical_state: 'present',
    final_collector_no: 'C-01',
    collector_barcode: 'C-01',
    photo: null,
  }), [])
  assert.deepEqual(completionBlockers({
    physical_state: 'missing',
    final_collector_no: null,
    collector_barcode: null,
    photo: null,
  }), ['该采集器没有实物，需先完成替换'])
  assert.deepEqual(completionBlockers({
    physical_state: 'replaced',
    final_collector_no: 'POOL-01',
    collector_barcode: 'POOL-01',
    photo: null,
  }), ['替换采集器照片缺失'])
})

test('only an administrator with enough pool stock can replace every missing collector', () => {
  assert.equal(canReplaceMissing(false, 2, 2), false)
  assert.equal(canReplaceMissing(true, 1, 2), false)
  assert.equal(canReplaceMissing(true, 2, 2), true)
})

test('newer global terminal request sequences reject an older response', () => {
  const current = 2
  assert.equal(isCurrentRequest(1, current), false)
  assert.equal(isCurrentRequest(2, current), true)
})

test('refresh requires an admin, changed source, zero completion, and no active random assignment', () => {
  assert.equal(canRefreshTerminal(true, true, 0, []), true)
  assert.equal(canRefreshTerminal(false, true, 0, []), false)
  assert.equal(canRefreshTerminal(true, false, 0, []), false)
  assert.equal(canRefreshTerminal(true, true, 1, []), false)
  assert.equal(canRefreshTerminal(true, true, 0, ['assignment-1']), false)
})

test('meter completion requires exact two source slots, meter barcode, and module barcode', () => {
  const complete = { meter_barcode: 'M-01', module_barcode: 'MOD-01', photos: [
    { slot: 'module_meter', photo: { id: 'photo-a' } },
    { slot: 'after_box', photo: { id: 'photo-b' } },
  ] }
  assert.deepEqual(meterCompletionBlockers(complete), [])
  assert.deepEqual(meterCompletionBlockers({ ...complete, photos: [complete.photos[0]] }), ['缺少改造完成照片'])
})
