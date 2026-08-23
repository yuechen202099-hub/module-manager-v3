import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { CollectorInventoryDecision, CollectorPhotoRegistration } from '@/api/types'
import CollectorInventoryView from '@/views/CollectorInventoryView.vue'

const serviceMocks = vi.hoisted(() => ({
  createCollectorTransferRun: vi.fn(),
  fetchCollectorTransferRuns: vi.fn(),
  importCollectorInventory: vi.fn(),
  scanPhysicalCollector: vi.fn(),
  uploadPhysicalCollectorPhoto: vi.fn(),
}))

const workspaceMock = vi.hoisted(() => ({
  projects: [{ id: 'project-1', name: '城南改造' }],
  activeProject: { id: 'project-1', name: '城南改造' },
  loadProjects: vi.fn(),
}))

vi.mock('@/api/services', () => serviceMocks)
vi.mock('@/stores/workspace', () => ({ useWorkspaceStore: () => workspaceMock }))
vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
}))

const run = {
  id: 'run-1',
  project_id: 'project-1',
  name: '城南改造 · 第三批',
  status: 'inventory' as const,
  terminal_count: 40,
  meter_count: 120,
  collector_requirement_count: 120,
  blocked_terminal_count: 0,
  direct_match_count: 38,
  pool_available_count: 0,
  assignment_count: 38,
  diagnostics: [],
  created_at: '2026-08-23T00:00:00Z',
}

function decision(
  kind: CollectorInventoryDecision['decision'],
  requiresPhoto: boolean,
  addToPool: boolean,
): CollectorInventoryDecision {
  return {
    collector_id: `collector-${kind}`,
    collector_no: 'CG-2026-0819-0036',
    decision: kind,
    requires_photo: requiresPhoto,
    add_to_pool: addToPool,
    pool_status: requiresPhoto ? 'awaiting_photo' : addToPool ? 'available' : 'direct',
    requirement_id: addToPool ? null : 'requirement-1',
    photo: requiresPhoto ? null : {
      id: 'photo-1',
      image_url: '/photos/collector.jpg',
      preview_url: '/photos/collector-preview.jpg',
    } as CollectorInventoryDecision['photo'],
  }
}

async function mountPage() {
  const wrapper = mount(CollectorInventoryView, { attachTo: document.body })
  await flushPromises()
  return wrapper
}

async function submitManualScan(wrapper: Awaited<ReturnType<typeof mountPage>>) {
  await wrapper.get('#collector-number').setValue('CG-2026-0819-0036')
  await wrapper.get('form.manual-entry').trigger('submit')
  await flushPromises()
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, reject, resolve }
}

