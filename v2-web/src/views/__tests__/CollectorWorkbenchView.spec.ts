import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { GlobalCollectorTerminalCandidate, GlobalCollectorTerminalDetail, GlobalCollectorTerminalPage } from '@/api/types'
import AppLayout from '@/layouts/AppLayout.vue'
import router from '@/router'
import { findStaticPage } from '@/router/staticPages'
import CollectorWorkbenchView from '@/views/CollectorWorkbenchView.vue'

const serviceMocks = vi.hoisted(() => ({
  fetchGlobalCollectorTerminals: vi.fn(), openGlobalCollectorTerminal: vi.fn(), fetchGlobalCollectorTerminal: vi.fn(),
  replaceGlobalTerminalMissing: vi.fn(), refreshGlobalCollectorTerminal: vi.fn(), rollbackCollectorAssignment: vi.fn(),
  setCollectorWorkbenchItemCompleted: vi.fn(),
}))
const authMock = vi.hoisted(() => ({
  isAuthenticated: true, user: { role: 'admin', roles: ['admin'], teamId: 'team-1' }, displayName: '管理员甲',
  hydrateFromLegacySession: vi.fn(async () => undefined), logout: vi.fn(),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => authMock }))
vi.mock('@/stores/workspace', () => ({ useWorkspaceStore: () => ({ projects: [], loadProjects: vi.fn() }) }))
vi.mock('@/api/services', () => serviceMocks)

const photo = { id: 'photo-1', image_url: '/pool.jpg', preview_url: '/pool.jpg' }
const candidate = (overrides: Partial<GlobalCollectorTerminalCandidate> = {}): GlobalCollectorTerminalCandidate => ({
  terminal_key: 'opaque-key', project_id: 'project-1', project_name: '城南项目', terminal_code: 'T-001', installation_address: '安装地址',
  needs_disambiguation: false, meter_count: 1, collector_count: 1, physical_count: 1, missing_count: 0, pool_available_count: 2,
  workflow_state: 'ready', selectable: true, source_revision: 'revision-1', diagnostics: [], ...overrides,
})
const detail = (physicalState: 'present' | 'missing' | 'replaced' = 'present'): GlobalCollectorTerminalDetail => ({
  run_id: 'run-1', project_id: 'project-1', terminal: { id: 'terminal-1', terminal_code: 'T-001', installation_address: '安装地址', status: 'ready', diagnostics: [] },
  meter_install_items: [{ meter_item_id: 'meter-1', workbench_item_id: 'meter-workbench-1', status: 'pending', meter_no: 'METER-01', meter_barcode: 'METER-01', module_no: 'MODULE-01', module_barcode: 'MODULE-01', photos: [{ slot: 'module_meter', label: '电表和模块', photo }, { slot: 'after_box', label: '改造完成', photo }], diagnostics: [] }],
  collector_items: [{ requirement_id: 'requirement-1', workbench_item_id: 'collector-workbench-1', status: 'pending', original_collector_no: 'OLD-01', physical_state: physicalState, final_collector_no: physicalState === 'missing' ? null : physicalState === 'replaced' ? 'POOL-01' : 'OLD-01', collector_barcode: physicalState === 'missing' ? null : physicalState === 'replaced' ? 'POOL-01' : 'OLD-01', capture_strategy: physicalState === 'missing' ? 'unavailable' : physicalState === 'replaced' ? 'screen_photo' : 'live_physical', assignment_id: physicalState === 'replaced' ? 'assignment-1' : null, photo: physicalState === 'replaced' ? photo : null, diagnostics: [] }],
  pool_summary: { required: physicalState === 'missing' ? 1 : 0, available: 2, shortage: 0 }, completed_count: 0, total_count: 2, progress: 0, source_revision: 'revision-1', current_source_revision: 'revision-1', source_changed: false,
})
const page = (items: GlobalCollectorTerminalCandidate[]): GlobalCollectorTerminalPage => ({ items, page: 1, page_size: 50, total: items.length })
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done }); return { promise, resolve } }
async function mountWorkbench() { const wrapper = mount(CollectorWorkbenchView, { attachTo: document.body }); await flushPromises(); return wrapper }

