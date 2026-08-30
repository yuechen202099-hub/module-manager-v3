import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { DataCenterDetail, GlobalMeterInstallWorkbenchRow, MaterialGroup } from '@/api/types'
import DataCenterGroupReviewPanel from '@/components/data-center/DataCenterGroupReviewPanel.vue'

type Deferred<T> = {
  promise: Promise<T>
  resolve: (value: T) => void
  reject: (reason?: unknown) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function detailFixture(id: string, auditAction = `loaded-${id}`, reviewStatus = 'pending'): DataCenterDetail {
  return {
    kind: 'group',
    id,
    terminal: `terminal-${id}`,
    meterNo: `meter-${id}`,
    meterMatchKey: `match-${id}`,
    address: `address-${id}`,
    collector: `collector-${id}`,
    moduleAssetNo: `module-${id}`,
    constructionCollector: '',
    constructionModuleAssetNo: '',
    installer: 'installer',
    photoCount: 1,
    classificationStatus: 'complete',
    classificationProgress: {},
    classificationManualConfirmation: null,
    classificationConfirmationFingerprint: `fingerprint-${id}`,
    anomalies: [],
    barcodeStatus: 'passed',
    barcodeProgress: {},
    groupBarcodeMissingFields: [],
    constructionStatus: 'constructed',
    archiveStatus: 'unarchived',
    exceptionStatus: '',
    reviewStatus,
    updatedAt: '2026-08-26T00:00:00Z',
    photos: [{
      id: `photo-${id}`,
      url: '',
      name: `photo-${id}`,
      status: 'valid',
      category: 'module_meter',
      categoryLabel: `photo-label-${id}`,
    }],
    audit: [{ action: auditAction, actor: 'admin', created_at: '2026-08-26T00:00:00Z' }],
  }
}

const apiMock = vi.hoisted(() => ({
  classifyDataCenterGroupPhoto: vi.fn(),
  confirmDataCenterGroupClassification: vi.fn(),
  confirmDataCenterGroupBarcode: vi.fn(),
  fetchDataCenterDetail: vi.fn(),
  fetchGroupPhotoObjectUrl: vi.fn(),
  getApiErrorStatus: vi.fn((error: unknown) => (error as { status?: number } | null)?.status),
  rescanDataCenterGroupPhotoBarcode: vi.fn(),
  resetAdminGroupToUnconstructed: vi.fn(),
  resetAdminGroupToUnreviewed: vi.fn(),
  resolveDataCenterGroupAnomaly: vi.fn(),
  returnDataCenterGroupToException: vi.fn(),
  reviewDataCenterGroup: vi.fn(),
  scanDataCenterGroupPhotoRegion: vi.fn(),
  updateDataCenterGroup: vi.fn(),
}))

vi.mock('@/api/services', () => apiMock)

function mountPanel(props: {
  groupId: string
  rephotoItem?: GlobalMeterInstallWorkbenchRow | null
  defaultStage?: 'source' | 'rephoto'
  classificationOnly?: boolean
}) {
  return mount(DataCenterGroupReviewPanel, {
    props,
    global: { plugins: [ElementPlus] },
  })
}

function buttonByText(wrapper: ReturnType<typeof mountPanel>, text: string) {
  const button = wrapper.findAll('button').find((candidate) => candidate.text().trim() === text)
  if (!button) throw new Error(`Missing button: ${text}`)
  return button
}

describe('DataCenterGroupReviewPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('ResizeObserver', class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
    apiMock.fetchDataCenterDetail.mockResolvedValue(detailFixture('default'))
    apiMock.fetchGroupPhotoObjectUrl.mockResolvedValue('blob:default')
    apiMock.classifyDataCenterGroupPhoto.mockResolvedValue({})
    apiMock.confirmDataCenterGroupClassification.mockResolvedValue({})
    apiMock.confirmDataCenterGroupBarcode.mockResolvedValue({})
    apiMock.rescanDataCenterGroupPhotoBarcode.mockResolvedValue({})
    apiMock.resetAdminGroupToUnconstructed.mockResolvedValue({})
    apiMock.resetAdminGroupToUnreviewed.mockResolvedValue({})
    apiMock.resolveDataCenterGroupAnomaly.mockResolvedValue({})
    apiMock.returnDataCenterGroupToException.mockResolvedValue({})
    apiMock.reviewDataCenterGroup.mockResolvedValue({} as MaterialGroup)
    apiMock.scanDataCenterGroupPhotoRegion.mockResolvedValue({})
    apiMock.updateDataCenterGroup.mockResolvedValue({ changedFields: [] })
  })

  afterEach(() => {
    document.body.innerHTML = ''
    vi.unstubAllGlobals()
  })

  it('sends the formal review contract without a client actor', async () => {
    const requests: Array<{ path: string; init: RequestInit }> = []
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init: RequestInit = {}) => {
      requests.push({ path: String(input), init })
      return {
        ok: true,
        status: 200,
        json: async () => ({ data: { id: 'g/encoded', status: 'approved' } }),
      } as Response
    })
    const realServices = await vi.importActual<typeof import('@/api/services')>('@/api/services')

    const result = await realServices.reviewDataCenterGroup('g/encoded', 'approved', 'checked', 'none')
    const body = JSON.parse(String(requests[0]?.init.body))

    expect(requests).toHaveLength(1)
    expect(requests[0]?.path).toBe('/groups/data-center/groups/g%2Fencoded/review')
    expect(requests[0]?.init.method).toBe('PATCH')
    expect(body).toEqual({ status: 'approved', note: 'checked', exception_note: 'none' })
    expect(body).not.toHaveProperty('actor')
    expect(result).toMatchObject({ id: 'g/encoded', status: 'approved' })
  })

  it('maps the explicit manual classification confirmation from group detail', async () => {
    vi.stubGlobal('fetch', async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        data: {
          kind: 'group',
          id: 'g-confirmed',
          status: 'approved',
          classification_manual_confirmation: {
            actor: 'admin',
            confirmed_at: '2026-08-27T12:00:00+08:00',
          },
          photos: [],
          audit: [],
        },
      }),
    }) as Response)
    const realServices = await vi.importActual<typeof import('@/api/services')>('@/api/services')

    const result = await realServices.fetchDataCenterDetail('group', 'g-confirmed')

    expect(result.classificationManualConfirmation).toEqual({
      actor: 'admin',
      confirmed_at: '2026-08-27T12:00:00+08:00',
    })
  })

  it('uses construction identifiers as the effective values in data-center rows', async () => {
    vi.stubGlobal('fetch', async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        data: {
          total: 2,
          page: 1,
          page_size: 20,
          items: [
            {
              kind: 'group',
              id: 'g-construction',
              collector: 'source-collector',
              module_asset_no: 'source-module',
              construction_collector: 'construction-collector',
              construction_module_asset_no: 'construction-module',
            },
            {
              kind: 'group',
              id: 'g-source-fallback',
              collector: 'fallback-collector',
              module_asset_no: 'fallback-module',
              construction_collector: '   ',
              construction_module_asset_no: '   ',
            },
          ],
        },
      }),
    }) as Response)
    const realServices = await vi.importActual<typeof import('@/api/services')>('@/api/services')

    const result = await realServices.fetchDataCenterRows({ page: 1, pageSize: 20 })

    expect(result.items[0]).toMatchObject({
      collector: 'construction-collector',
      moduleAssetNo: 'construction-module',
      constructionCollector: 'construction-collector',
      constructionModuleAssetNo: 'construction-module',
    })
    expect(result.items[1]).toMatchObject({
      collector: 'fallback-collector',
      moduleAssetNo: 'fallback-module',
    })
  })

  it('uses construction identifiers in the group detail consumed by the review form', async () => {
    vi.stubGlobal('fetch', async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        data: {
          kind: 'group',
          id: 'g-review-construction',
          collector: '',
          module_asset_no: '',
          construction_collector: 'review-collector',
          construction_module_asset_no: 'review-module',
          photos: [],
          audit: [],
        },
      }),
    }) as Response)
    const realServices = await vi.importActual<typeof import('@/api/services')>('@/api/services')

    const result = await realServices.fetchDataCenterDetail('group', 'g-review-construction')

    expect(result.collector).toBe('review-collector')
    expect(result.moduleAssetNo).toBe('review-module')
  })

  it('sends the manual classification confirmation contract without a client actor', async () => {
    const requests: Array<{ path: string; init: RequestInit }> = []
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init: RequestInit = {}) => {
      requests.push({ path: String(input), init })
      return {
        ok: true,
        status: 200,
        json: async () => ({ data: { id: 'g/encoded', status: 'approved' } }),
      } as Response
    })
    const realServices = await vi.importActual<typeof import('@/api/services')>('@/api/services')

    const result = await realServices.confirmDataCenterGroupClassification('g/encoded', true, 'fingerprint-visible')
    const body = JSON.parse(String(requests[0]?.init.body))

    expect(requests).toHaveLength(1)
    expect(requests[0]?.path).toBe('/groups/data-center/groups/g%2Fencoded/classification-manual-confirm')
    expect(requests[0]?.init.method).toBe('POST')
    expect(body).toEqual({ acknowledge_anomalies: true, expected_evidence_fingerprint: 'fingerprint-visible', source_page: 'review_rephoto_workbench' })
    expect(body).not.toHaveProperty('actor')
    expect(result).toMatchObject({ id: 'g/encoded', status: 'approved' })
  })

  it('maps anomaly history and sends the single-anomaly resolution contract', async () => {
    const requests: Array<{ path: string; init: RequestInit }> = []
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init: RequestInit = {}) => {
      requests.push({ path: String(input), init })
      return {
        ok: true,
        status: 200,
        json: async () => ({
          data: {
            kind: 'group',
            id: 'g/encoded',
            anomalies: [{
              code: 'module_missing',
              message: '缺少模块号',
              status: 'resolved',
              evidence_fingerprint: 'a'.repeat(64),
              resolved_by: 'admin-a',
              resolved_at: '2026-08-29T10:00:00+08:00',
            }],
            photos: [],
            audit: [],
          },
        }),
      } as Response
    })
    const realServices = await vi.importActual<typeof import('@/api/services')>('@/api/services')

    const result = await realServices.resolveDataCenterGroupAnomaly(
      'g/encoded',
      'module/missing',
      'a'.repeat(64),
    )
    const body = JSON.parse(String(requests[0]?.init.body))

    expect(requests[0]?.path).toBe('/groups/data-center/groups/g%2Fencoded/anomalies/module%2Fmissing/resolve')
    expect(requests[0]?.init.method).toBe('POST')
    expect(body).toEqual({
      expected_evidence_fingerprint: 'a'.repeat(64),
      source_page: 'review_rephoto_workbench',
    })
    expect(result.anomalies).toEqual([{
      code: 'module_missing',
      message: '缺少模块号',
      status: 'resolved',
      evidenceFingerprint: 'a'.repeat(64),
      resolvedBy: 'admin-a',
      resolvedAt: '2026-08-29T10:00:00+08:00',
    }])
  })

  it('aborts stale detail and ignores a late response after groupId changes', async () => {
    const requests = new Map<string, Deferred<DataCenterDetail>>()
    const signals = new Map<string, AbortSignal>()
    apiMock.fetchDataCenterDetail.mockImplementation((_kind, groupId: string, signal: AbortSignal) => {
      const request = deferred<DataCenterDetail>()
      requests.set(groupId, request)
      signals.set(groupId, signal)
      return request.promise
    })

    const wrapper = mountPanel({ groupId: 'g-1' })
    await flushPromises()
    await wrapper.setProps({ groupId: 'g-2' })

    expect(signals.get('g-1')?.aborted).toBe(true)
    requests.get('g-2')?.resolve(detailFixture('g-2'))
    await flushPromises()
    requests.get('g-1')?.resolve(detailFixture('g-1'))
    await flushPromises()

    expect(wrapper.text()).toContain('meter-g-2')
    expect(wrapper.text()).not.toContain('meter-g-1')
    wrapper.unmount()
  })

  it('aborts stale protected images and revokes every late, same-photo replacement, and unmounted URL exactly once', async () => {
    const photoRequests = new Map<string, Array<Deferred<string>>>()
    const photoSignals = new Map<string, AbortSignal>()
    const createdUrls: string[] = []
    const resolvePhoto = (request: Deferred<string> | undefined, objectUrl: string) => {
      createdUrls.push(objectUrl)
      request?.resolve(objectUrl)
    }
    apiMock.fetchDataCenterDetail.mockImplementation((_kind, groupId: string) => Promise.resolve(detailFixture(groupId)))
    apiMock.fetchGroupPhotoObjectUrl.mockImplementation(
      (groupId: string, _photoId: string, _kind: string, _version: string, signal: AbortSignal) => {
        const request = deferred<string>()
        const requests = photoRequests.get(groupId) || []
        requests.push(request)
        photoRequests.set(groupId, requests)
        photoSignals.set(groupId, signal)
        return request.promise
      },
    )

    const wrapper = mountPanel({ groupId: 'g-1' })
    await flushPromises()
    await wrapper.setProps({ groupId: 'g-2' })

    expect(photoSignals.get('g-1')?.aborted).toBe(true)
    resolvePhoto(photoRequests.get('g-2')?.[0], 'blob:g-2')
    await flushPromises()
    resolvePhoto(photoRequests.get('g-1')?.[0], 'blob:g-1-late')
    await flushPromises()

    await buttonByText(wrapper, '字段修正').trigger('click')
    await flushPromises()
    resolvePhoto(photoRequests.get('g-2')?.[1], 'blob:g-2-replacement')
    await flushPromises()
    wrapper.unmount()

    const revokedUrls = (URL.revokeObjectURL as ReturnType<typeof vi.fn>).mock.calls.flat()
    expect(revokedUrls).toHaveLength(createdUrls.length)
    expect(new Set(revokedUrls).size).toBe(createdUrls.length)
    expect([...revokedUrls].sort()).toEqual([...createdUrls].sort())
  })

  it('discards a review completion when the initiating group is no longer active', async () => {
    const reviewRequest = deferred<MaterialGroup>()
    const loadedGroupIds: string[] = []
    apiMock.fetchDataCenterDetail.mockImplementation((_kind, groupId: string) => {
      loadedGroupIds.push(groupId)
      return Promise.resolve(detailFixture(groupId))
    })
    apiMock.fetchGroupPhotoObjectUrl.mockImplementation((_groupId, photoId: string) => Promise.resolve(`blob:${photoId}`))
    apiMock.reviewDataCenterGroup.mockImplementation(() => reviewRequest.promise)

    const wrapper = mountPanel({ groupId: 'g-1' })
    await flushPromises()
    await buttonByText(wrapper, '正式通过').trigger('click')
    await flushPromises()
    await wrapper.setProps({ groupId: 'g-2' })
    await flushPromises()
    const updatedBeforeCompletion = wrapper.emitted('updated')?.length || 0
    const decidedBeforeCompletion = wrapper.emitted('review-decided')?.length || 0

    reviewRequest.resolve({ id: 'g-1', status: 'approved' } as MaterialGroup)
    await flushPromises()

    expect(loadedGroupIds).toEqual(['g-1', 'g-2'])
    expect(wrapper.text()).toContain('meter-g-2')
    expect(wrapper.text()).not.toContain('meter-g-1')
    expect(wrapper.emitted('updated')?.length || 0).toBe(updatedBeforeCompletion)
    expect(wrapper.emitted('review-decided')?.length || 0).toBe(decidedBeforeCompletion)
    wrapper.unmount()
  })

  it('keeps the active review locked when a stale field correction completes', async () => {
    const fieldCorrectionRequest = deferred<{ changedFields: string[] }>()
    const reviewRequest = deferred<MaterialGroup>()
    const loadedGroupIds: string[] = []
    apiMock.fetchDataCenterDetail.mockImplementation((_kind, groupId: string) => {
      loadedGroupIds.push(groupId)
      return Promise.resolve(detailFixture(groupId))
    })
    apiMock.fetchGroupPhotoObjectUrl.mockImplementation((_groupId, photoId: string) => Promise.resolve(`blob:${photoId}`))
    apiMock.updateDataCenterGroup.mockImplementation(() => fieldCorrectionRequest.promise)
    apiMock.reviewDataCenterGroup.mockImplementation(() => reviewRequest.promise)

    const wrapper = mountPanel({ groupId: 'g-1' })
    await flushPromises()
    await buttonByText(wrapper, '字段修正').trigger('click')
    await flushPromises()
    await wrapper.setProps({ groupId: 'g-2' })
    await flushPromises()
    await buttonByText(wrapper, '正式通过').trigger('click')
    await flushPromises()

    fieldCorrectionRequest.resolve({ changedFields: ['meter_no'] })
    await flushPromises()

    expect(loadedGroupIds).toEqual(['g-1', 'g-2'])
    expect(buttonByText(wrapper, '正式通过').attributes()).toHaveProperty('disabled')
    expect(wrapper.emitted('updated')).toBeUndefined()
    expect(wrapper.emitted('review-decided')).toBeUndefined()

    reviewRequest.resolve({ id: 'g-2', status: 'approved' } as MaterialGroup)
    await flushPromises()

    expect(loadedGroupIds).toEqual(['g-1', 'g-2', 'g-2'])
    expect(buttonByText(wrapper, '正式通过').attributes()).not.toHaveProperty('disabled')
    expect(wrapper.emitted('updated')).toHaveLength(1)
    expect(wrapper.emitted('updated')?.[0]?.[0]).toMatchObject({ id: 'g-2' })
    expect(wrapper.emitted('review-decided')).toEqual([['approved']])
    wrapper.unmount()
  })

  it.each([
    ['正式通过', 'approved'],
    ['资料不全', 'incomplete'],
  ] as const)('uses the formal review decision for %s and reloads server detail', async (label, status) => {
    let reviewStatus = 'pending'
    const reviewRequests: Array<{ groupId: string; status: string; note: string; exceptionNote: string }> = []
    apiMock.fetchDataCenterDetail.mockImplementation((_kind, groupId: string) => Promise.resolve(
      detailFixture(groupId, reviewStatus === 'pending' ? 'server-pending' : `server-${reviewStatus}`, reviewStatus),
    ))
    apiMock.fetchGroupPhotoObjectUrl.mockImplementation((_groupId, photoId: string) => Promise.resolve(`blob:${photoId}:${reviewStatus}`))
    apiMock.reviewDataCenterGroup.mockImplementation((groupId, nextStatus, note, exceptionNote) => {
      reviewRequests.push({ groupId, status: nextStatus, note, exceptionNote })
      reviewStatus = nextStatus
      return Promise.resolve({ id: groupId, status: nextStatus } as MaterialGroup)
    })

    const wrapper = mountPanel({ groupId: 'g-review' })
    await flushPromises()
    expect(wrapper.find('.el-dialog').exists()).toBe(false)

    await buttonByText(wrapper, label).trigger('click')
    await flushPromises()

    expect(reviewRequests).toEqual([{ groupId: 'g-review', status, note: '', exceptionNote: '' }])
    expect(wrapper.text()).toContain(`server-${status}`)
    expect(wrapper.text()).toContain(`审阅状态：${status}`)
    expect(wrapper.emitted('review-decided')).toEqual([[status]])
    expect(wrapper.emitted('updated')?.at(-1)?.[0]).toMatchObject({ id: 'g-review' })
    wrapper.unmount()
  })

  it('uses the classification-only mode to archive photos into the four existing categories', async () => {
    const classificationDetail = {
      ...detailFixture('g-classification'),
      classificationStatus: 'pending',
      photos: [
        { id: 'photo-before', url: '', name: 'photo-before', status: 'valid', category: 'unclassified', categoryLabel: '未分类' },
        { id: 'photo-collector', url: '', name: 'photo-collector', status: 'valid', category: 'collector_barcode', categoryLabel: '采集器条形码' },
        { id: 'photo-module', url: '', name: 'photo-module', status: 'valid', category: 'module_meter', categoryLabel: '模块与电能表' },
        { id: 'photo-after', url: '', name: 'photo-after', status: 'valid', category: 'after_box', categoryLabel: '表箱整体改造后' },
      ],
    } satisfies DataCenterDetail
    apiMock.fetchDataCenterDetail.mockResolvedValue(classificationDetail)
    apiMock.fetchGroupPhotoObjectUrl.mockImplementation((_groupId, photoId: string) => Promise.resolve(`blob:${photoId}`))

    const wrapper = mountPanel({ groupId: 'g-classification', classificationOnly: true })
    await flushPromises()

    expect(wrapper.findAll('.classification-photo-card')).toHaveLength(4)
    expect(wrapper.text()).toContain('照片分类 3/4')
    expect(wrapper.text()).toContain('表箱整体改造前')
    expect(wrapper.text()).toContain('采集器条形码')
    expect(wrapper.text()).toContain('模块与电能表')
    expect(wrapper.text()).toContain('表箱整体改造后')
    expect(wrapper.text()).not.toContain('正式通过')
    expect(wrapper.text()).not.toContain('资料不全')
    expect(wrapper.text()).not.toContain('异常 / 回退')

    await wrapper.get('[data-testid="preview-classification-photo-before"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="photo-lightbox"]').attributes('aria-modal')).toBe('true')
    expect(wrapper.get<HTMLImageElement>('[data-testid="photo-lightbox-image"]').attributes('src')).toBe('blob:photo-before')
    expect(apiMock.fetchGroupPhotoObjectUrl).toHaveBeenCalledWith(
      'g-classification',
      'photo-before',
      'original',
      '',
      expect.any(AbortSignal),
    )
    await wrapper.get('[data-testid="close-photo-lightbox"]').trigger('click')
    expect(wrapper.find('[data-testid="photo-lightbox"]').exists()).toBe(false)

    await wrapper.get('[data-testid="photo-category-photo-before"]').setValue('before_box')
    expect(wrapper.text()).toContain('照片分类 4/4')
    await wrapper.get('[data-testid="save-photo-classifications"]').trigger('click')
    await flushPromises()

    expect(apiMock.classifyDataCenterGroupPhoto).toHaveBeenCalledTimes(1)
    expect(apiMock.classifyDataCenterGroupPhoto).toHaveBeenCalledWith(
      'g-classification',
      'photo-before',
      'before_box',
      '审阅与翻拍照片分类',
    )
    expect(apiMock.reviewDataCenterGroup).not.toHaveBeenCalled()
    expect(apiMock.returnDataCenterGroupToException).not.toHaveBeenCalled()
    expect(wrapper.emitted('updated')?.at(-1)?.[0]).toMatchObject({ id: 'g-classification' })
    wrapper.unmount()
  })

  it('allows an administrator to manually confirm classification and warns when anomalies remain', async () => {
    const classificationDetail = {
      ...detailFixture('g-manual-classification'),
      classificationStatus: 'incomplete',
      barcodeStatus: 'unreadable',
      photos: [
        { id: 'photo-unclassified', url: '', name: 'photo-unclassified', status: 'valid', category: 'unclassified', categoryLabel: '未分类' },
        { id: 'photo-module', url: '', name: 'photo-module', status: 'valid', category: 'module_meter', categoryLabel: '模块与电能表' },
      ],
    } satisfies DataCenterDetail
    apiMock.fetchDataCenterDetail.mockResolvedValue(classificationDetail)
    apiMock.fetchGroupPhotoObjectUrl.mockImplementation((_groupId, photoId: string) => Promise.resolve(`blob:${photoId}`))
    const confirmDialog = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(
      'confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>,
    )

    const wrapper = mountPanel({ groupId: 'g-manual-classification', classificationOnly: true })
    await flushPromises()

    await wrapper.get('[data-testid="confirm-classification-complete"]').trigger('click')
    await flushPromises()

    expect(confirmDialog).toHaveBeenCalledTimes(1)
    expect(String(confirmDialog.mock.calls[0]?.[0])).toContain('仍有 1 张照片未分类')
    expect(String(confirmDialog.mock.calls[0]?.[0])).toContain('条码状态未通过')
    expect(apiMock.confirmDataCenterGroupClassification).toHaveBeenCalledWith(
      'g-manual-classification',
      true,
      'fingerprint-g-manual-classification',
    )
    expect(wrapper.emitted('review-decided')).toEqual([['approved']])
    expect(wrapper.emitted('updated')?.at(-1)?.[0]).toMatchObject({ id: 'g-manual-classification' })
    wrapper.unmount()
  })

  it('shows Chinese anomalies and keeps a resolved item as green history', async () => {
    const fingerprint = 'b'.repeat(64)
    const openDetail = {
      ...detailFixture('g-anomaly'),
      anomalies: [{
        code: 'module_missing',
        message: '缺少模块号',
        status: 'open',
        evidenceFingerprint: fingerprint,
        resolvedBy: '',
        resolvedAt: '',
      }],
    } satisfies DataCenterDetail
    const resolvedDetail = {
      ...openDetail,
      anomalies: [{
        ...openDetail.anomalies[0],
        status: 'resolved',
        resolvedBy: 'admin-a',
        resolvedAt: '2026-08-29T10:00:00+08:00',
      }],
    } satisfies DataCenterDetail
    let resolved = false
    apiMock.fetchDataCenterDetail.mockImplementation(() => Promise.resolve(resolved ? resolvedDetail : openDetail))
    apiMock.resolveDataCenterGroupAnomaly.mockImplementation(() => {
      resolved = true
      return Promise.resolve(resolvedDetail)
    })
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(
      'confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>,
    )

    const wrapper = mountPanel({ groupId: 'g-anomaly', classificationOnly: true })
    await flushPromises()

    expect(wrapper.get('[data-testid="anomaly-module_missing"]').text()).toContain('缺少模块号')
    expect(wrapper.get('[data-testid="resolve-anomaly-module_missing"]').text()).toBe('确认已修复')

    await wrapper.get('[data-testid="resolve-anomaly-module_missing"]').trigger('click')
    await flushPromises()

    expect(apiMock.resolveDataCenterGroupAnomaly).toHaveBeenCalledWith('g-anomaly', 'module_missing', fingerprint)
    expect(wrapper.get('[data-testid="anomaly-module_missing"]').classes()).toContain('resolved')
    expect(wrapper.get('[data-testid="anomaly-module_missing"]').text()).toContain('已确认修复')
    expect(wrapper.get('[data-testid="anomaly-module_missing"]').text()).toContain('admin-a')
    expect(wrapper.find('[data-testid="resolve-anomaly-module_missing"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('separates current anomalies from resolved history in the review panel', async () => {
    const detail = {
      ...detailFixture('g-anomaly-history', 'approved-history', 'approved'),
      exceptionStatus: '',
      anomalies: [
        {
          code: 'module_missing',
          message: '缺少模块号',
          status: 'open',
          evidenceFingerprint: 'a'.repeat(64),
          resolvedBy: '',
          resolvedAt: '',
        },
        {
          code: 'collector_missing',
          message: '缺少采集器号',
          status: 'resolved',
          evidenceFingerprint: 'a'.repeat(64),
          resolvedBy: 'module_admin',
          resolvedAt: '2026-08-29T18:47:02+08:00',
        },
      ],
    } satisfies DataCenterDetail
    apiMock.fetchDataCenterDetail.mockResolvedValue(detail)
    apiMock.fetchGroupPhotoObjectUrl.mockImplementation((_groupId, photoId: string) => Promise.resolve(`blob:${photoId}`))

    const wrapper = mountPanel({ groupId: detail.id })
    await flushPromises()

    const currentSection = wrapper.get('.exception-box')
    expect(currentSection.find('[data-testid="anomaly-module_missing"]').exists()).toBe(true)
    expect(currentSection.find('[data-testid="anomaly-collector_missing"]').exists()).toBe(false)
    const historySection = wrapper.get('[data-testid="anomaly-history"]')
    expect(historySection.text()).toContain('历史处理记录')
    expect(historySection.text()).toContain('缺少采集器号')
    expect(historySection.text()).toContain('module_admin')
    expect(historySection.text()).not.toContain('缺少模块号')
    wrapper.unmount()
  })

  it('reloads latest anomalies after a confirmation fingerprint conflict', async () => {
    const first = detailFixture('g-conflict')
    const latest = {
      ...first,
      classificationConfirmationFingerprint: 'fingerprint-latest',
      photos: [
        ...first.photos,
        { id: 'photo-new', url: '', name: 'photo-new', status: 'valid', category: 'unclassified', categoryLabel: '未分类' },
      ],
    } satisfies DataCenterDetail
    apiMock.fetchDataCenterDetail.mockResolvedValueOnce(first).mockResolvedValueOnce(latest)
    apiMock.confirmDataCenterGroupClassification.mockRejectedValue(
      Object.assign(new Error('分类证据或异常已变化，请重新加载最新异常后再次确认'), { status: 409 }),
    )
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(
      'confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>,
    )
    const wrapper = mountPanel({ groupId: 'g-conflict', classificationOnly: true })
    await flushPromises()

    await wrapper.get('[data-testid="confirm-classification-complete"]').trigger('click')
    await flushPromises()

    expect(apiMock.confirmDataCenterGroupClassification).toHaveBeenCalledWith(
      'g-conflict', true, 'fingerprint-g-conflict',
    )
    expect(apiMock.fetchDataCenterDetail).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('照片分类 1/2')
    expect(wrapper.emitted('review-decided')).toBeUndefined()
    wrapper.unmount()
  })

  it('shows that an approved classification-only group has been manually accepted', async () => {
    apiMock.fetchDataCenterDetail.mockResolvedValue(
      {
        ...detailFixture('g-confirmed', 'classification_manual_confirmed', 'approved'),
        classificationManualConfirmation: {
          actor: 'admin',
          confirmed_at: '2026-08-26T00:00:00Z',
        },
      },
    )

    const wrapper = mountPanel({ groupId: 'g-confirmed', classificationOnly: true })
    await flushPromises()

    expect(wrapper.text()).toContain('已人工确认分类完成')
    expect(wrapper.get('[data-testid="confirm-classification-complete"]').text()).toContain('重新确认')
    wrapper.unmount()
  })

  it('does not present an automatically approved group as manually confirmed', async () => {
    apiMock.fetchDataCenterDetail.mockResolvedValue(
      detailFixture('g-auto-approved', 'review_approved', 'approved'),
    )

    const wrapper = mountPanel({ groupId: 'g-auto-approved', classificationOnly: true })
    await flushPromises()

    expect(wrapper.text()).not.toContain('已人工确认分类完成')
    expect(wrapper.get('[data-testid="confirm-classification-complete"]').text()).toContain('人工确认分类完成')
    wrapper.unmount()
  })

  it('shows the rephoto stage only when supplied and renders exactly two slots with both barcodes', async () => {
    const sourceOnly = mountPanel({ groupId: 'g-source' })
    await flushPromises()
    expect(sourceOnly.find('[data-stage="rephoto"]').exists()).toBe(false)
    expect(sourceOnly.text()).not.toContain('翻拍位置')
    sourceOnly.unmount()

    const rephotoItem = {
      meter_item_id: 'meter-item-1',
      workbench_item_id: 'workbench-item-1',
      status: 'pending',
      meter_no: 'METER-001',
      meter_barcode: 'METER-BARCODE-001',
      module_no: 'MODULE-001',
      module_barcode: 'MODULE-BARCODE-001',
      photos: [
        { slot: 'after_box', label: '改造完成照片', photo: { id: 'after', preview_url: '/after.jpg' } },
        { slot: 'module_meter', label: '电表和模块照片', photo: { id: 'module', preview_url: '/module.jpg' } },
        { slot: 'module_meter', label: '重复位置不得出现', photo: { id: 'duplicate', preview_url: '/duplicate.jpg' } },
      ],
      diagnostics: [],
    } as unknown as GlobalMeterInstallWorkbenchRow

    const wrapper = mountPanel({ groupId: 'g-rephoto', rephotoItem, defaultStage: 'rephoto' })
    await flushPromises()

    expect(wrapper.find('[data-stage="rephoto"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-rephoto-slot]')).toHaveLength(2)
    expect(wrapper.text()).toContain('电表和模块照片')
    expect(wrapper.text()).toContain('改造完成照片')
    expect(wrapper.text()).not.toContain('重复位置不得出现')
    expect(wrapper.get('[aria-label="表号条码：METER-BARCODE-001"]').attributes('role')).toBe('img')
    expect(wrapper.get('[aria-label="模块号条码：MODULE-BARCODE-001"]').attributes('role')).toBe('img')
    wrapper.unmount()
  })
})
