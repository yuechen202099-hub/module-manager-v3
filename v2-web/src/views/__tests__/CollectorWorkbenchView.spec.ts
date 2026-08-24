import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  CollectorTerminalWorkbench,
  CollectorTransferPhoto,
  CollectorTransferRun,
  CollectorWorkbenchSummary,
} from '@/api/types'
import AppLayout from '@/layouts/AppLayout.vue'
import router from '@/router'
import { findStaticPage } from '@/router/staticPages'
import CollectorWorkbenchView from '@/views/CollectorWorkbenchView.vue'

const serviceMocks = vi.hoisted(() => ({
  fetchCollectorTransferProjects: vi.fn(),
  fetchCollectorTransferRuns: vi.fn(),
  fetchCollectorWorkbench: vi.fn(),
  fetchCollectorTerminalWorkbench: vi.fn(),
  setCollectorWorkbenchItemCompleted: vi.fn(),
  fetchScanImportJob: vi.fn(),
  startScanImportJob: vi.fn(),
}))

const workspaceMock = vi.hoisted(() => ({
  projects: [{ id: 'project-1', name: '城南改造' }],
  activeProject: { id: 'project-1', name: '城南改造' },
  loadProjects: vi.fn(),
}))

const authMock = vi.hoisted(() => ({
  isAuthenticated: true,
  user: { role: 'constructor', roles: ['constructor'], teamId: 'team-1' },
  displayName: '施工员甲',
  hydrateFromLegacySession: vi.fn(),
  logout: vi.fn(),
}))

vi.mock('@/stores/workspace', () => ({ useWorkspaceStore: () => workspaceMock }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => authMock }))
vi.mock('@/api/services', () => serviceMocks)

const run: CollectorTransferRun = {
  id: 'run-1',
  project_id: 'project-1',
  name: '城南改造 · 第三批',
  status: 'allocated',
  terminal_count: 2,
  meter_count: 2,
  collector_requirement_count: 2,
  blocked_terminal_count: 0,
  direct_match_count: 1,
  pool_available_count: 1,
  assignment_count: 2,
  diagnostics: [],
  created_at: '2026-08-23T00:00:00Z',
}

const photo = (id: string, url: string): CollectorTransferPhoto => ({
  id,
  image_url: url,
  object_key: `collector-transfer/${id}.jpg`,
  storage_type: 'oss',
  storage_key: `collector-transfer/${id}.jpg`,
  storage_bucket: 'evidence',
  sha256: `${id}-sha256`,
  content_type: 'image/jpeg',
  canonical_image_url: url,
  module_asset_no: '',
  collector: '',
  creator: 'fixture',
  preview_url: url,
  thumbnail_url: url,
})

const summary: CollectorWorkbenchSummary = {
  run,
  terminals: [
    {
      id: 'terminal-1',
      terminal_code: 'T-07',
      installation_address: '城南公变',
      status: 'in_progress',
      meter_count: 2,
      collector_requirement_count: 2,
      completed_count: 1,
      total_count: 4,
      progress: 25,
      diagnostics: [],
    },
    {
      id: 'terminal-2',
      terminal_code: 'T-08',
      installation_address: '城北公变',
      status: 'ready',
      meter_count: 1,
      collector_requirement_count: 1,
      completed_count: 0,
      total_count: 2,
      progress: 0,
      diagnostics: [],
    },
  ],
}

const terminalDetail: CollectorTerminalWorkbench = {
  run_id: 'run-1',
  terminal: {
    id: 'terminal-1',
    terminal_code: 'T-07',
    installation_address: '城南公变',
    status: 'in_progress',
  },
  items: [
    {
      id: 'meter-1',
      kind: 'meter_install',
      status: 'pending',
      meter_no: '000217630119',
      meter_barcode: '000217630119',
      module_no: 'M202608190771',
      module_barcode: 'M202608190771',
      photos: [
        { slot: 'module_meter', label: '模块与电表合照', photo: photo('module-meter-1', '/photos/module-meter.jpg') },
        { slot: 'after_box', label: '改造完成照片', photo: photo('after-box-1', '/photos/after-box.jpg') },
      ],
    },
    {
      id: 'meter-2',
      kind: 'meter_install',
      status: 'completed',
      meter_no: '000217630120',
      meter_barcode: '000217630120',
      module_no: 'M202608190772',
      module_barcode: 'M202608190772',
      photos: [
        { slot: 'module_meter', label: '模块与电表合照', photo: photo('module-meter-2', '/photos/module-meter-2.jpg') },
        { slot: 'after_box', label: '改造完成照片', photo: photo('after-box-2', '/photos/after-box-2.jpg') },
      ],
    },
    {
      id: 'removal-1',
      kind: 'collector_removal',
      status: 'pending',
      collector_no: 'CG-2026-OLD-0041',
      collector_barcode: 'CG-POOL-0008',
      assignment_mode: 'random',
      photos: [
        { slot: 'collector', label: '采集器实物照片', photo: photo('collector-1', '/photos/collector.jpg') },
      ],
    },
  ],
}

