import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ConstructionView from '@/views/ConstructionView.vue'

const zxingMocks = vi.hoisted(() => ({
  decodeFromConstraints: vi.fn(),
  stop: vi.fn(),
}))

const serviceMocks = vi.hoisted(() => ({
  currentActor: vi.fn(() => 'installer-1'),
  currentTeamId: vi.fn(() => 'team-1'),
  fetchAllUnmatchedRecords: vi.fn().mockResolvedValue([]),
  fetchConstructionExceptionOrders: vi.fn().mockResolvedValue([]),
  fetchConstructionTaskGroups: vi.fn().mockResolvedValue([]),
  fetchConstructionTasks: vi.fn().mockResolvedValue([]),
  fetchGroup: vi.fn(),
  fetchUserAccounts: vi.fn().mockResolvedValue([]),
  recordConstructionHeartbeat: vi.fn().mockResolvedValue(undefined),
  recordConstructionNonIdleEvent: vi.fn().mockResolvedValue(undefined),
  releaseConstructionTask: vi.fn(),
  submitConstructionExceptionOrder: vi.fn(),
  uploadConstructionBatch: vi.fn(),
}))

vi.mock('@zxing/browser', () => ({
  BrowserMultiFormatReader: class {
    decodeFromConstraints = zxingMocks.decodeFromConstraints
  },
}))
vi.mock('@/api/services', () => serviceMocks)
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { id: 'installer-1', username: 'installer-1', role: 'installer', roles: ['installer'], teamId: 'team-1' },
    logout: vi.fn(),
  }),
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

describe('ConstructionView Android scanner fallback', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('indexedDB', {
      open: vi.fn(() => {
        throw new Error('IndexedDB unavailable in scanner unit test')
      }),
    })
    vi.stubGlobal('navigator', {
      ...navigator,
      mediaDevices: { getUserMedia: vi.fn() },
    })
  })

  afterEach(() => {
    document.body.innerHTML = ''
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('uses ZXing when Quagga fails instead of stalling on an Android BarcodeDetector that returns no result', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    let onZxingResult: ((result?: { getText: () => string }, error?: { name?: string }) => void) | undefined
    zxingMocks.decodeFromConstraints.mockImplementation(
      async (_constraints: unknown, _video: HTMLVideoElement, callback: typeof onZxingResult) => {
        onZxingResult = callback
        return { stop: zxingMocks.stop }
      },
    )
    const quagga = {
      init: vi.fn((_options: unknown, complete: (error?: unknown) => void) => complete(new Error('Android live init failed'))),
      onDetected: vi.fn(),
      offDetected: vi.fn(),
      start: vi.fn(),
      stop: vi.fn(),
    }
    const nativeDetect = vi.fn().mockResolvedValue([])
    vi.stubGlobal('Quagga', quagga)
    vi.stubGlobal('BarcodeDetector', class { detect = nativeDetect })

    const wrapper = mount(ConstructionView, {
      attachTo: document.body,
      global: {
        directives: { loading: () => undefined },
        stubs: {
          ElAlert: true,
          ElButton: {
            emits: ['click'],
            template: '<button @click="$emit(\'click\')"><slot /></button>',
          },
          ElDialog: { template: '<div><slot /></div>' },
          ElDrawer: { template: '<div><slot /></div>' },
          ElEmpty: true,
          ElIcon: true,
          ElInput: true,
          ElTag: { template: '<span><slot /></span>' },
        },
      },
    })
    await flushPromises()
    const scanButton = wrapper.findAll('button').find((button) => button.text().includes('扫表号'))
    expect(scanButton).toBeDefined()

    await scanButton!.trigger('click')
    await flushPromises()

    expect(zxingMocks.decodeFromConstraints).toHaveBeenCalledTimes(1)
    expect(warn).toHaveBeenCalledWith(
      'Construction Quagga scanner failed; falling back to ZXing.',
      expect.any(Error),
    )
    expect(nativeDetect).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('ZXing 正在识别条形码')

    onZxingResult?.({ getText: () => 'ANDROID-METER-001' })
    onZxingResult?.({ getText: () => 'ANDROID-METER-001' })
    await flushPromises()

    expect(wrapper.find('.scanner-backdrop').exists()).toBe(false)
    expect(zxingMocks.stop).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('stops controls from a closed ZXing session instead of letting an old promise replace the reopened scanner', async () => {
    // Production mutation caught: removing the per-open scanner session check lets this old promise own the reopened camera.
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    let resolveOldControls: ((controls: { stop: () => void }) => void) | undefined
    const oldControls = { stop: vi.fn() }
    const currentControls = { stop: vi.fn() }
    zxingMocks.decodeFromConstraints
      .mockImplementationOnce(
        () =>
          new Promise<{ stop: () => void }>((resolve) => {
            resolveOldControls = resolve
          }),
      )
      .mockResolvedValueOnce(currentControls)
    vi.stubGlobal('Quagga', {
      init: vi.fn((_options: unknown, complete: (error?: unknown) => void) => complete(new Error('Android live init failed'))),
      onDetected: vi.fn(),
      offDetected: vi.fn(),
      start: vi.fn(),
      stop: vi.fn(),
    })

    const wrapper = mount(ConstructionView, {
      attachTo: document.body,
      global: {
        directives: { loading: () => undefined },
        stubs: {
          ElAlert: true,
          ElButton: { emits: ['click'], template: '<button @click="$emit(\'click\')"><slot /></button>' },
          ElDialog: { template: '<div><slot /></div>' },
          ElDrawer: { template: '<div><slot /></div>' },
          ElEmpty: true,
          ElIcon: true,
          ElInput: true,
          ElTag: { template: '<span><slot /></span>' },
        },
      },
    })
    await flushPromises()
    const scanButton = () => wrapper.findAll('button').find((button) => button.text().includes('扫表号'))

    await scanButton()!.trigger('click')
    await flushPromises()
    await wrapper.find('.scanner-head button').trigger('click')
    await scanButton()!.trigger('click')
    await flushPromises()
    resolveOldControls?.(oldControls)
    await flushPromises()

    expect(oldControls.stop).toHaveBeenCalledTimes(1)
    expect(currentControls.stop).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('ZXing 正在识别条形码')
    wrapper.unmount()
  })
})
