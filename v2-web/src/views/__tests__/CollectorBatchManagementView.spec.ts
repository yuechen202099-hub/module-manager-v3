import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import CollectorBatchManagementView from '@/views/CollectorBatchManagementView.vue'

const serviceMocks = vi.hoisted(() => ({
  allocateCollectorPool: vi.fn(),
  fetchCollectorTransferProjects: vi.fn(),
  fetchCollectorTransferRuns: vi.fn(),
}))

const authMock = vi.hoisted(() => ({
  user: { role: 'admin', roles: ['admin'] } as { role: string; roles: string[] } | null,
}))

vi.mock('@/api/services', () => serviceMocks)
vi.mock('@/stores/auth', () => ({ useAuthStore: () => authMock }))
vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
}))

const run = {
  id: 'run-1',
  project_id: 'project-1',
  name: '城南改造 · 第三批',
  status: 'inventory',
  terminal_count: 1,
  meter_count: 1,
  collector_requirement_count: 1,
  blocked_terminal_count: 0,
  direct_match_count: 0,
  pool_available_count: 1,
  assignment_count: 0,
  diagnostics: [],
  created_at: '2026-08-24T00:00:00Z',
}

describe('CollectorBatchManagementView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authMock.user = { role: 'admin', roles: ['admin'] }
    serviceMocks.fetchCollectorTransferProjects.mockResolvedValue([{ id: 'project-1', name: '城南改造' }])
    serviceMocks.fetchCollectorTransferRuns.mockResolvedValue([run])
    serviceMocks.allocateCollectorPool.mockResolvedValue({ run_id: 'run-1', assignment_count: 1, assignments: [] })
  })

  it('lets only the separate administrator batch page allocate a selected run', async () => {
    const wrapper = mount(CollectorBatchManagementView)
    await flushPromises()

    expect(wrapper.text()).toContain('替换池批次管理')
    expect(wrapper.text()).not.toContain('打开摄像头扫码')
    expect(wrapper.get('[data-testid="allocate-pool"]').text()).toContain('执行随机分配')

    await wrapper.get('[data-testid="allocate-pool"]').trigger('click')
    await flushPromises()

    expect(serviceMocks.allocateCollectorPool).toHaveBeenCalledWith('run-1')
    expect(serviceMocks.fetchCollectorTransferRuns).toHaveBeenLastCalledWith('project-1')
    wrapper.unmount()
  })
})
