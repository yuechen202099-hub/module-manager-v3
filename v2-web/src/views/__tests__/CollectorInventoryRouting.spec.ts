import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AppLayout from '@/layouts/AppLayout.vue'
import router from '@/router'
import { findStaticPage } from '@/router/staticPages'

const authMock = vi.hoisted(() => ({
  isAuthenticated: true,
  user: { role: 'constructor', roles: ['constructor'], teamId: 'team-1' } as { role: string; roles: string[]; teamId: string },
  displayName: '施工员甲',
  hydrateFromLegacySession: vi.fn(async () => undefined),
  logout: vi.fn(),
}))

vi.mock('@/stores/auth', () => ({ useAuthStore: () => authMock }))
vi.mock('@/stores/workspace', () => ({ useWorkspaceStore: () => ({ projects: [{ id: 'project-1', name: '测试项目' }], activeProject: null, loadProjects: vi.fn() }) }))
vi.mock('@/api/services', () => ({ fetchScanImportJob: vi.fn(), startScanImportJob: vi.fn() }))

function routeRedirect(path: string) {
  return router.getRoutes().find((route) => route.path === path)?.redirect
}

describe('collector inventory routing', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    authMock.isAuthenticated = true
    authMock.user = { role: 'constructor', roles: ['constructor'], teamId: 'team-1' }
    authMock.displayName = '施工员甲'
    await router.push('/construction')
    await router.isReady()
  })

  it('registers the native mobile page for admin and constructor only', () => {
    const page = findStaticPage('collector-inventory')
    expect(page).toMatchObject({
      routePath: '/collector-inventory',
      roles: ['admin', 'constructor'],
      migrationStatus: 'native_vue',
    })

    const route = router.getRoutes().find((item) => item.name === 'collector-inventory')
    expect(route?.path).toBe('/collector-inventory')
    expect(route?.meta.roles).toEqual(['admin', 'constructor'])
    expect(route?.components?.default).toBeTypeOf('function')
  })

  it('converges retired review bookmarks on the canonical review workbench', () => {
    expect(routeRedirect('/collector-workbench')).toBe('/review-workbench')
    expect(routeRedirect('/collector-batches')).toBe('/review-workbench')

    const reviewRedirect = routeRedirect('/review/:groupId')
    expect(reviewRedirect).toBeTypeOf('function')
    expect((reviewRedirect as (to: { params: { groupId: string } }) => unknown)({ params: { groupId: 'g-123' } })).toEqual({
      path: '/review-workbench',
      query: { group_id: 'g-123' },
    })
  })

  it('keeps constructors inside construction collection regardless of target route', async () => {
    for (const path of ['/', '/project-board', '/global-search', '/collector-inventory', '/review-workbench', '/projects', '/checklists', '/account-management', '/sync-config']) {
      await router.push(path)
      expect(router.currentRoute.value.path, path).toBe('/construction')
    }

    const wrapper = mount(AppLayout, {
      global: {
        plugins: [router],
        stubs: { RouterView: true, ElButton: true, ElDialog: true, ElIcon: true, ElPagination: true, ElProgress: true, ElTag: true, ElTooltip: true },
      },
    })
    await flushPromises()
    expect(wrapper.findAll('.top-nav__item').map((item) => item.text())).toEqual(['施工采集'])
    wrapper.unmount()
  })

  it('keeps construction and every administrator page available to admins', async () => {
    authMock.user = { role: 'admin', roles: ['admin'], teamId: 'team-1' }
    authMock.displayName = '管理员甲'

    for (const path of ['/construction', '/project-board', '/claim-tasks', '/global-search', '/collector-inventory', '/review-workbench', '/projects', '/checklists', '/account-management', '/sync-config']) {
      await router.push(path)
      expect(router.currentRoute.value.path, path).toBe(path)
    }
  })

  it('preserves the data-center review dialog link instead of redirecting it to the workbench', async () => {
    authMock.user = { role: 'admin', roles: ['admin'], teamId: 'team-1' }
    await router.push('/global-search?group_id=g-123&page=1&page_size=20&review=1')

    expect(router.currentRoute.value.fullPath).toBe('/global-search?group_id=g-123&page=1&page_size=20&review=1')
  })
})