const run2: CollectorTransferRun = {
  ...run,
  id: 'run-2',
  project_id: 'project-2',
  name: '城北改造 · 第一批',
  meter_count: 0,
  collector_requirement_count: 1,
  assignment_count: 1,
}

const summary2: CollectorWorkbenchSummary = {
  run: run2,
  terminals: [summary.terminals[1]],
}

const terminalDetail2: CollectorTerminalWorkbench = {
  run_id: 'run-2',
  terminal: {
    id: 'terminal-2',
    terminal_code: 'T-08',
    installation_address: '城北公变',
    status: 'ready',
  },
  items: [structuredClone(terminalDetail.items[2])],
}

async function mountWorkbench() {
  const wrapper = mount(CollectorWorkbenchView, { attachTo: document.body })
  await flushPromises()
  return wrapper
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

describe('collector workbench route and navigation', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    workspaceMock.loadProjects.mockResolvedValue(undefined)
    authMock.hydrateFromLegacySession.mockResolvedValue(undefined)
    await router.push('/collector-workbench')
    await router.isReady()
  })

  it('registers the authenticated desktop page for admin and constructor', () => {
    const page = findStaticPage('collector-workbench')
    expect(page).toMatchObject({
      routePath: '/collector-workbench',
      roles: ['admin', 'constructor'],
      migrationStatus: 'native_vue',
    })

    const route = router.getRoutes().find((item) => item.name === 'collector-workbench')
    expect(route?.path).toBe('/collector-workbench')
    expect(route?.meta.roles).toEqual(['admin', 'constructor'])
    expect(route?.components?.default).toBeTruthy()
  })

  it.each(['constructor', 'admin'])('renders the workbench entry in AppLayout navigation for %s', async (role) => {
    authMock.user = { role, roles: [role], teamId: 'team-1' }
    const wrapper = mount(AppLayout, {
      global: {
        plugins: [router],
        stubs: {
          RouterView: true,
          ElButton: true,
          ElDialog: true,
          ElIcon: true,
          ElPagination: true,
          ElProgress: true,
          ElTag: true,
          ElTooltip: true,
        },
      },
    })
    await flushPromises()

    const links = wrapper.findAll('.top-nav__item').map((item) => item.text())
    expect(links).toContain('翻拍工作台')
    wrapper.unmount()
  })
})

