import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { GlobalCollectorTerminalCandidate, GlobalCollectorTerminalDetail, GlobalCollectorTerminalPage, ReviewWorkbenchOpenResult } from '@/api/types'
import ReviewRephotoWorkbenchView from '@/views/ReviewRephotoWorkbenchView.vue'

const serviceMocks = vi.hoisted(() => ({
  fetchGlobalCollectorTerminals: vi.fn(), openReviewWorkbenchTerminal: vi.fn(),
  replaceGlobalTerminalMissing: vi.fn(), rollbackCollectorAssignment: vi.fn(),
  refreshGlobalCollectorTerminal: vi.fn(), setCollectorWorkbenchItemCompleted: vi.fn(),
}))
const authMock = vi.hoisted(() => ({ user: { role: 'admin', roles: ['admin'] } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => authMock }))
vi.mock('@/api/services', () => serviceMocks)
vi.mock('@/components/data-center/DataCenterGroupReviewPanel.vue', () => ({
  default: {
    name: 'DataCenterGroupReviewPanel',
    props: ['groupId', 'rephotoItem', 'defaultStage', 'classificationOnly'], emits: ['updated', 'review-decided'],
    template: '<section class="review-panel-stub"><span>照片分类</span><button data-testid="save-classification" @click="$emit(\'updated\', {})">保存分类</button></section>',
  },
}))

const photo = { id: 'photo-1', image_url: '/api/photos/1', preview_url: '/api/photos/1' }
const candidate = (overrides: Partial<GlobalCollectorTerminalCandidate> = {}): GlobalCollectorTerminalCandidate => ({
  terminal_key: 'opaque-key', project_id: 'project-1', project_name: '城南项目', terminal_code: 'T-001', installation_address: '安装地址',
  needs_disambiguation: false, meter_count: 2, collector_count: 2, physical_count: 1, missing_count: 1, pool_available_count: 2,
  workflow_state: 'needs_review', selectable: true, source_revision: 'revision-1', constructed_meter_count: 2, unconstructed_meter_count: 1, review_ready_count: 1, review_required_count: 1, diagnostics: [], ...overrides,
})
const rephoto = (state: 'present' | 'missing' | 'replaced' = 'missing'): GlobalCollectorTerminalDetail => ({
  run_id: 'run-1', project_id: 'project-1', terminal: { id: 'terminal-1', terminal_code: 'T-001', installation_address: '安装地址', status: 'ready', diagnostics: [] },
  meter_install_items: [
    { meter_item_id: 'meter-a', workbench_item_id: 'meter-workbench-a', status: 'pending', meter_no: 'M-A', meter_barcode: 'M-A', module_no: 'MOD-A', module_barcode: 'MOD-A', photos: [{ slot: 'module_meter', label: '电表和模块', photo }, { slot: 'after_box', label: '改造完成', photo }], diagnostics: [] },
    { meter_item_id: 'meter-b', workbench_item_id: 'meter-workbench-b', status: 'pending', meter_no: 'M-B', meter_barcode: 'M-B', module_no: 'MOD-B', module_barcode: 'MOD-B', photos: [{ slot: 'module_meter', label: '电表和模块', photo }, { slot: 'after_box', label: '改造完成', photo }], diagnostics: [] },
  ],
  collector_items: [
    { requirement_id: 'collector-a', workbench_item_id: 'collector-workbench-a', status: 'pending', original_collector_no: 'C-01', physical_state: 'present', final_collector_no: 'C-01', collector_barcode: 'C-01', capture_strategy: 'live_physical', assignment_id: null, photo: null, diagnostics: [] },
    { requirement_id: 'collector-b', workbench_item_id: 'collector-workbench-b', status: 'pending', original_collector_no: 'C-01', physical_state: state, final_collector_no: state === 'replaced' ? 'POOL-01' : state === 'present' ? 'C-01' : null, collector_barcode: state === 'replaced' ? 'POOL-01' : state === 'present' ? 'C-01' : null, capture_strategy: state === 'replaced' ? 'screen_photo' : state === 'present' ? 'live_physical' : 'unavailable', assignment_id: state === 'replaced' ? 'assignment-1' : null, photo: state === 'replaced' ? photo : null, diagnostics: [] },
  ],
  pool_summary: { required: state === 'missing' ? 1 : 0, available: 2, shortage: 0 }, completed_count: 0, total_count: 4, progress: 0, source_revision: 'revision-1', current_source_revision: 'revision-1', source_changed: false,
})
const open = (overrides: Partial<ReviewWorkbenchOpenResult> = {}): ReviewWorkbenchOpenResult => ({
  terminal: { terminal_key: 'opaque-key', project_id: 'project-1', terminal_code: 'T-001', installation_address: '安装地址' }, workflow_state: 'needs_review', source_revision: 'revision-1',
  constructed_meter_count: 2, unconstructed_meter_count: 1, review_ready_count: 1, review_required_count: 1,
  review_blockers: [{ group_id: 'group-a', codes: ['资料不全'] }],
  meters: [
    { group_id: 'group-a', meter_no: 'M-A', module_no: 'MOD-A', collector_no: 'C-01', construction_state: 'constructed', review_status: '待审阅', review_ready: false, blockers: ['资料不全'], classification_manually_confirmed: false, classification_confirmation_anomalies: [], classification_manual_confirmation: null },
    { group_id: 'group-b', meter_no: 'M-B', module_no: 'MOD-B', collector_no: 'C-01', construction_state: 'constructed', review_status: '已通过', review_ready: true, blockers: [], classification_manually_confirmed: true, classification_confirmation_anomalies: [], classification_manual_confirmation: {} },
    { group_id: 'group-c', meter_no: 'M-C', module_no: 'MOD-C', collector_no: 'C-02', construction_state: 'unconstructed', review_status: '未施工', review_ready: false, blockers: [], classification_manually_confirmed: false, classification_confirmation_anomalies: [], classification_manual_confirmation: null },
  ], rephoto: null, ...overrides,
})
const page = (items: GlobalCollectorTerminalCandidate[]): GlobalCollectorTerminalPage => ({ items, page: 1, page_size: 50, total: items.length })
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done }); return { promise, resolve } }
async function mountWorkbench() { const wrapper = mount(ReviewRephotoWorkbenchView, { attachTo: document.body }); await flushPromises(); return wrapper }

