import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ReviewTask } from '@/api/types'
import ClaimTasksView from '@/views/ClaimTasksView.vue'

const authMock = vi.hoisted(() => ({ role: 'admin' }))
const apiMock = vi.hoisted(() => ({
  assignConstructionTask: vi.fn(),
  fetchMaterialExportSummaries: vi.fn(),
  fetchTaskSnapshot: vi.fn(),
  fetchUserAccounts: vi.fn(),
  preflightMaterialExport: vi.fn(),
  reserveMaterialExport: vi.fn(),
  setConstructionTaskPriority: vi.fn(),
  updateMaterialExportSetting: vi.fn(),
}))

vi.mock('@/api/services', () => apiMock)
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { role: authMock.role, roles: [authMock.role] } }),
}))

function task(terminal: string, priority: boolean, uploaded: number, total = 100): ReviewTask {
  return {
    id: `task-${terminal}`,
    projectId: 'project-a',
    name: terminal,
    stage: '施工',
    status: 'pending',
    terminal,
    totalGroups: total,
    claimedGroups: 0,
    completedGroups: 0,
    renovationCount: total,
    constructionUploadedCount: uploaded,
    constructionUnbuiltCount: total - uploaded,
    constructionAvailable: true,
    constructionPriority: priority,
  }
}

const tasks = [task('B', false, 80), task('A', true, 20), task('C', true, 90)]

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

describe('ClaimTasksView material export integration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authMock.role = 'admin'
    apiMock.fetchTaskSnapshot.mockResolvedValue({ teamId: 'team-a', items: tasks, version: '1', generatedAt: '', cache: {} })
    apiMock.fetchUserAccounts.mockResolvedValue([])
    apiMock.fetchMaterialExportSummaries.mockResolvedValue(tasks.map((item) => ({
      taskId: item.id,
      projectId: item.projectId,
      terminalCode: item.terminal,
      requestedCollectorCount: 0,
      sourceCollectorCount: 1,
      finalCollectorCount: 1,
      activeAllocationCount: 0,
      lastJobStatus: '',
    })))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders the task cards and temporary export notice before summaries finish loading', async () => {
    const summaries = deferred<unknown[]>()
    apiMock.fetchMaterialExportSummaries.mockReturnValue(summaries.promise)

    const wrapper = mount(ClaimTasksView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.findAll('.claim-task-card')).toHaveLength(3)
    expect(wrapper.find('[data-testid="material-export-toolbar"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="material-export-disabled-notice"]').text()).toContain('暂时关闭')
    expect(apiMock.fetchMaterialExportSummaries).toHaveBeenCalledTimes(1)

    summaries.resolve([])
    await flushPromises()
    wrapper.unmount()
  })

  it('keeps collector quantity settings for administrators while export actions are closed', async () => {
    const admin = mount(ClaimTasksView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(admin.findAll('[data-testid="material-export-card"]')).toHaveLength(3)
    expect(admin.find('[data-testid="material-export-batch"]').exists()).toBe(false)
    expect(admin.findAll('[data-testid="material-export-card-action"]')).toHaveLength(0)
    expect(admin.findAll('[data-testid^="material-export-count-"]')).toHaveLength(3)
    expect(admin.findAll('.claim-task-card').map((card) => card.text().match(/终端\s+([ABC])/)?.[1])).toEqual(['C', 'A', 'B'])
    admin.unmount()

    authMock.role = 'constructor'
    const constructor = mount(ClaimTasksView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(constructor.find('[data-testid="material-export-toolbar"]').exists()).toBe(false)
    expect(constructor.find('[data-testid="material-export-card"]').exists()).toBe(false)
    expect(apiMock.fetchMaterialExportSummaries).toHaveBeenCalledTimes(1)
    constructor.unmount()
  })

  it('keeps the collector quantity setting disabled only for a completely unconstructed terminal', async () => {
    apiMock.fetchTaskSnapshot.mockResolvedValue({
      teamId: 'team-a',
      items: [task('ZERO', false, 0, 10), task('PART', false, 1, 10)],
      version: '1',
      generatedAt: '',
      cache: {},
    })

    const wrapper = mount(ClaimTasksView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    const cards = wrapper.findAll('.claim-task-card')
    const zero = cards.find((card) => card.text().includes('终端 ZERO'))!
    const partial = cards.find((card) => card.text().includes('终端 PART'))!
    expect(zero.get('[data-testid="material-export-count-ZERO"] input').attributes('disabled')).toBeDefined()
    expect(partial.get('[data-testid="material-export-count-PART"] input').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })
})
