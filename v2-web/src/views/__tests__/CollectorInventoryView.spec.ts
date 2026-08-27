import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

import type { CollectorInventoryDecision, CollectorPhotoRegistration } from '@/api/types'
import CollectorInventoryView from '@/views/CollectorInventoryView.vue'

const serviceMocks = vi.hoisted(() => ({
  createCollectorTransferRun: vi.fn(),
  fetchCollectorTransferProjects: vi.fn(),
  fetchCollectorTransferRuns: vi.fn(),
  fetchProjectCollectorInventory: vi.fn(),
  registerProjectCollector: vi.fn(),
  scanPhysicalCollector: vi.fn(),
  scanProjectCollector: vi.fn(),
  uploadPhysicalCollectorPhoto: vi.fn(),
}))

const workspaceMock = vi.hoisted(() => ({
  activeProject: { id: 'project-1', name: '城南改造' } as { id: string; name: string } | null,
}))
const reactiveWorkspaceMock = reactive(workspaceMock)

const authMock = vi.hoisted(() => ({
  user: { role: 'admin', roles: ['admin'] },
}))

vi.mock('@/api/services', () => serviceMocks)
vi.mock('@/stores/workspace', () => ({ useWorkspaceStore: () => reactiveWorkspaceMock }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => authMock }))
vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
}))

type DecisionKind =
  | 'direct_reuse'
  | 'direct_needs_photo'
  | 'pool_needs_photo'
  | 'existing_available'
  | 'existing_reserved'
  | 'existing_used'

function decision(
  kind: DecisionKind,
  requiresPhoto: boolean,
  addToPool: boolean,
): CollectorInventoryDecision {
  const poolStatus = kind.replace('existing_', '')
  return {
    collector_id: kind === 'pool_needs_photo' ? null : `collector-${kind}`,
    collector_no: 'CG-2026-0819-0036',
    decision: kind,
    requires_photo: requiresPhoto,
    add_to_pool: addToPool,
    pool_status: kind.startsWith('existing_')
      ? poolStatus
      : kind === 'pool_needs_photo'
        ? null
        : 'direct',
    photo: requiresPhoto ? null : {
      id: 'photo-1',
      image_url: '/photos/collector.jpg',
      preview_url: '/photos/collector-preview.jpg',
    },
  } as CollectorInventoryDecision
}

