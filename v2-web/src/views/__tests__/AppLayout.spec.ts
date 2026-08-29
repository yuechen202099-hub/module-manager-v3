import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AppLayout from '@/layouts/AppLayout.vue'

const authMock = vi.hoisted(() => ({
  user: { role: 'reviewer', roles: ['reviewer'] },
  displayName: 'legacy-account',
  hydrateFromLegacySession: vi.fn(),
  logout: vi.fn(),
}))
const workspaceMock = vi.hoisted(() => ({
  activeProject: null,
  projects: [],
  loadProjects: vi.fn(),
}))

vi.mock('@/stores/auth', () => ({ useAuthStore: () => authMock }))
vi.mock('@/stores/workspace', () => ({ useWorkspaceStore: () => workspaceMock }))
vi.mock('@/api/services', () => ({ fetchScanImportJob: vi.fn(), startScanImportJob: vi.fn() }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ meta: { title: '项目看板' }, path: '/project-board', query: {} }),
  useRouter: () => ({ push: vi.fn() }),
}))

const slotStub = { template: '<div><slot /></div>' }

describe('application layout', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authMock.hydrateFromLegacySession.mockResolvedValue(undefined)
  })

  it('does not present a removed reviewer role from a stale session', async () => {
    const wrapper = mount(AppLayout, {
      global: {
        stubs: {
          ElButton: slotStub,
          ElDialog: true,
          ElIcon: slotStub,
          ElPagination: true,
          ElProgress: true,
          ElTag: slotStub,
          ElTooltip: slotStub,
          RouterView: true,
        },
      },
    })
    await flushPromises()

    expect(wrapper.get('.user-chip').text()).toBe('用户 / legacy-account')
    expect(wrapper.text()).not.toContain('审阅员')

    wrapper.unmount()
  })
})