describe('CollectorInventoryView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    serviceMocks.fetchCollectorTransferRuns.mockResolvedValue([run])
    workspaceMock.loadProjects.mockResolvedValue(undefined)
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:collector-preview'),
      revokeObjectURL: vi.fn(),
    })
  })

  afterEach(() => {
    document.body.innerHTML = ''
    vi.unstubAllGlobals()
  })

  it.each([
    ['direct_reuse', false, false, '无需拍照', '不加入替换池', '继续扫码'],
    ['direct_needs_photo', true, false, '需要补拍', '直接匹配，不入池', '立即补拍'],
    ['pool_needs_photo', true, true, '需要补拍', '加入替换池', '立即补拍'],
    ['assignment_reuse', false, false, '已有分配', '不重复入池', '继续扫码'],
  ] as const)(
    'renders %s decision copy, action, and pool semantics',
    async (kind, requiresPhoto, addToPool, title, poolCopy, action) => {
      serviceMocks.scanPhysicalCollector.mockResolvedValue(decision(kind, requiresPhoto, addToPool))
      const wrapper = await mountPage()

      await submitManualScan(wrapper)

      expect(wrapper.get('[data-testid="decision-title"]').text()).toContain(title)
      expect(wrapper.get('[data-testid="pool-semantics"]').text()).toContain(poolCopy)
      expect(wrapper.get('[data-testid="decision-primary-action"]').text()).toContain(action)
      if (!requiresPhoto) expect(wrapper.find('[data-testid="photo-input"]').attributes('disabled')).toBeDefined()
      wrapper.unmount()
    },
  )

  it('states the mobile-only business boundary and exposes no customer-platform credentials or upload controls', async () => {
    const wrapper = await mountPage()

    expect(wrapper.text()).toContain('仅做盘点与补拍 · 不录入甲方平台')
    expect(wrapper.text()).toContain('摄像头无法识别时，可手工输入或使用扫码枪')
    expect(wrapper.text()).not.toMatch(/甲方账号|甲方密码|平台登录|自动上传/)
    expect(wrapper.find('input[type="password"]').exists()).toBe(false)
    expect(wrapper.find('a[href*="platform"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('uses the rear camera file input and shows local preview, uploading, and success feedback', async () => {
    serviceMocks.scanPhysicalCollector.mockResolvedValue(decision('direct_needs_photo', true, false))
    const upload = deferred<CollectorPhotoRegistration>()
    serviceMocks.uploadPhysicalCollectorPhoto.mockReturnValue(upload.promise)
    const wrapper = await mountPage()
    await submitManualScan(wrapper)

    const input = wrapper.get<HTMLInputElement>('[data-testid="photo-input"]')
    expect(input.attributes('accept')).toBe('image/*')
    expect(input.attributes('capture')).toBe('environment')
    const file = new File(['photo'], 'collector.jpg', { type: 'image/jpeg' })
    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
    await input.trigger('change')

    expect(wrapper.get<HTMLImageElement>('[data-testid="photo-preview"]').attributes('src')).toBe('blob:collector-preview')
    expect(wrapper.get('[data-testid="upload-status"]').text()).toContain('照片上传中')
    upload.resolve({
      collector_id: 'collector-direct_needs_photo',
      collector_no: 'CG-2026-0819-0036',
      pool_status: 'direct',
      assignment_id: null,
      photo: { id: 'photo-2', preview_url: '/photos/saved.jpg' } as CollectorPhotoRegistration['photo'],
    })
    await flushPromises()

    expect(wrapper.get('[data-testid="upload-status"]').text()).toContain('上传成功')
    expect(wrapper.get('[data-testid="pool-semantics"]').text()).toContain('直接匹配，不入池')
    wrapper.unmount()
  })

  it('keeps the preview and offers an explicit retry after photo upload failure', async () => {
    serviceMocks.scanPhysicalCollector.mockResolvedValue(decision('pool_needs_photo', true, true))
    serviceMocks.uploadPhysicalCollectorPhoto.mockRejectedValue(new Error('网络中断'))
    const wrapper = await mountPage()
    await submitManualScan(wrapper)
    const input = wrapper.get<HTMLInputElement>('[data-testid="photo-input"]')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [new File(['photo'], 'collector.jpg', { type: 'image/jpeg' })],
    })

    await input.trigger('change')
    await flushPromises()

    expect(wrapper.get('[data-testid="photo-preview"]').attributes('src')).toBe('blob:collector-preview')
    expect(wrapper.get('[data-testid="upload-status"]').text()).toContain('上传失败：网络中断')
    expect(wrapper.get('[data-testid="decision-primary-action"]').text()).toContain('重新上传')
    wrapper.unmount()
  })

  it('uses native BarcodeDetector continuously, deduplicates an in-flight value, and stops MediaStream tracks', async () => {
    const scan = deferred<CollectorInventoryDecision>()
    serviceMocks.scanPhysicalCollector.mockReturnValue(scan.promise)
    const stop = vi.fn()
    const stream = { getTracks: () => [{ stop }] }
    const getUserMedia = vi.fn().mockResolvedValue(stream)
    vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia } })
    const frameCallbacks: FrameRequestCallback[] = []
    vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => {
      frameCallbacks.push(callback)
      return frameCallbacks.length
    }))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    const detect = vi.fn()
      .mockResolvedValueOnce([{ rawValue: 'CG-2026-0819-0036' }])
      .mockResolvedValueOnce([{ rawValue: 'CG-2026-0819-0036' }])
    vi.stubGlobal('BarcodeDetector', class {
      static getSupportedFormats = vi.fn().mockResolvedValue(['code_128'])
      detect = detect
    })
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="start-camera"]').trigger('click')
    await flushPromises()
    expect(getUserMedia).toHaveBeenCalledWith(expect.objectContaining({ video: expect.objectContaining({ facingMode: expect.anything() }) }))
    expect(serviceMocks.scanPhysicalCollector).toHaveBeenCalledTimes(1)
    frameCallbacks.shift()?.(0)
    await flushPromises()
    expect(serviceMocks.scanPhysicalCollector).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-testid="scan-feedback"]').text()).toContain('正在查询，请勿重复扫码')

    scan.resolve(decision('direct_reuse', false, false))
    await flushPromises()
    expect(stop).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('leaves manual input and scanner-gun fallback usable when camera permission is denied', async () => {
    const getUserMedia = vi.fn().mockRejectedValue(new Error('NotAllowedError'))
    vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia } })
    vi.stubGlobal('BarcodeDetector', class { detect = vi.fn() })
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="start-camera"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="camera-status"]').text()).toContain('摄像头不可用')
    expect(wrapper.get('#collector-number').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })
})