const emptyInventory = {
  items: [],
  total: 0,
  stats: { direct: 0, available: 0, reserved: 0, used: 0, awaiting_photo: 0 },
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

function stubUnavailableConstructionScanner() {
  const quagga = {
    init: vi.fn((_options: unknown, complete: (error?: unknown) => void) => complete(new Error('Quagga unavailable'))),
    onDetected: vi.fn(),
    offDetected: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
  }
  vi.stubGlobal('Quagga', quagga)
  return quagga
}

describe('CollectorInventoryView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    reactiveWorkspaceMock.activeProject = { id: 'project-1', name: '城南改造' }
    serviceMocks.fetchProjectCollectorInventory.mockResolvedValue(structuredClone(emptyInventory))
    serviceMocks.fetchCollectorTransferProjects.mockResolvedValue([{ id: 'project-1', name: '城南改造' }])
    serviceMocks.fetchCollectorTransferRuns.mockResolvedValue([{
      id: 'run-1',
      project_id: 'project-1',
      name: '旧批次',
      status: 'inventory',
    }])
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:collector-preview'),
      revokeObjectURL: vi.fn(),
    })
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  })

  afterEach(() => {
    document.body.innerHTML = ''
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('opens ready to scan for the current project without loading or selecting a run', async () => {
    const wrapper = await mountPage()

    expect(serviceMocks.fetchCollectorTransferRuns).not.toHaveBeenCalled()
    expect(serviceMocks.fetchCollectorTransferProjects).not.toHaveBeenCalled()
    expect(serviceMocks.fetchProjectCollectorInventory).toHaveBeenCalledWith('project-1')
    expect(wrapper.find('[data-testid="collector-run-select"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('当前批次')
    expect(wrapper.get('[data-testid="project-identity"]').text()).toContain('城南改造')
    expect(wrapper.get('[data-testid="start-camera"]').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('keeps the mobile boundary free of batch, import, and customer-platform entry controls', async () => {
    const wrapper = await mountPage()

    expect(wrapper.text()).toContain('只做扫码、拍照和入池判断')
    expect(wrapper.text()).not.toContain('新建盘点批次')
    expect(wrapper.text()).not.toContain('批量导入')
    expect(wrapper.find('input[name="customer_username"]').exists()).toBe(false)
    expect(wrapper.find('input[name="customer_password"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="customer-platform-upload"]').exists()).toBe(false)
    expect(serviceMocks.createCollectorTransferRun).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('shows only a safe project-selection state when there is no current project', async () => {
    reactiveWorkspaceMock.activeProject = null
    const wrapper = await mountPage()

    expect(wrapper.get('[data-testid="project-empty-state"]').text()).toContain('请先选择项目')
    expect(wrapper.find('[data-testid="start-camera"]').exists()).toBe(false)
    expect(wrapper.find('#collector-number').exists()).toBe(false)
    expect(serviceMocks.fetchProjectCollectorInventory).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it.each([
    ['direct_reuse', false, false, '无需拍照', '同号直接匹配', '继续扫码'],
    ['direct_needs_photo', true, false, '需要拍照', '直接匹配，不入池', '立即拍照'],
    ['pool_needs_photo', true, true, '需要拍照', '拍照后加入替换池', '立即拍照'],
    ['existing_available', false, false, '已在替换池', '已在替换池', '继续扫码'],
    ['existing_reserved', false, false, '已被占用', '禁止重复使用', '继续扫码'],
    ['existing_used', false, false, '已使用', '禁止重复使用', '继续扫码'],
  ] as const)(
    'renders the %s project-inventory decision without a run',
    async (kind, requiresPhoto, addToPool, title, poolCopy, action) => {
      serviceMocks.scanProjectCollector.mockResolvedValue(decision(kind, requiresPhoto, addToPool))
      const wrapper = await mountPage()

      await submitManualScan(wrapper)

      expect(serviceMocks.scanProjectCollector).toHaveBeenCalledWith(
        'project-1',
        'CG-2026-0819-0036',
      )
      expect(serviceMocks.scanPhysicalCollector).not.toHaveBeenCalled()
      expect(wrapper.get('[data-testid="decision-title"]').text()).toContain(title)
      expect(wrapper.get('[data-testid="pool-semantics"]').text()).toContain(poolCopy)
      expect(wrapper.get('[data-testid="decision-primary-action"]').text()).toContain(action)
      wrapper.unmount()
    },
  )

  it('keeps a same-number physical out of the website photo flow when no photo exists', async () => {
    serviceMocks.scanProjectCollector.mockResolvedValue({
      ...decision('direct_reuse', false, false),
      photo: null,
    })
    const wrapper = await mountPage()

    await submitManualScan(wrapper)

    expect(wrapper.get('[data-testid="decision-title"]').text()).toContain('无需拍照')
    expect(wrapper.text()).toContain('手上有同号实物')
    expect(wrapper.get('[data-testid="photo-input"]').attributes('disabled')).toBeDefined()
    expect(serviceMocks.registerProjectCollector).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('cancelling a non-direct photo never calls registration', async () => {
    serviceMocks.scanProjectCollector.mockResolvedValue(
      decision('pool_needs_photo', true, true),
    )
    const wrapper = await mountPage()
    await submitManualScan(wrapper)

    await wrapper.get<HTMLInputElement>('[data-testid="photo-input"]').trigger('cancel')
    await wrapper.get('[data-testid="capture-cancel"]').trigger('click')

    expect(serviceMocks.registerProjectCollector).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="photo-preview"]').exists()).toBe(false)
    expect(wrapper.find('.collector-card').exists()).toBe(false)
    wrapper.unmount()
  })

  it('registers the barcode and rear-camera photo together, then refreshes project inventory', async () => {
    serviceMocks.scanProjectCollector.mockResolvedValue(
      decision('pool_needs_photo', true, true),
    )
    const upload = deferred<CollectorPhotoRegistration>()
    serviceMocks.registerProjectCollector.mockReturnValue(upload.promise)
    const wrapper = await mountPage()
    await submitManualScan(wrapper)
    const input = wrapper.get<HTMLInputElement>('[data-testid="photo-input"]')
    expect(input.attributes('accept')).toBe('image/*')
    expect(input.attributes('capture')).toBe('environment')
    const file = new File(['photo'], 'collector.jpg', { type: 'image/jpeg' })
    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })

    await input.trigger('change')

    expect(serviceMocks.registerProjectCollector).toHaveBeenCalledWith(
      'project-1',
      'CG-2026-0819-0036',
      file,
    )
    expect(wrapper.get<HTMLImageElement>('[data-testid="photo-preview"]').attributes('src'))
      .toBe('blob:collector-preview')
    expect(wrapper.get('[data-testid="upload-status"]').text()).toContain('照片上传中')

    upload.resolve({
      collector_id: 'collector-pool',
      collector_no: 'CG-2026-0819-0036',
      pool_status: 'available',
      photo: { id: 'photo-pool', preview_url: '/photos/pool.jpg' },
    } as CollectorPhotoRegistration)
    await flushPromises()

    expect(wrapper.get('[data-testid="upload-status"]').text()).toContain('已加入替换池')
    expect(serviceMocks.fetchProjectCollectorInventory).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('keeps the local preview and retries the same in-memory file after upload failure', async () => {
    serviceMocks.scanProjectCollector.mockResolvedValue(
      decision('direct_needs_photo', true, false),
    )
    serviceMocks.registerProjectCollector
      .mockRejectedValueOnce(new Error('网络中断'))
      .mockResolvedValueOnce({
        collector_id: 'collector-direct',
        collector_no: 'CG-2026-0819-0036',
        pool_status: 'direct',
        photo: { id: 'photo-direct', preview_url: '/photos/direct.jpg' },
      } as CollectorPhotoRegistration)
    const wrapper = await mountPage()
    await submitManualScan(wrapper)
    const input = wrapper.get<HTMLInputElement>('[data-testid="photo-input"]')
    const file = new File(['photo'], 'collector.jpg', { type: 'image/jpeg' })
    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })

    await input.trigger('change')
    await flushPromises()

    expect(wrapper.get('[data-testid="upload-status"]').text()).toContain('上传失败：网络中断')
    expect(wrapper.get('[data-testid="photo-preview"]').attributes('src')).toBe('blob:collector-preview')
    expect(wrapper.get('[data-testid="decision-primary-action"]').text()).toContain('重新上传')

    await wrapper.get('[data-testid="decision-primary-action"]').trigger('click')
    await flushPromises()

    expect(serviceMocks.registerProjectCollector).toHaveBeenNthCalledWith(
      2,
      'project-1',
      'CG-2026-0819-0036',
      file,
    )
    expect(wrapper.get('[data-testid="upload-status"]').text()).toContain('上传成功')
    wrapper.unmount()
  })

  it('reuses the construction Quagga scanner before opening a competing native camera stream', async () => {
    const detectedHandlers: Array<(result: unknown) => void> = []
    const quagga = {
      init: vi.fn((_options: unknown, complete: (error?: unknown) => void) => complete()),
      onDetected: vi.fn((handler: (result: unknown) => void) => detectedHandlers.push(handler)),
      offDetected: vi.fn(),
      start: vi.fn(),
      stop: vi.fn(),
    }
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [] })
    const nativeDetect = vi.fn().mockResolvedValue([])
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('Quagga', quagga)
    vi.stubGlobal('BarcodeDetector', class { detect = nativeDetect })
    vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia } })
    serviceMocks.scanProjectCollector.mockResolvedValue(decision('direct_reuse', false, false))
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="start-camera"]').trigger('click')
    await flushPromises()

    expect(quagga.init).toHaveBeenCalledTimes(1)
    expect(quagga.start).toHaveBeenCalledTimes(1)
    expect(getUserMedia).not.toHaveBeenCalled()
    expect(nativeDetect).not.toHaveBeenCalled()
    detectedHandlers[0]?.({ codeResult: { code: 'CG-2026-0819-0036' } })
    await flushPromises()
    expect(serviceMocks.scanProjectCollector).toHaveBeenCalledWith('project-1', 'CG-2026-0819-0036')
    wrapper.unmount()
  })

  it('keeps the live barcode camera inside a closable scanner dialog', async () => {
    const quagga = {
      init: vi.fn((_options: unknown, complete: (error?: unknown) => void) => complete()),
      onDetected: vi.fn(),
      offDetected: vi.fn(),
      start: vi.fn(),
      stop: vi.fn(),
    }
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('Quagga', quagga)
    vi.stubGlobal('navigator', {
      ...navigator,
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [] }) },
    })
    const wrapper = await mountPage()

    expect(wrapper.find('[data-testid="inventory-scanner-dialog"]').exists()).toBe(false)
    await wrapper.get('[data-testid="start-camera"]').trigger('click')
    await flushPromises()

    const dialog = wrapper.get('[data-testid="inventory-scanner-dialog"]')
    expect(dialog.attributes('role')).toBe('dialog')
    expect(dialog.find('video.collector-camera-preview').exists()).toBe(true)
    expect(wrapper.find('.camera-stage video').exists()).toBe(false)

    await dialog.get('[data-testid="close-inventory-scanner"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="inventory-scanner-dialog"]').exists()).toBe(false)
    expect(quagga.stop).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('stops a partially started construction scanner before native fallback opens the camera', async () => {
    const detectedHandlers: Array<(result: unknown) => void> = []
    const quagga = {
      init: vi.fn((_options: unknown, complete: (error?: unknown) => void) => complete()),
      onDetected: vi.fn((handler: (result: unknown) => void) => detectedHandlers.push(handler)),
      offDetected: vi.fn(),
      start: vi.fn(() => { throw new Error('Quagga start failed') }),
      stop: vi.fn(),
    }
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [] })
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('Quagga', quagga)
    vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia } })
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="start-camera"]').trigger('click')
    await flushPromises()

    expect(quagga.onDetected).toHaveBeenCalledTimes(1)
    expect(quagga.offDetected).toHaveBeenCalledWith(detectedHandlers[0])
    expect(quagga.stop).toHaveBeenCalledTimes(1)
    expect(getUserMedia).toHaveBeenCalledTimes(1)
    expect(wrapper.get('video').element.srcObject).toBeTruthy()
    wrapper.unmount()
  })

  it('uses BarcodeDetector continuously after the construction scanner is unavailable, deduplicates an in-flight value, and stops camera tracks', async () => {
    const scan = deferred<CollectorInventoryDecision>()
    serviceMocks.scanProjectCollector.mockReturnValue(scan.promise)
    const stop = vi.fn()
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] })
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
    vi.stubGlobal('BarcodeDetector', class { detect = detect })
    stubUnavailableConstructionScanner()
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="start-camera"]').trigger('click')
    await flushPromises()
    expect(serviceMocks.scanProjectCollector).toHaveBeenCalledTimes(1)
    frameCallbacks.shift()?.(0)
    await flushPromises()
    expect(serviceMocks.scanProjectCollector).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-testid="scan-feedback"]').text()).toContain('正在查询')

    scan.resolve(decision('direct_reuse', false, false))
    await flushPromises()
    expect(stop).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('leaves manual entry usable when camera permission is denied', async () => {
    const getUserMedia = vi.fn().mockRejectedValue(new Error('NotAllowedError'))
    vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia } })
    vi.stubGlobal('BarcodeDetector', class { detect = vi.fn() })
    stubUnavailableConstructionScanner()
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="start-camera"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="camera-status"]').text()).toContain('摄像头不可用')
    expect(wrapper.get('#collector-number').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('catches a BarcodeDetector gate before getUserMedia by opening the preview without native detection', async () => {
    const stop = vi.fn()
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] })
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia } })
    stubUnavailableConstructionScanner()
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="start-camera"]').trigger('click')
    await flushPromises()

    expect(getUserMedia).toHaveBeenCalledTimes(1)
    expect(wrapper.get('video').element.srcObject).toBeTruthy()
    expect(wrapper.get('[data-testid="scan-feedback"]').text()).toContain('现场扫码工具不可用')
    expect(wrapper.get('#collector-number').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
    expect(stop).toHaveBeenCalledTimes(1)
  })

  it('catches removal of the generic-video retry after an environment-camera rejection', async () => {
    const stop = vi.fn()
    const getUserMedia = vi.fn()
      .mockRejectedValueOnce(new Error('No rear camera'))
      .mockResolvedValueOnce({ getTracks: () => [{ stop }] })
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia } })
    stubUnavailableConstructionScanner()
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="start-camera"]').trigger('click')
    await flushPromises()

    expect(getUserMedia).toHaveBeenNthCalledWith(1, {
      audio: false,
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
    })
    expect(getUserMedia).toHaveBeenNthCalledWith(2, { audio: false, video: true })
    expect(wrapper.get('video').element.srcObject).toBeTruthy()
    expect(wrapper.get('#collector-number').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
    expect(stop).toHaveBeenCalledTimes(1)
  })

  it('catches setting scanning before the native preview has played', async () => {
    const previewStart = deferred<void>()
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [] })
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia } })
    stubUnavailableConstructionScanner()
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockReturnValue(previewStart.promise)
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="start-camera"]').trigger('click')
    await flushPromises()

    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-testid="camera-status"]').text()).toContain('正在请求摄像头权限')
    previewStart.resolve()
    await flushPromises()
    expect(wrapper.get('[data-testid="scan-feedback"]').text()).not.toContain('正在请求摄像头权限')
    wrapper.unmount()
  })

  it('catches removal of the Quagga fallback and its shared one-in-flight submission guard', async () => {
    const detectedHandlers: Array<(result: unknown) => void> = []
    const quagga = {
      init: vi.fn((_options: unknown, complete: (error?: unknown) => void) => complete()),
      onDetected: vi.fn((handler: (result: unknown) => void) => detectedHandlers.push(handler)),
      offDetected: vi.fn(),
      start: vi.fn(),
      stop: vi.fn(),
    }
    const scan = deferred<CollectorInventoryDecision>()
    serviceMocks.scanProjectCollector.mockReturnValue(scan.promise)
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('Quagga', quagga)
    vi.stubGlobal('navigator', {
      ...navigator,
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [] }) },
    })
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="start-camera"]').trigger('click')
    await flushPromises()
    detectedHandlers[0]?.({ codeResult: { code: 'CG-2026-0819-0036' } })
    detectedHandlers[0]?.({ codeResult: { code: 'CG-2026-0819-0036' } })
    await flushPromises()

    expect(quagga.start).toHaveBeenCalledTimes(1)
    expect(serviceMocks.scanProjectCollector).toHaveBeenCalledTimes(1)
    scan.resolve(decision('direct_reuse', false, false))
    await flushPromises()
    expect(wrapper.get('[data-testid="decision-title"]').text()).toContain('无需拍照')
    expect(quagga.offDetected).toHaveBeenCalledTimes(1)
    expect(quagga.stop).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('catches a camera startup timeout that leaves manual entry in an endless starting state', async () => {
    vi.useFakeTimers()
    const never = new Promise<MediaStream>(() => undefined)
    const getUserMedia = vi.fn().mockReturnValue(never)
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia } })
    stubUnavailableConstructionScanner()
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="start-camera"]').trigger('click')
    await vi.advanceTimersByTimeAsync(14_100)
    await flushPromises()

    expect(getUserMedia).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[data-testid="camera-status"]').text()).toContain('摄像头不可用')
    expect(wrapper.get('#collector-number').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('catches a timed-out rear-camera request that later retains tracks instead of releasing them', async () => {
    vi.useFakeTimers()
    const rearRequest = deferred<MediaStream>()
    const genericRequest = deferred<MediaStream>()
    const rearStops = [vi.fn(), vi.fn()]
    const lateRearStream = {
      getTracks: () => rearStops.map((stop) => ({ stop })),
    } as unknown as MediaStream
    const getUserMedia = vi.fn()
      .mockReturnValueOnce(rearRequest.promise)
      .mockReturnValueOnce(genericRequest.promise)
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia } })
    stubUnavailableConstructionScanner()
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="start-camera"]').trigger('click')
    await vi.advanceTimersByTimeAsync(7_000)
    await flushPromises()
    rearRequest.resolve(lateRearStream)
    await flushPromises()

    expect(getUserMedia).toHaveBeenCalledTimes(2)
    expect(rearStops[0]).toHaveBeenCalledTimes(1)
    expect(rearStops[1]).toHaveBeenCalledTimes(1)
    expect(wrapper.get('video').element.srcObject).not.toBe(lateRearStream)
    expect(wrapper.get('[data-testid="camera-status"]').text()).toContain('正在请求摄像头权限')
    wrapper.unmount()
  })

  it('catches late camera startup retaining tracks or Quagga callbacks after unmount', async () => {
    const startup = deferred<MediaStream>()
    const stop = vi.fn()
    const quagga = stubUnavailableConstructionScanner()
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia: vi.fn().mockReturnValue(startup.promise) } })
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="start-camera"]').trigger('click')
    await flushPromises()
    wrapper.unmount()
    startup.resolve({ getTracks: () => [{ stop }] } as unknown as MediaStream)
    await flushPromises()

    expect(stop).toHaveBeenCalledTimes(1)
    expect(quagga.onDetected).not.toHaveBeenCalled()
    expect(quagga.start).not.toHaveBeenCalled()
  })

  it('catches a Quagga init timeout whose late success leaks its LiveStream', async () => {
    vi.useFakeTimers()
    let completeInit!: (error?: unknown) => void
    const quagga = {
      init: vi.fn((_options: unknown, complete: (error?: unknown) => void) => { completeInit = complete }),
      onDetected: vi.fn(),
      offDetected: vi.fn(),
      start: vi.fn(),
      stop: vi.fn(),
    }
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('Quagga', quagga)
    vi.stubGlobal('navigator', {
      ...navigator,
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [] }) },
    })
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="start-camera"]').trigger('click')
    await flushPromises()
    expect(quagga.init).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(7_000)
    await flushPromises()
    const stopsBeforeLateSuccess = quagga.stop.mock.calls.length
    completeInit()
    await flushPromises()

    expect(quagga.stop.mock.calls.length).toBeGreaterThan(stopsBeforeLateSuccess)
    expect(quagga.onDetected).not.toHaveBeenCalled()
    expect(quagga.start).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it.each([
    ['project change', async (wrapper: Awaited<ReturnType<typeof mountPage>>) => {
      reactiveWorkspaceMock.activeProject = { id: 'project-2', name: '城北改造' }
      await flushPromises()
    }],
    ['records view', async (wrapper: Awaited<ReturnType<typeof mountPage>>) => {
      await wrapper.get('nav.bottom-nav button[aria-label="盘点记录"]').trigger('click')
      await flushPromises()
    }],
    ['unmount', async (wrapper: Awaited<ReturnType<typeof mountPage>>) => {
      wrapper.unmount()
    }],
  ])('catches Quagga late init success after %s', async (_boundary, crossBoundary) => {
    let completeInit!: (error?: unknown) => void
    const quagga = {
      init: vi.fn((_options: unknown, complete: (error?: unknown) => void) => { completeInit = complete }),
      onDetected: vi.fn(),
      offDetected: vi.fn(),
      start: vi.fn(),
      stop: vi.fn(),
    }
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('Quagga', quagga)
    vi.stubGlobal('navigator', {
      ...navigator,
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [] }) },
    })
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="start-camera"]').trigger('click')
    await flushPromises()
    expect(quagga.init).toHaveBeenCalledTimes(1)
    await crossBoundary(wrapper)
    const stopsBeforeLateSuccess = quagga.stop.mock.calls.length
    completeInit()
    await flushPromises()

    expect(quagga.stop.mock.calls.length).toBeGreaterThan(stopsBeforeLateSuccess)
    expect(quagga.onDetected).not.toHaveBeenCalled()
    expect(quagga.start).not.toHaveBeenCalled()
    if (wrapper.exists()) wrapper.unmount()
  })

  it('shows only inventory from the active project in the records view', async () => {
    serviceMocks.fetchProjectCollectorInventory.mockResolvedValue({
      items: [{
        collector_id: 'collector-1',
        collector_no: 'PROJECT-1-COLLECTOR',
        pool_status: 'available',
        photo: { id: 'photo-1', preview_url: '/photos/1.jpg' },
        last_scanned_at: '2026-08-24T10:00:00Z',
        created_at: '2026-08-24T10:00:00Z',
      }],
      total: 1,
      stats: { direct: 0, available: 1, reserved: 0, used: 0, awaiting_photo: 0 },
    })
    const wrapper = await mountPage()

    await wrapper.get('nav.bottom-nav button[aria-label="盘点记录"]').trigger('click')

    expect(wrapper.get('[data-testid="inventory-records"]').text()).toContain('PROJECT-1-COLLECTOR')
    expect(serviceMocks.fetchProjectCollectorInventory).toHaveBeenCalledWith('project-1')
    wrapper.unmount()
  })

  it('revokes the local preview on unmount without creating another registration', async () => {
    serviceMocks.scanProjectCollector.mockResolvedValue(
      decision('pool_needs_photo', true, true),
    )
    serviceMocks.registerProjectCollector.mockRejectedValue(new Error('离线'))
    const wrapper = await mountPage()
    await submitManualScan(wrapper)
    const input = wrapper.get<HTMLInputElement>('[data-testid="photo-input"]')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [new File(['photo'], 'collector.jpg', { type: 'image/jpeg' })],
    })
    await input.trigger('change')
    await flushPromises()

    wrapper.unmount()

    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:collector-preview')
    expect(serviceMocks.registerProjectCollector).toHaveBeenCalledTimes(1)
  })
})
