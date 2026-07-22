import assert from 'node:assert/strict'
import test from 'node:test'

import {
  mapBarcodeDashboardState,
  mapBarcodeVerificationState,
  mapPhotoCategoryState,
} from '../v2-web/src/utils/barcodeVerificationState.mjs'

const statusCases = [
  ['not_eligible', '不符合核验条件', 'info'],
  ['pending', '待核验', 'info'],
  ['processing', '核验中', 'primary'],
  ['passed', '机器通过', 'success'],
  ['partial', '部分通过', 'warning'],
  ['unreadable', '无法识别', 'warning'],
  ['mismatch', '核验不符', 'danger'],
  ['manual_confirmed', '人工确认通过', 'success'],
  ['failed', '核验失败', 'danger'],
]

test('maps every durable verification status without collapsing machine and manual passes', () => {
  for (const [status, label, type] of statusCases) {
    const mapped = mapBarcodeVerificationState({
      barcodeVerificationStatus: status,
      barcodeVerificationPassedCount: status === 'partial' ? 2 : undefined,
    })
    assert.equal(mapped.status, status)
    assert.equal(mapped.label, label)
    assert.equal(mapped.type, type)
  }
})

test('clamps durable progress to every supported 0/3 through 3/3 value', () => {
  for (const passedCount of [0, 1, 2, 3]) {
    const mapped = mapBarcodeVerificationState({
      barcodeVerificationStatus: passedCount === 3 ? 'passed' : 'partial',
      barcodeVerificationPassedCount: passedCount,
      barcodeVerificationTotalCount: 3,
    })
    assert.equal(mapped.passedCount, passedCount)
    assert.equal(mapped.totalCount, 3)
    assert.equal(mapped.progressLabel, `${passedCount}/3`)
  }
})

test('uses durable recognition source and keeps manual confirmation explicit', () => {
  assert.deepEqual(
    mapBarcodeVerificationState({
      barcodeVerificationStatus: 'passed',
      barcodeVerificationSource: 'machine_qr',
      barcodeVerificationPassedCount: 3,
    }).source,
    { key: 'machine', label: '机器识别' },
  )
  assert.deepEqual(
    mapBarcodeVerificationState({
      barcodeVerificationStatus: 'manual_confirmed',
      barcodeVerificationSource: 'manual_confirmed',
      barcodeVerificationPassedCount: 3,
    }).source,
    { key: 'manual', label: '人工确认' },
  )
})

test('prefers durable nested verification while preserving legacy flat fields', () => {
  const durable = mapBarcodeVerificationState({
    barcodeVerification: {
      status: 'processing',
      recognitionSource: 'machine_barcode',
      result: { passedCount: 1 },
    },
    groupBarcodeCheckStatus: 'matched',
    groupBarcodePassedCount: 3,
  })
  assert.equal(durable.status, 'processing')
  assert.equal(durable.progressLabel, '1/3')

  const legacy = mapBarcodeVerificationState({
    groupBarcodeCheckStatus: 'mismatched',
    groupBarcodePassedCount: 1,
  })
  assert.equal(legacy.status, 'mismatch')
  assert.equal(legacy.progressLabel, '1/3')
})

test('durable nested status wins over a stale legacy manual confirmation flag', () => {
  const mapped = mapBarcodeVerificationState({
    barcodeVerification: {
      status: 'pending',
      recognitionSource: '',
      result: { passedCount: 0 },
    },
    groupBarcodeManualConfirmed: true,
    groupBarcodePassedCount: 3,
  })

  assert.equal(mapped.status, 'pending')
  assert.equal(mapped.progressLabel, '0/3')
  assert.deepEqual(mapped.source, { key: 'none', label: '未识别' })
})

test('maps complete, duplicate, missing, and invalid-count photo category states', () => {
  assert.equal(
    mapPhotoCategoryState({
      photoCategoryStatus: 'complete',
      photoCategoryClassifiedCount: 4,
      photoCategoryTotalCount: 4,
    }).label,
    '分类完整 4/4',
  )
  assert.equal(
    mapPhotoCategoryState({
      photoCategoryStatus: 'duplicate',
      photoCategoryClassifiedCount: 4,
      photoCategoryTotalCount: 4,
    }).label,
    '分类重复 4/4',
  )
  assert.equal(
    mapPhotoCategoryState({
      photoCategoryStatus: 'missing',
      photoCategoryClassifiedCount: 3,
      photoCategoryTotalCount: 4,
    }).label,
    '分类缺失 3/4',
  )
  assert.equal(
    mapPhotoCategoryState({
      photoCategoryStatus: 'invalid_count',
      photoCategoryClassifiedCount: 3,
      photoCategoryTotalCount: 3,
    }).label,
    '数量异常 3/4',
  )
})

test('derives category state from photos when the API status is absent', () => {
  const photo = (category) => ({ category, isActive: true })
  assert.equal(
    mapPhotoCategoryState({
      photos: [photo('before_box'), photo('collector_barcode'), photo('module_meter'), photo('after_box')],
    }).status,
    'complete',
  )
  assert.equal(
    mapPhotoCategoryState({
      photos: [photo('before_box'), photo('before_box'), photo('module_meter'), photo('after_box')],
    }).status,
    'duplicate',
  )
  assert.equal(
    mapPhotoCategoryState({
      photos: [photo('before_box'), photo('collector_barcode'), photo('module_meter'), photo('unclassified')],
    }).status,
    'missing',
  )
  assert.equal(mapPhotoCategoryState({ photos: [photo('before_box')] }).status, 'invalid_count')
})

test('maps dashboard accuracy from completed eligible groups and keeps not eligible separate', () => {
  const mapped = mapBarcodeDashboardState({
    groupBarcodeAccuracyChecked: 4,
    groupBarcodeAccuracyPassed: 3,
    groupBarcodeAccuracyFailed: 1,
    groupBarcodeAccuracyUnreadable: 0,
    groupBarcodeAccuracyNotRequired: 7,
    groupBarcodeAccuracyRate: 0.25,
  })

  assert.equal(mapped.checked, 4)
  assert.equal(mapped.passed, 3)
  assert.equal(mapped.notEligible, 7)
  assert.equal(mapped.rate, 0.75)
  assert.equal(mapped.rateLabel, '75%')
})