describe('review rephoto workbench', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    serviceMocks.fetchGlobalCollectorTerminals.mockResolvedValue(page([candidate()]))
    serviceMocks.openReviewWorkbenchTerminal.mockResolvedValue(open())
    serviceMocks.replaceGlobalTerminalMissing.mockResolvedValue({ required: 1, assigned: 1, assignments: [] })
    serviceMocks.rollbackCollectorAssignment.mockResolvedValue({})
    serviceMocks.refreshGlobalCollectorTerminal.mockResolvedValue({})
    serviceMocks.setCollectorWorkbenchItemCompleted.mockResolvedValue({})
  })

  it('keeps pending review visible without locking complete rephoto material', async () => {
    serviceMocks.openReviewWorkbenchTerminal.mockResolvedValue(open({ rephoto: rephoto('replaced') }))
    const wrapper = await mountWorkbench()
    expect(wrapper.text()).toContain('T-001')
    expect(wrapper.text()).toContain('未施工，不参与本次翻拍')
    expect(wrapper.find('.workbench-grid').exists()).toBe(false)
    expect(wrapper.find('.meter-queue').exists()).toBe(false)
    expect(wrapper.find('.review-actions').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('正式通过')
    expect(wrapper.text()).not.toContain('资料不全')
    expect(wrapper.text()).not.toContain('退回异常')
    expect(wrapper.getComponent({ name: 'DataCenterGroupReviewPanel' }).props('classificationOnly')).toBe(true)
    expect(wrapper.get('.terminal-notice').text()).toContain('分类不影响翻拍')
    expect(wrapper.get<HTMLButtonElement>('.complete-meter').element.disabled).toBe(false)
    expect(wrapper.findAll('.rephoto-slot')).toHaveLength(2)
    expect(wrapper.findAll('.rephoto-slot img')).toHaveLength(2)
    wrapper.unmount()
  })

  it('opens every rephoto image in a large read-only preview', async () => {
    serviceMocks.openReviewWorkbenchTerminal.mockResolvedValue(open({ rephoto: rephoto('replaced') }))
    const wrapper = await mountWorkbench()

    await wrapper.get('[data-testid="preview-meter-module_meter"]').trigger('click')
    expect(wrapper.get('[data-testid="photo-lightbox"]').attributes('aria-modal')).toBe('true')
    expect(wrapper.get<HTMLImageElement>('[data-testid="photo-lightbox-image"]').attributes('src')).toBe('/api/photos/1')
    await wrapper.get('[data-testid="close-photo-lightbox"]').trigger('click')
    expect(wrapper.find('[data-testid="photo-lightbox"]').exists()).toBe(false)

    await wrapper.get('[data-testid="preview-collector-collector-b"]').trigger('click')
    expect(wrapper.get('[data-testid="photo-lightbox-image"]').attributes('alt')).toContain('采集器 C-01')
    wrapper.unmount()
  })

  it('distinguishes manual classification acceptance from remaining material anomalies', async () => {
    serviceMocks.openReviewWorkbenchTerminal.mockResolvedValue(open({
      workflow_state: 'blocked',
      review_ready_count: 1,
      review_required_count: 1,
      meters: [
        { group_id: 'group-a', meter_no: 'M-A', module_no: 'MOD-A', collector_no: 'C-01', construction_state: 'constructed', review_status: 'approved', review_ready: false, blockers: ['after_box_photo_missing'], classification_manually_confirmed: true, classification_confirmation_anomalies: ['after_box_photo_missing'], classification_manual_confirmation: {} },
        { group_id: 'group-b', meter_no: 'M-B', module_no: 'MOD-B', collector_no: 'C-01', construction_state: 'constructed', review_status: 'approved', review_ready: true, blockers: [], classification_manually_confirmed: true, classification_confirmation_anomalies: [], classification_manual_confirmation: {} },
      ],
    }))

    const wrapper = await mountWorkbench()

    expect(wrapper.get('[data-testid="meter-record-group-a"]').text()).toContain('分类已确认，资料异常')
    expect(wrapper.get('.terminal-notice').text()).toContain('已确认分类的表计仍可能存在资料异常')
    wrapper.unmount()
  })

  it('reopens after photo classification and then shows two slots per constructed meter with deduplicated collectors', async () => {
    serviceMocks.openReviewWorkbenchTerminal.mockResolvedValueOnce(open()).mockResolvedValueOnce(open({ workflow_state: 'needs_replacement', review_ready_count: 2, review_required_count: 0, review_blockers: [], rephoto: rephoto() }))
    const wrapper = await mountWorkbench()
    await wrapper.get('[data-testid="save-classification"]').trigger('click'); await flushPromises()
    expect(serviceMocks.openReviewWorkbenchTerminal).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('.rephoto-slot')).toHaveLength(2)
    await wrapper.get('[data-testid="meter-record-group-b"]').trigger('click')
    expect(wrapper.findAll('.rephoto-slot')).toHaveLength(2)
    expect(wrapper.get('.meter-record.is-expanded .meter-number').text()).toContain('M-B')
    expect(wrapper.findAll('.collector-card')).toHaveLength(1)
    wrapper.unmount()
  })

  it('sends only opaque terminal identity and revision to unified open', async () => {
    const wrapper = await mountWorkbench()
    expect(serviceMocks.openReviewWorkbenchTerminal).toHaveBeenCalledWith({ terminal_key: 'opaque-key', source_revision: 'revision-1' })
    expect(JSON.stringify(serviceMocks.openReviewWorkbenchTerminal.mock.calls)).not.toMatch(/project-1|T-001/)
    wrapper.unmount()
  })

  it('opens one blocked terminal so its photos remain available for classification', async () => {
    serviceMocks.fetchGlobalCollectorTerminals.mockResolvedValue(page([
      candidate({ workflow_state: 'blocked', selectable: false }),
    ]))
    serviceMocks.openReviewWorkbenchTerminal.mockResolvedValue(open({ workflow_state: 'blocked' }))

    const wrapper = await mountWorkbench()
    await wrapper.get('[aria-label="输入终端号"]').setValue('T-001')
    await wrapper.get('[data-testid="search-terminal"]').trigger('click')
    await flushPromises()

    expect(serviceMocks.openReviewWorkbenchTerminal).toHaveBeenCalledWith({
      terminal_key: 'opaque-key',
      source_revision: 'revision-1',
    })
    expect(wrapper.get('.terminal-summary').text()).toContain('T-001')
    expect(wrapper.text()).not.toContain('未找到唯一可授权终端')
    expect(wrapper.getComponent({ name: 'DataCenterGroupReviewPanel' }).props('classificationOnly')).toBe(true)
    wrapper.unmount()
  })

  it('does not let a late search response replace a newer opened terminal', async () => {
    const late = deferred<GlobalCollectorTerminalPage>()
    serviceMocks.fetchGlobalCollectorTerminals.mockReturnValueOnce(late.promise).mockResolvedValueOnce(page([candidate({ terminal_key: 'new-key', terminal_code: 'T-002' })]))
    serviceMocks.openReviewWorkbenchTerminal.mockResolvedValue(open({ terminal: { terminal_key: 'new-key', project_id: 'project-1', terminal_code: 'T-002', installation_address: '新地址' } }))
    const wrapper = mount(ReviewRephotoWorkbenchView, { attachTo: document.body }); await flushPromises()
    await wrapper.get('[aria-label="输入终端号"]').setValue('T-002'); await wrapper.get('[data-testid="search-terminal"]').trigger('click'); await flushPromises()
    late.resolve(page([candidate()])); await flushPromises()
    expect(wrapper.text()).toContain('T-002'); expect(wrapper.text()).not.toContain('T-001')
    wrapper.unmount()
  })

  it('keeps the zero-result safety state when an earlier terminal open resolves late', async () => {
    const lateOpen = deferred<ReviewWorkbenchOpenResult>()
    serviceMocks.openReviewWorkbenchTerminal.mockReturnValueOnce(lateOpen.promise)
    serviceMocks.fetchGlobalCollectorTerminals.mockResolvedValueOnce(page([candidate()])).mockResolvedValueOnce(page([]))
    const wrapper = mount(ReviewRephotoWorkbenchView, { attachTo: document.body }); await flushPromises()

    await wrapper.get('[aria-label="输入终端号"]').setValue('不存在的终端')
    await wrapper.get('[data-testid="search-terminal"]').trigger('click'); await flushPromises()
    lateOpen.resolve(open())
    await flushPromises()

    expect(wrapper.text()).toContain('未找到终端，请检查终端号。')
    expect(wrapper.text()).not.toContain('终端 T-001')
    wrapper.unmount()
  })

  it('loads the next bounded terminal candidate page instead of hard-coding page one', async () => {
    serviceMocks.fetchGlobalCollectorTerminals.mockResolvedValueOnce({ ...page([candidate()]), total: 51 }).mockResolvedValueOnce({ ...page([candidate({ terminal_key: 'page-two', terminal_code: 'T-002' })]), page: 2, total: 51 })
    const wrapper = await mountWorkbench()

    await wrapper.get('[data-testid="next-candidate-page"]').trigger('click'); await flushPromises()

    expect(serviceMocks.fetchGlobalCollectorTerminals).toHaveBeenLastCalledWith({ query: '', page: 2, pageSize: 50, includeBlocked: true })
    expect(serviceMocks.openReviewWorkbenchTerminal).toHaveBeenLastCalledWith({ terminal_key: 'page-two', source_revision: 'revision-1' })
    wrapper.unmount()
  })

  it('does not auto-open one visible row when the paginated search has multiple matches', async () => {
    const wrapper = await mountWorkbench()
    serviceMocks.openReviewWorkbenchTerminal.mockClear()
    serviceMocks.fetchGlobalCollectorTerminals.mockResolvedValueOnce({
      ...page([candidate({ terminal_key: 'page-two', terminal_code: 'T-002' })]),
      page: 2,
      total: 51,
    })

    await wrapper.get('[aria-label="输入终端号"]').setValue('T')
    await wrapper.get('[data-testid="search-terminal"]').trigger('click')
    await flushPromises()

    expect(serviceMocks.openReviewWorkbenchTerminal).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('匹配到多个终端，请输入完整终端号。')
    wrapper.unmount()
  })

  it('opens the unique group deep-link candidate and selects the requested constructed meter', async () => {
    window.history.replaceState({}, '', '/review-workbench?group_id=group-b')
    try {
      const wrapper = await mountWorkbench()
      expect(serviceMocks.fetchGlobalCollectorTerminals).toHaveBeenCalledWith(expect.objectContaining({ query: 'group-b' }))
      expect(wrapper.get('.meter-record.is-expanded .meter-number').text()).toContain('M-B')
      wrapper.unmount()
    } finally {
      window.history.replaceState({}, '', '/')
    }
  })

  it('selects a deep-linked unconstructed group without creating rephoto slots', async () => {
    window.history.replaceState({}, '', '/review-workbench?group_id=group-c')
    try {
      const wrapper = await mountWorkbench()
      expect(wrapper.get('.meter-record.unconstructed-record.is-expanded .meter-number').text()).toContain('M-C')
      expect(wrapper.findAll('.rephoto-slot')).toHaveLength(0)
      wrapper.unmount()
    } finally {
      window.history.replaceState({}, '', '/')
    }
  })

  it('completes the workbench item belonging to the visible deduplicated collector card', async () => {
    const withTwoCollectors = rephoto('present')
    withTwoCollectors.collector_items[1] = { ...withTwoCollectors.collector_items[1], original_collector_no: 'C-02', final_collector_no: 'C-02', collector_barcode: 'C-02' }
    serviceMocks.openReviewWorkbenchTerminal.mockResolvedValue(open({ workflow_state: 'ready', review_ready_count: 2, review_required_count: 0, review_blockers: [], rephoto: withTwoCollectors }))
    const wrapper = await mountWorkbench()

    await wrapper.get('[data-testid="complete-collector-collector-b"]').trigger('click'); await flushPromises()

    expect(serviceMocks.setCollectorWorkbenchItemCompleted).toHaveBeenCalledWith('collector-workbench-b', true)
    wrapper.unmount()
  })

  it('does not complete during shortage', async () => {
    serviceMocks.openReviewWorkbenchTerminal.mockResolvedValue(open({ workflow_state: 'pool_shortage', review_ready_count: 2, review_required_count: 0, review_blockers: [], rephoto: rephoto('missing') }))
    const wrapper = await mountWorkbench()
    expect(wrapper.get<HTMLButtonElement>('[data-testid="complete-collector-collector-b"]').element.disabled).toBe(true)
    await wrapper.get('[data-testid="replace-all-missing"]').trigger('click'); await flushPromises()
    expect(serviceMocks.replaceGlobalTerminalMissing).not.toHaveBeenCalled()
    expect(serviceMocks.setCollectorWorkbenchItemCompleted).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('replacement followed by rollback returns to missing', async () => {
    serviceMocks.openReviewWorkbenchTerminal.mockResolvedValueOnce(open({ workflow_state: 'needs_replacement', review_ready_count: 2, review_required_count: 0, review_blockers: [], rephoto: rephoto('missing') })).mockResolvedValue(open({ workflow_state: 'needs_replacement', review_ready_count: 2, review_required_count: 0, review_blockers: [], rephoto: rephoto('replaced') }))
    const wrapper = await mountWorkbench()
    await wrapper.get('[data-testid="replace-all-missing"]').trigger('click'); await flushPromises()
    serviceMocks.openReviewWorkbenchTerminal.mockResolvedValue(open({ workflow_state: 'needs_replacement', review_ready_count: 2, review_required_count: 0, review_blockers: [], rephoto: rephoto('missing') }))
    await wrapper.get('[data-testid="rollback-assignment"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('无实物')
    wrapper.unmount()
  })

  it('disables every mutation after a changed source and never requests a camera or non-local URL', async () => {
    vi.stubGlobal('fetch', vi.fn())
    const getUserMedia = vi.fn()
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } })
    serviceMocks.openReviewWorkbenchTerminal.mockResolvedValue(open({ workflow_state: 'ready', rephoto: { ...rephoto('present'), source_changed: true } }))
    const wrapper = await mountWorkbench()
    expect(wrapper.findAll('.rephoto-mutation').every((button) => (button.element as HTMLButtonElement).disabled)).toBe(true)
    expect(getUserMedia).not.toHaveBeenCalled()
    expect(wrapper.findAll('img').every((image) => String(image.attributes('src')).startsWith('/'))).toBe(true)
    vi.unstubAllGlobals(); wrapper.unmount()
  })
})
