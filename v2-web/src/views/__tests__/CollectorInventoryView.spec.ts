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

const authMock = vi.hoisted(() => ({
  user: { role: 'admin', roles: ['admin'] } as { role: string; roles: string[] } | null,
}))

vi.mock('@/api/services', () => serviceMocks)
vi.mock('@/stores/workspace', () => ({ useWorkspaceStore: () => workspaceMock }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => authMock }))
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

const otherProjectRun = {
  ...run,
  id: 'run-2',
  project_id: 'project-2',
  name: '城北改造 · 第一批',
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
    workspaceMock.projects = [{ id: 'project-1', name: '城南改造' }]
    workspaceMock.activeProject = { id: 'project-1', name: '城南改造' }
    workspaceMock.loadProjects.mockResolvedValue(undefined)
    authMock.user = { role: 'admin', roles: ['admin'] }
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

  it('keeps the active project identity visible and filters runs by that project', async () => {
    const wrapper = await mountPage()

    expect(wrapper.get('[data-testid="project-identity"]').text()).toContain('城南改造')
    expect(wrapper.get('[data-testid="project-identity"]').text()).toContain('project-1')
    expect(serviceMocks.fetchCollectorTransferRuns).toHaveBeenCalledWith('project-1')
    wrapper.unmount()
  })

  it('keeps setup project changes as a draft until a new run is created successfully', async () => {
    workspaceMock.projects = [
      { id: 'project-1', name: '城南改造' },
      { id: 'project-2', name: '城北改造' },
    ]
    serviceMocks.fetchCollectorTransferRuns.mockImplementation(async (projectId: string) => (
      projectId === 'project-2' ? [otherProjectRun] : [run]
    ))
    serviceMocks.createCollectorTransferRun.mockResolvedValue(otherProjectRun)
    const wrapper = await mountPage()
    const currentRunSelect = wrapper.get<HTMLSelectElement>('[aria-label="当前盘点批次"]')

    expect(wrapper.get('[data-testid="project-identity"]').text()).toContain('城南改造')
    expect(currentRunSelect.element.value).toBe('run-1')
    expect(Array.from(currentRunSelect.element.options, (option) => option.value)).toEqual(['', 'run-1'])
    expect(serviceMocks.fetchCollectorTransferRuns).toHaveBeenCalledWith('project-1')

    await wrapper.get('[aria-label="选择盘点批次"]').trigger('click')
    const setupProjectSelect = wrapper.findAll<HTMLSelectElement>('.setup-dialog select')[1]
    await setupProjectSelect.setValue('project-2')

    expect(wrapper.get('[data-testid="project-identity"]').text()).toContain('城南改造')
    expect(currentRunSelect.element.value).toBe('run-1')
    expect(Array.from(currentRunSelect.element.options, (option) => option.value)).toEqual(['', 'run-1'])
    expect(serviceMocks.fetchCollectorTransferRuns).not.toHaveBeenCalledWith('project-2')

    await wrapper.get('[aria-label="关闭"]').trigger('click')
    expect(wrapper.get('[data-testid="project-identity"]').text()).toContain('城南改造')
    expect(currentRunSelect.element.value).toBe('run-1')
    expect(serviceMocks.fetchCollectorTransferRuns).not.toHaveBeenCalledWith('project-2')

    await wrapper.get('[aria-label="选择盘点批次"]').trigger('click')
    await wrapper.findAll<HTMLSelectElement>('.setup-dialog select')[1].setValue('project-2')
    await wrapper.get('form.setup-dialog').trigger('submit')
    await flushPromises()

    expect(serviceMocks.createCollectorTransferRun).toHaveBeenCalledWith('project-2', expect.any(String))
    expect(serviceMocks.fetchCollectorTransferRuns).toHaveBeenCalledWith('project-2')
    expect(wrapper.get('[data-testid="project-identity"]').text()).toContain('城北改造')
    expect(wrapper.get('[data-testid="project-identity"]').text()).toContain('project-2')
    expect(currentRunSelect.element.value).toBe('run-2')
    expect(Array.from(currentRunSelect.element.options, (option) => option.value)).toEqual(['', 'run-2'])
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

  it('shows a completed pool result and continue-scan action after a pool photo upload succeeds', async () => {
    serviceMocks.scanPhysicalCollector.mockResolvedValue(decision('pool_needs_photo', true, true))
    serviceMocks.uploadPhysicalCollectorPhoto.mockResolvedValue({
      collector_id: 'collector-pool_needs_photo',
      collector_no: 'CG-2026-0819-0036',
      pool_status: 'available',
      assignment_id: null,
      photo: { id: 'photo-pool', preview_url: '/photos/pool.jpg' } as CollectorPhotoRegistration['photo'],
    })
    const wrapper = await mountPage()
    await submitManualScan(wrapper)
    const input = wrapper.get<HTMLInputElement>('[data-testid="photo-input"]')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [new File(['pool-photo'], 'pool.jpg', { type: 'image/jpeg' })],
    })

    await input.trigger('change')
    await flushPromises()

    expect(wrapper.get('[data-testid="decision-title"]').text()).toContain('已加入替换池')
    expect(wrapper.get('[data-testid="pool-semantics"]').text()).toContain('已加入替换池')
    expect(wrapper.get('[data-testid="decision-primary-action"]').text()).toContain('继续扫码')
    expect(wrapper.text()).not.toContain('需要补拍')
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

  it.each([
    ['盘点记录', 'records'],
    ['批量导入', 'import'],
  ])('stops the camera and cancels its frame when switching to %s', async (label) => {
    const stop = vi.fn()
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] })
    vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia } })
    vi.stubGlobal('requestAnimationFrame', vi.fn(() => 73))
    const cancelAnimationFrame = vi.fn()
    vi.stubGlobal('cancelAnimationFrame', cancelAnimationFrame)
    vi.stubGlobal('BarcodeDetector', class { detect = vi.fn().mockResolvedValue([]) })
    const wrapper = await mountPage()
    await wrapper.get('[data-testid="start-camera"]').trigger('click')
    await flushPromises()

    await wrapper.get(`nav.bottom-nav button[aria-label="${label}"]`).trigger('click')
    await flushPromises()

    expect(stop).toHaveBeenCalledTimes(1)
    expect(cancelAnimationFrame).toHaveBeenCalledWith(73)
    wrapper.unmount()
  })

  it('surfaces a completed duplicate scan instead of silently replacing the recent result', async () => {
    serviceMocks.scanPhysicalCollector.mockResolvedValue(decision('direct_reuse', false, false))
    const wrapper = await mountPage()
    await submitManualScan(wrapper)
    await wrapper.get('[data-testid="decision-primary-action"]').trigger('click')
    await flushPromises()

    await submitManualScan(wrapper)

    expect(serviceMocks.scanPhysicalCollector).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[data-testid="completed-duplicate-feedback"]').text()).toContain('重复扫码')
    expect(wrapper.get('[data-testid="completed-duplicate-feedback"]').text()).toContain('已扫码')
    wrapper.unmount()
  })

  it('shows admin setup/import actions but hides them for constructors', async () => {
    const adminWrapper = await mountPage()
    expect(adminWrapper.find('[aria-label="选择盘点批次"]').exists()).toBe(true)
    expect(adminWrapper.find('nav.bottom-nav button[aria-label="批量导入"]').exists()).toBe(true)
    adminWrapper.unmount()

    authMock.user = { role: 'constructor', roles: ['constructor'] }
    serviceMocks.fetchCollectorTransferRuns.mockResolvedValue([])
    const constructorWrapper = await mountPage()
    expect(constructorWrapper.find('[aria-label="选择盘点批次"]').exists()).toBe(false)
    expect(constructorWrapper.find('nav.bottom-nav button[aria-label="批量导入"]').exists()).toBe(false)
    expect(constructorWrapper.find('.setup-dialog').exists()).toBe(false)
    expect(constructorWrapper.get('[data-testid="constructor-empty-state"]').text()).toContain('暂无可盘点批次')
    expect(constructorWrapper.get('[data-testid="constructor-empty-state"]').text()).toContain('管理员')
    constructorWrapper.unmount()
  })
})