describe('global collector workbench', () => {
  beforeEach(async () => {
    vi.clearAllMocks(); authMock.user = { role: 'admin', roles: ['admin'], teamId: 'team-1' }
    serviceMocks.fetchGlobalCollectorTerminals.mockResolvedValue(page([candidate()]))
    serviceMocks.openGlobalCollectorTerminal.mockResolvedValue({ workbench_terminal_id: 'terminal-1', snapshot_reused: false, source_changed: false })
    serviceMocks.fetchGlobalCollectorTerminal.mockResolvedValue(detail())
    serviceMocks.setCollectorWorkbenchItemCompleted.mockResolvedValue({ id: 'collector-workbench-1', status: 'completed', completed_at: '2026-08-25T00:00:00Z' })
    await router.push('/collector-workbench'); await router.isReady()
  })

  it('uses one global terminal control and has no project, batch, or creation flow', async () => {
    const wrapper = await mountWorkbench()
    expect(wrapper.findAll('[aria-label="选择可翻拍终端"]').length).toBe(1)
    expect(wrapper.findAll('[aria-label="当前项目"], [aria-label="当前批次"], [data-testid="create-batch"]').length).toBe(0)
    expect(serviceMocks.openGlobalCollectorTerminal).toHaveBeenCalledWith(expect.objectContaining({ terminal_key: 'opaque-key', project_id: 'project-1', terminal_code: 'T-001', source_revision: 'revision-1' }))
    expect(JSON.stringify(serviceMocks.openGlobalCollectorTerminal.mock.calls)).not.toMatch(/team|actor|role/)
    wrapper.unmount()
  })

  it('renders present, missing, and replaced collector contracts without a camera', async () => {
    const wrapper = await mountWorkbench()
    expect(wrapper.text()).toContain('有实物'); expect(wrapper.text()).toContain('无需网站照片，请直接拿实物翻拍'); expect(wrapper.find('[data-testid="complete-and-next"]').exists()).toBe(true)
    serviceMocks.fetchGlobalCollectorTerminal.mockResolvedValueOnce(detail('missing'))
    await wrapper.get('[aria-label="选择可翻拍终端"]').setValue('opaque-key'); await flushPromises()
    expect(wrapper.text()).toContain('无实物'); expect(wrapper.text()).not.toContain('POOL-01'); expect(wrapper.find('[data-testid="complete-and-next"]').exists()).toBe(false)
    serviceMocks.fetchGlobalCollectorTerminal.mockResolvedValueOnce(detail('replaced'))
    await wrapper.get('[aria-label="选择可翻拍终端"]').setValue('opaque-key'); await flushPromises()
    expect(wrapper.text()).toContain('已替换'); expect(wrapper.text()).toContain('POOL-01'); expect(wrapper.get('img').attributes('src')).toBe('/pool.jpg'); expect(wrapper.html()).not.toContain('getUserMedia')
    wrapper.unmount()
  })

  it('renders exactly the two new-install source photos and blocks incomplete meter completion', async () => {
    const wrapper = await mountWorkbench()
    expect(wrapper.findAll('.meter-photos figure').map((item) => item.attributes('data-slot'))).toEqual(['module_meter', 'after_box'])
    expect(wrapper.findAll('.meter-list .code128 figcaption').map((item) => item.text())).toEqual(['METER-01', 'MODULE-01'])
    expect(wrapper.get<HTMLButtonElement>('[data-testid="complete-meter-meter-1"]').element.disabled).toBe(false)
    serviceMocks.fetchGlobalCollectorTerminal.mockResolvedValue({ ...detail(), meter_install_items: [{ ...detail().meter_install_items[0], photos: [detail().meter_install_items[0].photos[0]] }] })
    await wrapper.get('[aria-label="选择可翻拍终端"]').setValue('opaque-key'); await flushPromises()
    expect(wrapper.get<HTMLButtonElement>('[data-testid="complete-meter-meter-1"]').element.disabled).toBe(true)
    wrapper.unmount()
  })

  it('replaces missing collectors once and reloads persisted detail', async () => {
    serviceMocks.fetchGlobalCollectorTerminal.mockResolvedValue(detail('missing')); serviceMocks.replaceGlobalTerminalMissing.mockResolvedValue({ required: 1, assigned: 1, assignments: [] })
    const wrapper = await mountWorkbench(); serviceMocks.fetchGlobalCollectorTerminal.mockResolvedValue(detail('replaced'))
    await wrapper.get('[data-testid="replace-all-missing"]').trigger('click'); await flushPromises()
    expect(serviceMocks.replaceGlobalTerminalMissing).toHaveBeenCalledWith('terminal-1'); expect(serviceMocks.fetchGlobalCollectorTerminal).toHaveBeenCalledTimes(2); expect(wrapper.text()).toContain('已替换')
    wrapper.unmount()
  })

  it('hides replacement, refresh, and rollback from constructors and reports pool shortage', async () => {
    authMock.user = { role: 'constructor', roles: ['constructor'], teamId: 'team-1' }
    serviceMocks.fetchGlobalCollectorTerminals.mockResolvedValue(page([candidate({ workflow_state: 'pool_shortage', missing_count: 2, pool_available_count: 1 })]))
    serviceMocks.fetchGlobalCollectorTerminal.mockResolvedValue({ ...detail('missing'), pool_summary: { required: 2, available: 1, shortage: 1 } })
    const wrapper = await mountWorkbench()
    expect(wrapper.text()).toContain('需要 2 / 可用 1'); expect(wrapper.findAll('[data-testid="replace-all-missing"], [data-testid="refresh-terminal"], [data-testid="rollback-assignment"]').length).toBe(0)
    wrapper.unmount()
  })

  it('exposes only a refreshable changed, unprogressed snapshot and retries failures', async () => {
    serviceMocks.fetchGlobalCollectorTerminal.mockResolvedValue({ ...detail(), source_changed: true, current_source_revision: 'revision-2' })
    serviceMocks.refreshGlobalCollectorTerminal.mockRejectedValueOnce(new Error('刷新失败')).mockResolvedValue({ workbench_terminal_id: 'terminal-1' })
    const wrapper = await mountWorkbench(); expect(wrapper.text()).toContain('来源资料已变化')
    await wrapper.get('[data-testid="refresh-terminal"]').trigger('click'); await flushPromises(); expect(wrapper.get('[role="alert"]').text()).toContain('刷新失败')
    await wrapper.get('[data-testid="retry-error"]').trigger('click'); await flushPromises(); expect(serviceMocks.refreshGlobalCollectorTerminal).toHaveBeenCalledTimes(2)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' })); await flushPromises(); expect(wrapper.text()).toContain('拆除 1')
    wrapper.unmount()
  })

  it('confirms rollback but keeps refresh disabled for an active random assignment', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true)); serviceMocks.fetchGlobalCollectorTerminal.mockResolvedValue({ ...detail('replaced'), source_changed: true, current_source_revision: 'revision-2' }); serviceMocks.rollbackCollectorAssignment.mockResolvedValue({})
    const wrapper = await mountWorkbench(); expect(wrapper.get<HTMLButtonElement>('[data-testid="refresh-terminal"]').element.disabled).toBe(true)
    await wrapper.get('[data-testid="rollback-assignment"]').trigger('click'); await flushPromises(); expect(serviceMocks.rollbackCollectorAssignment).toHaveBeenCalledWith('assignment-1')
    vi.unstubAllGlobals(); wrapper.unmount()
  })

  it('keeps late candidate and detail responses from replacing newer terminal state', async () => {
    const lateDetail = deferred<GlobalCollectorTerminalDetail>()
    serviceMocks.fetchGlobalCollectorTerminals.mockResolvedValue(page([candidate({ terminal_key: 'new-key', terminal_code: 'T-002' })]))
    serviceMocks.openGlobalCollectorTerminal.mockResolvedValue({ workbench_terminal_id: 'terminal-2', snapshot_reused: true, source_changed: false })
    serviceMocks.fetchGlobalCollectorTerminal.mockReturnValueOnce(lateDetail.promise).mockResolvedValueOnce({ ...detail(), terminal: { ...detail().terminal, id: 'terminal-2', terminal_code: 'T-002' } })
    const wrapper = mount(CollectorWorkbenchView, { attachTo: document.body }); await flushPromises(); await wrapper.get('[aria-label="选择可翻拍终端"]').setValue('new-key'); await flushPromises()
    lateDetail.resolve(detail()); await flushPromises(); expect(wrapper.text()).toContain('T-002'); expect(wrapper.text()).not.toContain('T-001 · 安装地址'); wrapper.unmount()
  })

  it('keeps failed terminal mutations and their persisted reload bound to the original terminal after selection changes', async () => {
    const candidateB = candidate({ terminal_key: 'terminal-b', terminal_code: 'T-002' })
    const detailB = { ...detail(), terminal: { ...detail().terminal, id: 'terminal-2', terminal_code: 'T-002' } }
    serviceMocks.fetchGlobalCollectorTerminals.mockResolvedValue(page([candidate(), candidateB]))
    serviceMocks.openGlobalCollectorTerminal.mockImplementation(async (value: GlobalCollectorTerminalCandidate) => ({ workbench_terminal_id: value.terminal_key === 'terminal-b' ? 'terminal-2' : 'terminal-1', snapshot_reused: false, source_changed: false }))
    serviceMocks.fetchGlobalCollectorTerminal.mockImplementation(async (id: string) => id === 'terminal-2' ? detailB : detail('missing'))
    serviceMocks.replaceGlobalTerminalMissing.mockRejectedValueOnce(new Error('A 替换失败')).mockResolvedValue({ required: 1, assigned: 1, assignments: [] })
    const wrapper = await mountWorkbench()
    await wrapper.get('[data-testid="replace-all-missing"]').trigger('click'); await flushPromises()
    await wrapper.get('[aria-label="选择可翻拍终端"]').setValue('terminal-b'); await flushPromises()
    await wrapper.get('[data-testid="retry-error"]').trigger('click'); await flushPromises()
    expect(serviceMocks.replaceGlobalTerminalMissing).toHaveBeenNthCalledWith(1, 'terminal-1')
    expect(serviceMocks.replaceGlobalTerminalMissing).toHaveBeenNthCalledWith(2, 'terminal-1')
    expect(serviceMocks.fetchGlobalCollectorTerminal).toHaveBeenLastCalledWith('terminal-1')
    expect(wrapper.text()).toContain('T-002')
    wrapper.unmount()
  })

  it('cancels a debounced candidate query when a listed terminal is selected', async () => {
    vi.useFakeTimers()
    const candidateB = candidate({ terminal_key: 'terminal-b', terminal_code: 'T-002' })
    const staleCandidates = deferred<GlobalCollectorTerminalPage>()
    serviceMocks.fetchGlobalCollectorTerminals.mockResolvedValueOnce(page([candidate(), candidateB])).mockReturnValueOnce(staleCandidates.promise)
    serviceMocks.openGlobalCollectorTerminal.mockImplementation(async (value: GlobalCollectorTerminalCandidate) => ({ workbench_terminal_id: value.terminal_key === 'terminal-b' ? 'terminal-2' : 'terminal-1', snapshot_reused: false, source_changed: false }))
    serviceMocks.fetchGlobalCollectorTerminal.mockResolvedValue({ ...detail(), terminal: { ...detail().terminal, id: 'terminal-2', terminal_code: 'T-002' } })
    const wrapper = mount(CollectorWorkbenchView, { attachTo: document.body }); await flushPromises()
    await wrapper.get('[aria-label="选择可翻拍终端"]').setValue('旧查询')
    await wrapper.get('[aria-label="选择可翻拍终端"]').setValue('terminal-b'); await flushPromises()
    await vi.advanceTimersByTimeAsync(250); staleCandidates.resolve(page([candidate()])); await flushPromises()
    expect(wrapper.text()).toContain('T-002')
    expect(wrapper.html()).toContain('terminal-b')
    vi.useRealTimers(); wrapper.unmount()
  })
})

describe('collector batch retirement', () => {
  it('removes batch navigation and redirects legacy batch bookmarks', async () => {
    expect(findStaticPage('collector-batches')).toBeUndefined()
    const wrapper = mount(AppLayout, { global: { plugins: [router], stubs: { RouterView: true, ElButton: true, ElDialog: true, ElIcon: true, ElPagination: true, ElProgress: true, ElTag: true, ElTooltip: true } } }); expect(wrapper.findAll('.top-nav__item').map((item) => item.text())).not.toContain('替换池批次')
    await router.push('/collector-batches'); await router.isReady(); expect(router.currentRoute.value.path).toBe('/collector-workbench'); wrapper.unmount()
  })
})
