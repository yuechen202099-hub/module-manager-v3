const VERIFICATION_TOTAL = 3
const REQUIRED_CATEGORIES = ['before_box', 'collector_barcode', 'module_meter', 'after_box']
const DURABLE_STATUSES = new Set([
  'not_eligible',
  'pending',
  'processing',
  'passed',
  'partial',
  'unreadable',
  'mismatch',
  'manual_confirmed',
  'failed',
])

const STATUS_PRESENTATION = {
  not_eligible: { label: '不符合核验条件', type: 'info' },
  pending: { label: '待核验', type: 'info' },
  processing: { label: '核验中', type: 'primary' },
  passed: { label: '机器通过', type: 'success' },
  partial: { label: '部分通过', type: 'warning' },
  unreadable: { label: '无法识别', type: 'warning' },
  mismatch: { label: '核验不符', type: 'danger' },
  manual_confirmed: { label: '人工确认通过', type: 'success' },
  failed: { label: '核验失败', type: 'danger' },
}

const LEGACY_STATUSES = {
  matched: 'passed',
  mismatched: 'mismatch',
  not_required: 'not_eligible',
}

function finiteNumber(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function hasValue(value) {
  return value !== undefined && value !== null && value !== ''
}

function normalizeStatus(input, verification) {
  const durableValue = String(verification?.status || '').trim()
  if (DURABLE_STATUSES.has(durableValue)) return durableValue
  if (input.groupBarcodeManualConfirmed) return 'manual_confirmed'
  const value = String(input.barcodeVerificationStatus || input.groupBarcodeVerificationStatus || '').trim()
  if (DURABLE_STATUSES.has(value)) return value
  const legacy = String(input.groupBarcodeCheckStatus || '').trim()
  return LEGACY_STATUSES[legacy] || (DURABLE_STATUSES.has(legacy) ? legacy : 'not_eligible')
}

function normalizeSource(status, source) {
  const value = String(source || '').trim()
  if (status === 'manual_confirmed' || value === 'manual_confirmed' || value === 'manual') {
    return { key: 'manual', label: '人工确认' }
  }
  if (value || ['passed', 'partial', 'unreadable', 'mismatch', 'failed'].includes(status)) {
    return { key: 'machine', label: '机器识别' }
  }
  return { key: 'none', label: '未识别' }
}

export function mapBarcodeVerificationState(input = {}) {
  const verification = input.barcodeVerification || null
  const status = normalizeStatus(input, verification)
  const result = verification?.result || {}
  const totalCount = VERIFICATION_TOTAL
  const explicitPassed = hasValue(result.passedCount)
    ? result.passedCount
    : hasValue(input.barcodeVerificationPassedCount)
      ? input.barcodeVerificationPassedCount
      : input.groupBarcodePassedCount
  const defaultPassed = ['passed', 'manual_confirmed'].includes(status) ? totalCount : 0
  const passedCount = Math.max(0, Math.min(totalCount, Math.round(finiteNumber(explicitPassed, defaultPassed))))
  const presentation = STATUS_PRESENTATION[status]
  const sourceValue = verification?.recognitionSource || input.barcodeVerificationSource || ''

  return {
    status,
    label: presentation.label,
    type: presentation.type,
    passedCount,
    totalCount,
    progressLabel: `${passedCount}/${totalCount}`,
    source: normalizeSource(status, sourceValue),
    eligible: status !== 'not_eligible',
    reason: String(verification?.invalidationReason || input.barcodeVerificationReason || ''),
  }
}

function activePhotos(input) {
  if (!Array.isArray(input.photos)) return []
  return input.photos.filter((photo) => photo && photo.isActive !== false && photo.is_active !== false)
}

function normalizeCategoryStatus(value) {
  const status = String(value || '').trim()
  if (['complete', 'completed', 'valid'].includes(status)) return 'complete'
  if (['duplicate', 'duplicated', 'duplicate_category'].includes(status)) return 'duplicate'
  if (['missing', 'missing_category', 'incomplete'].includes(status)) return 'missing'
  if (['invalid_count', 'count_mismatch', 'invalid_photo_count'].includes(status)) return 'invalid_count'
  return ''
}

export function mapPhotoCategoryState(input = {}) {
  const photos = activePhotos(input)
  const totalSource = hasValue(input.photoCategoryTotalCount)
    ? input.photoCategoryTotalCount
    : photos.length || input.photoCount
  const totalCount = Math.max(0, Math.round(finiteNumber(totalSource, 0)))
  const categories = photos.map((photo) => String(photo.category || '').trim()).filter(Boolean)
  const classifiedFromPhotos = categories.filter((category) => category !== 'unclassified').length
  const classifiedCount = Math.max(
    0,
    Math.min(totalCount, Math.round(finiteNumber(input.photoCategoryClassifiedCount, classifiedFromPhotos))),
  )
  let status = normalizeCategoryStatus(input.photoCategoryStatus)

  if (!status) {
    if (totalCount !== REQUIRED_CATEGORIES.length) {
      status = 'invalid_count'
    } else if (photos.length) {
      const recognized = categories.filter((category) => REQUIRED_CATEGORIES.includes(category))
      status = new Set(recognized).size < recognized.length
        ? 'duplicate'
        : REQUIRED_CATEGORIES.every((category) => recognized.includes(category))
          ? 'complete'
          : 'missing'
    } else if (input.photoCategoryComplete) {
      status = 'complete'
    } else {
      status = classifiedCount >= REQUIRED_CATEGORIES.length ? 'duplicate' : 'missing'
    }
  }

  const details = {
    complete: { text: '分类完整', type: 'success' },
    duplicate: { text: '分类重复', type: 'danger' },
    missing: { text: '分类缺失', type: 'warning' },
    invalid_count: { text: '数量异常', type: 'danger' },
  }[status]

  return {
    status,
    label: `${details.text} ${classifiedCount}/${REQUIRED_CATEGORIES.length}`,
    type: details.type,
    classifiedCount,
    totalCount,
  }
}

export function mapBarcodeDashboardState(summary = {}) {
  const checked = Math.max(0, Math.round(finiteNumber(summary.groupBarcodeAccuracyChecked, 0)))
  const passed = Math.max(0, Math.min(checked, Math.round(finiteNumber(summary.groupBarcodeAccuracyPassed, 0))))
  const failed = Math.max(0, Math.round(finiteNumber(summary.groupBarcodeAccuracyFailed, 0)))
  const unreadable = Math.max(0, Math.round(finiteNumber(summary.groupBarcodeAccuracyUnreadable, 0)))
  const notEligible = Math.max(0, Math.round(finiteNumber(summary.groupBarcodeAccuracyNotRequired, 0)))
  const rate = checked ? passed / checked : 0
  return {
    checked,
    passed,
    failed,
    unreadable,
    notEligible,
    rate,
    rateLabel: `${Math.round(rate * 100)}%`,
  }
}
