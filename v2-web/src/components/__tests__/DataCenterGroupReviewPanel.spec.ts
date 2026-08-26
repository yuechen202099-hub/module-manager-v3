import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
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
  confirmDataCenterGroupBarcode: vi.fn(),
  fetchDataCenterDetail: vi.fn(),
  fetchGroupPhotoObjectUrl: vi.fn(),
  rescanDataCenterGroupPhotoBarcode: vi.fn(),
  resetAdminGroupToUnconstructed: vi.fn(),
  resetAdminGroupToUnreviewed: vi.fn(),
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
    apiMock.confirmDataCenterGroupBarcode.mockResolvedValue({})
    apiMock.rescanDataCenterGroupPhotoBarcode.mockResolvedValue({})
    apiMock.resetAdminGroupToUnconstructed.mockResolvedValue({})
    apiMock.resetAdminGroupToUnreviewed.mockResolvedValue({})
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