describe('CollectorWorkbenchView data and evidence anatomy', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    workspaceMock.projects = [
      { id: 'project-1', name: '城南改造' },
      { id: 'project-2', name: '城北改造' },
    ]
    workspaceMock.activeProject = workspaceMock.projects[0]
    workspaceMock.loadProjects.mockResolvedValue(undefined)
    serviceMocks.fetchCollectorTransferProjects.mockResolvedValue(structuredClone(workspaceMock.projects))
    serviceMocks.fetchCollectorTransferRuns.mockResolvedValue([run])
    serviceMocks.fetchCollectorWorkbench.mockImplementation(async () => structuredClone(summary))
    serviceMocks.fetchCollectorTerminalWorkbench.mockImplementation(async () => structuredClone(terminalDetail))
    serviceMocks.setCollectorWorkbenchItemCompleted.mockImplementation(async (itemId: string, completed: boolean) => ({
      id: itemId,
      status: completed ? 'completed' : 'pending',
      completed_at: completed ? '2026-08-23T01:00:00Z' : null,
    }))
  })

  it('recovers when the initial project bootstrap fails and retry succeeds', async () => {
    workspaceMock.projects = []
    let attempts = 0
    serviceMocks.fetchCollectorTransferProjects.mockImplementation(async () => {
      attempts += 1
      if (attempts === 1) throw new Error('项目列表暂时不可用')
      return [
        { id: 'project-1', name: '城南改造' },
        { id: 'project-2', name: '城北改造' },
      ]
    })

    const wrapper = await mountWorkbench()

    expect(wrapper.get('[role="alert"]').text()).toContain('项目列表暂时不可用')
    expect(serviceMocks.fetchCollectorTransferRuns).not.toHaveBeenCalled()

    await wrapper.get('[data-testid="retry-error"]').trigger('click')
    await flushPromises()

    expect(serviceMocks.fetchCollectorTransferProjects).toHaveBeenCalledTimes(2)
    expect(serviceMocks.fetchCollectorTransferRuns).toHaveBeenCalledWith('project-1')
    expect(serviceMocks.fetchCollectorWorkbench).toHaveBeenCalledWith('run-1')
    expect(serviceMocks.fetchCollectorTerminalWorkbench).toHaveBeenCalledWith('run-1', 'terminal-1')
    expect(wrapper.get<HTMLSelectElement>('[aria-label="当前项目"]').element.value).toBe('project-1')
    expect(wrapper.get('.barcode-card figcaption').text()).toBe('000217630119')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('uses the transfer project list instead of a stale global workspace project', async () => {
    workspaceMock.projects = [{ id: 'local-test', name: '模块更换项目' }]
    workspaceMock.activeProject = { id: 'local-test', name: '模块更换项目' }
    serviceMocks.fetchCollectorTransferProjects.mockResolvedValue([{ id: 'project-1', name: '城南改造' }])

    const wrapper = await mountWorkbench()

    expect(workspaceMock.loadProjects).not.toHaveBeenCalled()
    expect(serviceMocks.fetchCollectorTransferProjects).toHaveBeenCalledTimes(1)
    expect(serviceMocks.fetchCollectorTransferRuns).toHaveBeenCalledWith('project-1')
    expect(wrapper.get<HTMLSelectElement>('[aria-label="当前项目"]').element.value).toBe('project-1')
    wrapper.unmount()
  })

  it('loads the selected project run and lets the operator choose a terminal through the API', async () => {
    const wrapper = await mountWorkbench()

    expect(serviceMocks.fetchCollectorTransferRuns).toHaveBeenCalledWith('project-1')
    expect(serviceMocks.fetchCollectorWorkbench).toHaveBeenCalledWith('run-1')
    expect(serviceMocks.fetchCollectorTerminalWorkbench).toHaveBeenCalledWith('run-1', 'terminal-1')
    expect(wrapper.get('[aria-label="当前终端"]').text()).toContain('T-07')

    await wrapper.get('[aria-label="当前终端"]').setValue('terminal-2')
    await flushPromises()
    expect(serviceMocks.fetchCollectorTerminalWorkbench).toHaveBeenLastCalledWith('run-1', 'terminal-2')
    wrapper.unmount()
  })

  it('loads a newly selected run and its first terminal through the workbench APIs', async () => {
    const alternateRun = { ...run, id: 'run-alt', name: '城南改造 · 第四批' }
    const alternateSummary = { ...summary, run: alternateRun }
    serviceMocks.fetchCollectorTransferRuns.mockResolvedValue([structuredClone(run), alternateRun])
    serviceMocks.fetchCollectorWorkbench.mockImplementation(async (selectedRunId: string) => (
      structuredClone(selectedRunId === 'run-alt' ? alternateSummary : summary)
    ))
    const wrapper = await mountWorkbench()

    await wrapper.get('[aria-label="当前批次"]').setValue('run-alt')
    await flushPromises()

    expect(serviceMocks.fetchCollectorWorkbench).toHaveBeenLastCalledWith('run-alt')
    expect(serviceMocks.fetchCollectorTerminalWorkbench).toHaveBeenLastCalledWith('run-alt', 'terminal-1')
    expect(wrapper.get<HTMLSelectElement>('[aria-label="当前批次"]').element.value).toBe('run-alt')
    expect(wrapper.get('.barcode-card figcaption').text()).toBe('000217630119')
    wrapper.unmount()
  })

  it('renders exactly two real barcodes and the two required photos for a new-install item', async () => {
    const wrapper = await mountWorkbench()

    const barcodes = wrapper.findAll('.barcode-card .code128')
    expect(barcodes).toHaveLength(2)
    expect(barcodes.map((item) => item.get('figcaption').text())).toEqual([
      '000217630119',
      'M202608190771',
    ])
    expect(barcodes.every((item) => item.get('svg').attributes('role') === 'img')).toBe(true)

    const photos = wrapper.findAll('.photo-frame')
    expect(photos).toHaveLength(2)
    expect(photos.map((item) => item.attributes('data-slot'))).toEqual(['module_meter', 'after_box'])
    expect(photos.map((item) => item.get('img').attributes('src'))).toEqual([
      '/photos/module-meter.jpg',
      '/photos/after-box.jpg',
    ])
    wrapper.unmount()
  })

  it('uses the assigned final collector barcode and one bound physical photo for removal', async () => {
    const wrapper = await mountWorkbench()

    await wrapper.get('[data-testid="mode-removal"]').trigger('click')

    const barcodes = wrapper.findAll('.barcode-card .code128')
    expect(barcodes).toHaveLength(1)
    expect(barcodes[0].get('figcaption').text()).toBe('CG-POOL-0008')
    expect(wrapper.text()).not.toContain('CG-2026-OLD-0041')
    const photos = wrapper.findAll('.photo-frame')
    expect(photos).toHaveLength(1)
    expect(photos[0].attributes('data-slot')).toBe('collector')
    expect(photos[0].get('img').attributes('src')).toBe('/photos/collector.jpg')
    wrapper.unmount()
  })

  it.each([
    ['表号条形码', 'meter_barcode', '缺少表号条形码', 0],
    ['模块号条形码', 'module_barcode', '缺少模块号条形码', 0],
    ['模块与电表合照', 'module_meter', '缺少模块与电表合照', 1],
    ['改造完成照片', 'after_box', '缺少改造完成照片', 1],
  ] as const)('blocks completion when an install item is missing %s', async (_label, missingField, expectedReason, missingPhotoCount) => {
    const detail = structuredClone(terminalDetail)
    const item = detail.items[0]
    if (item.kind !== 'meter_install') throw new Error('fixture must be an install item')
    if (missingField === 'meter_barcode' || missingField === 'module_barcode') {
      item[missingField] = ''
    } else if (missingField === 'module_meter') {
      const slot = item.photos.find((candidate) => candidate.slot === missingField)
      if (slot) slot.photo = null
    } else {
      item.photos = item.photos.filter((candidate) => candidate.slot !== missingField)
    }
    serviceMocks.fetchCollectorTerminalWorkbench.mockResolvedValue(detail)
    const wrapper = await mountWorkbench()

    expect(wrapper.get('.record-chip').text()).toBe('资料不完整')
    expect(wrapper.get('[data-testid="blocking-reasons"]').text()).toContain(expectedReason)
    expect(wrapper.findAll('.photo-frame').map((frame) => frame.attributes('data-slot'))).toEqual([
      'module_meter',
      'after_box',
    ])
    expect(wrapper.findAll('.photo-missing')).toHaveLength(missingPhotoCount)
    expect(wrapper.get<HTMLButtonElement>('[data-testid="complete-and-next"]').element.disabled).toBe(true)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await flushPromises()
    expect(serviceMocks.setCollectorWorkbenchItemCompleted).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it.each([
    ['最终采集器号', 'collector_barcode', '缺少最终采集器号', 0],
    ['采集器实物照片', 'collector', '缺少采集器实物照片', 1],
  ] as const)('blocks completion when a removal item is missing %s', async (_label, missingField, expectedReason, missingPhotoCount) => {
    const detail = structuredClone(terminalDetail)
    const item = detail.items.find((candidate) => candidate.kind === 'collector_removal')
    if (!item || item.kind !== 'collector_removal') throw new Error('fixture must contain a removal item')
    if (missingField === 'collector_barcode') {
      item.collector_barcode = ''
    } else {
      item.photos = item.photos.filter((candidate) => candidate.slot !== 'collector')
    }
    detail.items = [item]
    serviceMocks.fetchCollectorTerminalWorkbench.mockResolvedValue(detail)
    const wrapper = await mountWorkbench()

    expect(wrapper.get('.record-chip').text()).toBe('资料不完整')
    expect(wrapper.get('[data-testid="blocking-reasons"]').text()).toContain(expectedReason)
    expect(wrapper.findAll('.photo-frame').map((frame) => frame.attributes('data-slot'))).toEqual(['collector'])
    expect(wrapper.findAll('.photo-missing')).toHaveLength(missingPhotoCount)
    expect(wrapper.get<HTMLButtonElement>('[data-testid="complete-and-next"]').element.disabled).toBe(true)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await flushPromises()
    expect(serviceMocks.setCollectorWorkbenchItemCompleted).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it.each([
    ['blocked status', 'blocked', [], '终端状态为资料有阻塞'],
    ['terminal diagnostics', 'in_progress', [{ group_id: 'group-7', code: 'missing_group', message: '终端未匹配到施工组' }], '终端未匹配到施工组'],
  ] as const)('blocks completion for %s even when item evidence is complete', async (_label, status, diagnostics, expectedReason) => {
    const blockedSummary = structuredClone(summary)
    blockedSummary.terminals[0].status = status
    blockedSummary.terminals[0].diagnostics = [...diagnostics]
    serviceMocks.fetchCollectorWorkbench.mockResolvedValue(blockedSummary)
    const wrapper = await mountWorkbench()

    expect(wrapper.get('.record-chip').text()).toBe('资料不完整')
    expect(wrapper.get('[data-testid="blocking-reasons"]').text()).toContain(expectedReason)
    expect(wrapper.findAll('.photo-frame').map((frame) => frame.attributes('data-slot'))).toEqual([
      'module_meter',
      'after_box',
    ])
    expect(wrapper.findAll('.photo-missing')).toHaveLength(0)
    expect(wrapper.get<HTMLButtonElement>('[data-testid="complete-and-next"]').element.disabled).toBe(true)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await flushPromises()
    expect(serviceMocks.setCollectorWorkbenchItemCompleted).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('shows completed status and current incomplete reasons when install evidence later becomes invalid', async () => {
    const detail = structuredClone(terminalDetail)
    const item = detail.items[1]
    if (item.kind !== 'meter_install') throw new Error('fixture must be a completed install item')
    item.meter_barcode = ''
    const moduleMeterSlot = item.photos.find((candidate) => candidate.slot === 'module_meter')
    if (moduleMeterSlot) moduleMeterSlot.photo = null
    detail.items = [item]
    serviceMocks.fetchCollectorTerminalWorkbench.mockResolvedValue(detail)
    const wrapper = await mountWorkbench()

    expect(wrapper.findAll('.record-chip').map((chip) => chip.text())).toEqual(['已完成', '资料不完整'])
    expect(wrapper.get('[data-testid="blocking-reasons"]').text()).toContain('缺少表号条形码')
    expect(wrapper.get('[data-testid="blocking-reasons"]').text()).toContain('缺少模块与电表合照')
    expect(wrapper.findAll('.photo-frame').map((frame) => frame.attributes('data-slot'))).toEqual([
      'module_meter',
      'after_box',
    ])
    expect(wrapper.findAll('.photo-missing')).toHaveLength(1)
    expect(wrapper.get<HTMLButtonElement>('[data-testid="undo-completion"]').element.disabled).toBe(false)
    expect(wrapper.find('[data-testid="complete-and-next"]').exists()).toBe(false)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await flushPromises()
    expect(serviceMocks.setCollectorWorkbenchItemCompleted).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('shows completed status and current incomplete reasons when removal evidence later becomes invalid', async () => {
    const detail = structuredClone(terminalDetail)
    const item = detail.items.find((candidate) => candidate.kind === 'collector_removal')
    if (!item || item.kind !== 'collector_removal') throw new Error('fixture must contain a removal item')
    item.status = 'completed'
    item.collector_barcode = ''
    item.photos = item.photos.filter((candidate) => candidate.slot !== 'collector')
    detail.items = [item]
    serviceMocks.fetchCollectorTerminalWorkbench.mockResolvedValue(detail)
    const wrapper = await mountWorkbench()

    expect(wrapper.findAll('.record-chip').map((chip) => chip.text())).toEqual(['已完成', '资料不完整'])
    expect(wrapper.get('[data-testid="blocking-reasons"]').text()).toContain('缺少最终采集器号')
    expect(wrapper.get('[data-testid="blocking-reasons"]').text()).toContain('缺少采集器实物照片')
    expect(wrapper.findAll('.photo-frame').map((frame) => frame.attributes('data-slot'))).toEqual(['collector'])
    expect(wrapper.findAll('.photo-missing')).toHaveLength(1)
    expect(wrapper.get<HTMLButtonElement>('[data-testid="undo-completion"]').element.disabled).toBe(false)
    expect(wrapper.find('[data-testid="complete-and-next"]').exists()).toBe(false)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await flushPromises()
    expect(serviceMocks.setCollectorWorkbenchItemCompleted).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('shows completed status and current blocker reasons when its terminal becomes blocked with diagnostics', async () => {
    const blockedSummary = structuredClone(summary)
    blockedSummary.terminals[0].status = 'blocked'
    blockedSummary.terminals[0].diagnostics = [
      { group_id: 'group-7', code: 'missing_group', message: '终端未匹配到施工组' },
    ]
    const detail = structuredClone(terminalDetail)
    const item = detail.items[1]
    if (item.kind !== 'meter_install') throw new Error('fixture must be a completed install item')
    detail.items = [item]
    serviceMocks.fetchCollectorWorkbench.mockResolvedValue(blockedSummary)
    serviceMocks.fetchCollectorTerminalWorkbench.mockResolvedValue(detail)
    const wrapper = await mountWorkbench()

    expect(wrapper.findAll('.record-chip').map((chip) => chip.text())).toEqual(['已完成', '资料不完整'])
    expect(wrapper.get('[data-testid="blocking-reasons"]').text()).toContain('终端状态为资料有阻塞')
    expect(wrapper.get('[data-testid="blocking-reasons"]').text()).toContain('终端未匹配到施工组')
    expect(wrapper.get<HTMLButtonElement>('[data-testid="undo-completion"]').element.disabled).toBe(false)
    expect(wrapper.find('[data-testid="complete-and-next"]').exists()).toBe(false)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await flushPromises()
    expect(serviceMocks.setCollectorWorkbenchItemCompleted).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('moves between work items with buttons and the left and right arrow keys', async () => {
    const wrapper = await mountWorkbench()

    expect(wrapper.get('.barcode-card figcaption').text()).toBe('000217630119')
    await wrapper.get('[aria-label="下一条"]').trigger('click')
    expect(wrapper.get('.barcode-card figcaption').text()).toBe('000217630120')
    await wrapper.get('[aria-label="上一条"]').trigger('click')
    expect(wrapper.get('.barcode-card figcaption').text()).toBe('000217630119')

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
    await flushPromises()
    expect(wrapper.get('.barcode-card figcaption').text()).toBe('000217630120')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
    await flushPromises()
    expect(wrapper.get('.barcode-card figcaption').text()).toBe('000217630119')
    wrapper.unmount()
  })

  it('waits for the completion API before Enter advances and round-trips undo for a completed item', async () => {
    const completion = deferred<{ id: string; status: 'completed'; completed_at: string }>()
    serviceMocks.setCollectorWorkbenchItemCompleted.mockReturnValueOnce(completion.promise)
    const wrapper = await mountWorkbench()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await flushPromises()
    expect(serviceMocks.setCollectorWorkbenchItemCompleted).toHaveBeenCalledWith('meter-1', true)
    expect(wrapper.get('.barcode-card figcaption').text()).toBe('000217630119')

    completion.resolve({ id: 'meter-1', status: 'completed', completed_at: '2026-08-23T01:00:00Z' })
    await flushPromises()
    expect(wrapper.get('.barcode-card figcaption').text()).toBe('000217630120')
    expect(wrapper.get('[data-testid="undo-completion"]').text()).toContain('撤销完成')

    await wrapper.get('[data-testid="undo-completion"]').trigger('click')
    await flushPromises()
    expect(serviceMocks.setCollectorWorkbenchItemCompleted).toHaveBeenLastCalledWith('meter-2', false)
    expect(wrapper.get('.record-chip').text()).toBe('资料完整')
    expect(wrapper.get('.barcode-card figcaption').text()).toBe('000217630120')
    wrapper.unmount()
  })

  it('keeps a late completion response from changing a newer terminal context', async () => {
    const completion = deferred<{ id: string; status: 'completed'; completed_at: string }>()
    serviceMocks.setCollectorWorkbenchItemCompleted.mockReturnValueOnce(completion.promise)
    const wrapper = await mountWorkbench()

    await wrapper.get('[data-testid="complete-and-next"]').trigger('click')
    await flushPromises()

    expect(wrapper.get<HTMLSelectElement>('[aria-label="当前项目"]').element.disabled).toBe(true)
    expect(wrapper.get<HTMLSelectElement>('[aria-label="当前批次"]').element.disabled).toBe(true)
    expect(wrapper.get<HTMLSelectElement>('[aria-label="当前终端"]').element.disabled).toBe(true)
    expect(wrapper.get<HTMLButtonElement>('[data-testid="mode-removal"]').element.disabled).toBe(true)
    expect(wrapper.get<HTMLButtonElement>('.work-item').element.disabled).toBe(true)

    const exposed = wrapper.vm as unknown as {
      activeItemId: string
      mode: 'install' | 'removal'
      terminalDetail: CollectorTerminalWorkbench | null
      terminalId: string
    }
    exposed.terminalId = 'terminal-2'
    exposed.terminalDetail = {
      ...structuredClone(terminalDetail2),
      run_id: 'run-1',
    }
    exposed.mode = 'removal'
    exposed.activeItemId = 'removal-1'
    await wrapper.vm.$nextTick()

    expect(wrapper.get('.barcode-card figcaption').text()).toBe('CG-POOL-0008')
    expect(wrapper.get('.progress').text()).toContain('0 / 2')

    completion.resolve({ id: 'meter-1', status: 'completed', completed_at: '2026-08-23T01:00:00Z' })
    await flushPromises()

    expect(wrapper.get('.barcode-card figcaption').text()).toBe('CG-POOL-0008')
    expect(wrapper.get('.record-chip').text()).toBe('资料完整')
    expect(wrapper.get('.progress').text()).toContain('0 / 2')
    expect(wrapper.find('[data-testid="undo-completion"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('keeps a late completion response from changing a newer item in the same terminal', async () => {
    const completion = deferred<{ id: string; status: 'completed'; completed_at: string }>()
    serviceMocks.setCollectorWorkbenchItemCompleted.mockReturnValueOnce(completion.promise)
    const wrapper = await mountWorkbench()

    await wrapper.get('[data-testid="complete-and-next"]').trigger('click')
    await flushPromises()

    const exposed = wrapper.vm as unknown as { activeItemId: string }
    exposed.activeItemId = 'meter-2'
    await wrapper.vm.$nextTick()
    expect(wrapper.get('.barcode-card figcaption').text()).toBe('000217630120')
    expect(wrapper.get('.progress').text()).toContain('1 / 4')

    completion.resolve({ id: 'meter-1', status: 'completed', completed_at: '2026-08-23T01:00:00Z' })
    await flushPromises()

    expect(wrapper.get('.barcode-card figcaption').text()).toBe('000217630120')
    expect(wrapper.get('.progress').text()).toContain('1 / 4')
    wrapper.unmount()
  })

  it('retries a failed completion against its original item after the operator changes terminals', async () => {
    serviceMocks.fetchCollectorTerminalWorkbench.mockImplementation(async (_runId: string, selectedTerminalId: string) => (
      structuredClone(selectedTerminalId === 'terminal-2'
        ? { ...terminalDetail2, run_id: 'run-1' }
        : terminalDetail)
    ))
    serviceMocks.setCollectorWorkbenchItemCompleted
      .mockRejectedValueOnce(new Error('完成服务暂时不可用'))
      .mockResolvedValueOnce({ id: 'meter-1', status: 'completed', completed_at: '2026-08-23T01:00:00Z' })
    const wrapper = await mountWorkbench()

    await wrapper.get('[data-testid="complete-and-next"]').trigger('click')
    await flushPromises()
    await wrapper.get('[aria-label="当前终端"]').setValue('terminal-2')
    await flushPromises()

    expect(wrapper.get('.barcode-card figcaption').text()).toBe('CG-POOL-0008')
    expect(wrapper.get('.progress').text()).toContain('0 / 2')

    await wrapper.get('[data-testid="retry-error"]').trigger('click')
    await flushPromises()

    expect(serviceMocks.setCollectorWorkbenchItemCompleted).toHaveBeenNthCalledWith(1, 'meter-1', true)
    expect(serviceMocks.setCollectorWorkbenchItemCompleted).toHaveBeenNthCalledWith(2, 'meter-1', true)
    expect(wrapper.get('.barcode-card figcaption').text()).toBe('CG-POOL-0008')
    expect(wrapper.get('.record-chip').text()).toBe('资料完整')
    expect(wrapper.get('.progress').text()).toContain('0 / 2')
    wrapper.unmount()
  })

  it('keeps the current item and offers a working retry when the completion API fails', async () => {
    serviceMocks.setCollectorWorkbenchItemCompleted
      .mockRejectedValueOnce(new Error('完成服务暂时不可用'))
      .mockResolvedValueOnce({ id: 'meter-1', status: 'completed', completed_at: '2026-08-23T01:00:00Z' })
    const wrapper = await mountWorkbench()

    await wrapper.get('[data-testid="complete-and-next"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('.barcode-card figcaption').text()).toBe('000217630119')
    expect(wrapper.get('.record-chip').text()).toBe('资料完整')
    expect(wrapper.get('[role="alert"]').text()).toContain('完成服务暂时不可用')

    await wrapper.get('[data-testid="retry-error"]').trigger('click')
    await flushPromises()
    expect(serviceMocks.setCollectorWorkbenchItemCompleted).toHaveBeenCalledTimes(2)
    expect(wrapper.get('.barcode-card figcaption').text()).toBe('000217630120')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('preserves the current project and evidence when project loading fails, then retries the intended project', async () => {
    let project2Attempts = 0
    serviceMocks.fetchCollectorTransferRuns.mockImplementation(async (selectedProjectId: string) => {
      if (selectedProjectId !== 'project-2') return [structuredClone(run)]
      project2Attempts += 1
      if (project2Attempts === 1) throw new Error('批次列表暂时不可用')
      return [structuredClone(run2)]
    })
    serviceMocks.fetchCollectorWorkbench.mockImplementation(async (selectedRunId: string) => (
      structuredClone(selectedRunId === 'run-2' ? summary2 : summary)
    ))
    serviceMocks.fetchCollectorTerminalWorkbench.mockImplementation(async (selectedRunId: string) => (
      structuredClone(selectedRunId === 'run-2' ? terminalDetail2 : terminalDetail)
    ))
    const wrapper = await mountWorkbench()

    await wrapper.get('[aria-label="当前项目"]').setValue('project-2')
    await flushPromises()

    expect(wrapper.get<HTMLSelectElement>('[aria-label="当前项目"]').element.value).toBe('project-1')
    expect(wrapper.get('.barcode-card figcaption').text()).toBe('000217630119')
    expect(wrapper.get('[role="alert"]').text()).toContain('批次列表暂时不可用')

    await wrapper.get('[data-testid="retry-error"]').trigger('click')
    await flushPromises()
    expect(serviceMocks.fetchCollectorTransferRuns).toHaveBeenLastCalledWith('project-2')
    expect(wrapper.get<HTMLSelectElement>('[aria-label="当前项目"]').element.value).toBe('project-2')
    expect(wrapper.get<HTMLSelectElement>('[aria-label="当前批次"]').element.value).toBe('run-2')
    expect(wrapper.get('.barcode-card figcaption').text()).toBe('CG-POOL-0008')
    wrapper.unmount()
  })

  it('ignores a stale project response after a newer project selection has completed', async () => {
    const delayedProject2Runs = deferred<CollectorTransferRun[]>()
    serviceMocks.fetchCollectorTransferRuns.mockImplementation(async (selectedProjectId: string) => (
      selectedProjectId === 'project-2' ? delayedProject2Runs.promise : [structuredClone(run)]
    ))
    serviceMocks.fetchCollectorWorkbench.mockImplementation(async (selectedRunId: string) => (
      structuredClone(selectedRunId === 'run-2' ? summary2 : summary)
    ))
    serviceMocks.fetchCollectorTerminalWorkbench.mockImplementation(async (selectedRunId: string) => (
      structuredClone(selectedRunId === 'run-2' ? terminalDetail2 : terminalDetail)
    ))
    const wrapper = await mountWorkbench()

    const projectSelect = wrapper.get('[aria-label="当前项目"]')
    await projectSelect.setValue('project-2')
    await projectSelect.setValue('project-1')
    await flushPromises()
    expect(wrapper.get<HTMLSelectElement>('[aria-label="当前项目"]').element.value).toBe('project-1')

    delayedProject2Runs.resolve([structuredClone(run2)])
    await flushPromises()
    expect(wrapper.get<HTMLSelectElement>('[aria-label="当前项目"]').element.value).toBe('project-1')
    expect(wrapper.get<HTMLSelectElement>('[aria-label="当前批次"]').element.value).toBe('run-1')
    expect(wrapper.get('.barcode-card figcaption').text()).toBe('000217630119')
    wrapper.unmount()
  })

  it('keeps the accepted three-region desktop and narrow-desktop layout contract', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440, writable: true })
    const wrapper = await mountWorkbench()

    const regions = wrapper.findAll('.transfer-grid > [data-region]').map((region) => region.attributes('data-region'))
    expect(regions).toEqual(['queue', 'canvas', 'controls'])
    expect(getComputedStyle(wrapper.get('.transfer-grid').element).gridTemplateColumns).toBe('250px minmax(0, 1fr) 270px')
    expect(getComputedStyle(wrapper.get('.photo-frame img').element).objectFit).toBe('contain')

    window.innerWidth = 1000
    window.dispatchEvent(new Event('resize'))
    await flushPromises()
    expect(getComputedStyle(wrapper.get('.transfer-grid').element).gridTemplateColumns).toBe('230px minmax(0, 1fr)')
    expect(getComputedStyle(wrapper.get('[data-region="controls"]').element).gridColumn).toBe('1 / -1')

    window.innerWidth = 820
    window.dispatchEvent(new Event('resize'))
    await flushPromises()
    expect(getComputedStyle(wrapper.get('.transfer-grid').element).gridTemplateColumns).toBe('minmax(190px, 230px) minmax(0, 1fr)')
    wrapper.unmount()
  })

  it('states the manual-only boundary without credential fields or client-platform actions', async () => {
    const wrapper = await mountWorkbench()

    expect(wrapper.text()).toContain('本页仅辅助掌机人工翻拍与人工录入，不会登录或自动上传甲方平台。')
    expect(wrapper.find('input[type="password"]').exists()).toBe(false)
    expect(wrapper.find('a[href*="platform"], a[href*="login"], a[target="_blank"]').exists()).toBe(false)
    const actionText = wrapper.findAll('button').map((button) => button.text()).join(' ')
    expect(actionText).not.toMatch(/甲方账号|甲方密码|平台登录|自动上传|跳转甲方/)
    wrapper.unmount()
  })
})
