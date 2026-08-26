import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AppLayout from '@/layouts/AppLayout.vue'
import router from '@/router'
import { findStaticPage } from '@/router/staticPages'

const authMock = vi.hoisted(() => ({
  isAuthenticated: true,
  user: { role: 'constructor', roles: ['constructor'], teamId: 'team-1' } as { role: string; roles: string[]; teamId: string } | null,
  displayName: '施工员甲',
  hydrateFromLegacySession: vi.fn(async () => undefined),
  logout: vi.fn(),
}))

vi.mock('@/stores/auth', () => ({ useAuthStore: () => authMock }))
vi.mock('@/stores/workspace', () => ({ useWorkspaceStore: () => ({ projects: [{ id: 'project-1', name: '测试项目' }], activeProject: null, loadProjects: vi.fn() }) }))
vi.mock('@/api/services', () => ({ fetchScanImportJob: vi.fn(), startScanImportJob: vi.fn() }))

async function visibleNavigationTitles() {
  const wrapper = mount(AppLayout, {
    global: {
      plugins: [router],
      stubs: { RouterView: true, ElButton: true, ElDialog: true, ElIcon: true, ElPagination: true, ElProgress: true, ElTag: true, ElTooltip: true },
    },
  })
  await flushPromises()
  const titles = wrapper.findAll('.top-nav__item').map((item) => item.text())
  wrapper.unmount()
  return titles
}

describe('collector inventory routing', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    authMock.isAuthenticated = true
    authMock.user = { role: 'constructor', roles: ['constructor'], teamId: 'team-1' }
    authMock.displayName = '施工员甲'
    authMock.hydrateFromLegacySession.mockImplementation(async () => undefined)
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

  it('converges retired review bookmarks through real navigation on the canonical workbench', async () => {
    authMock.user = { role: 'admin', roles: ['admin'], teamId: 'team-1' }

    await router.push('/collector-workbench')
    expect(router.currentRoute.value.fullPath).toBe('/review-workbench')

    await router.push('/collector-batches')
    expect(router.currentRoute.value.fullPath).toBe('/review-workbench')

    await router.push('/review/g-123')
    expect(router.currentRoute.value.fullPath).toBe('/review-workbench?group_id=g-123')
  })

  it('keeps constructors inside construction collection regardless of target route', async () => {
    for (const path of ['/', '/project-board', '/global-search', '/collector-inventory', '/review-workbench', '/projects', '/checklists', '/account-management', '/sync-config']) {
      await router.push(path)
      expect(router.currentRoute.value.path, path).toBe('/construction')
    }

    expect(await visibleNavigationTitles()).toEqual(['施工采集'])
  })

  it('hydrates an authenticated session into a constructor before enforcing the global route gate', async () => {
    authMock.user = null
    authMock.hydrateFromLegacySession.mockImplementation(async () => {
      authMock.user = { role: 'constructor', roles: ['constructor'], teamId: 'team-1' }
    })

    await router.push('/project-board')

    expect(router.currentRoute.value.path).toBe('/construction')
    expect(authMock.hydrateFromLegacySession).toHaveBeenCalledTimes(1)
  })

  it('keeps construction and every administrator page available to admins', async () => {
    authMock.user = { role: 'admin', roles: ['admin'], teamId: 'team-1' }
    authMock.displayName = '管理员甲'

    for (const path of ['/construction', '/project-board', '/claim-tasks', '/global-search', '/collector-inventory', '/review-workbench', '/projects', '/checklists', '/account-management', '/sync-config']) {
      await router.push(path)
      expect(router.currentRoute.value.path, path).toBe(path)
    }
  })

  it('keeps composite constructor-admin accounts on administrator routes and navigation', async () => {
    authMock.user = { role: 'constructor', roles: ['constructor', 'admin'], teamId: 'team-1' }
    authMock.displayName = '施工员兼管理员'

    await router.push('/project-board')

    expect(router.currentRoute.value.path).toBe('/project-board')
    expect(await visibleNavigationTitles()).toEqual([
      '项目驾驶舱',
      '任务派发',
      '数据中台',
      '施工采集',
      '采集器盘点',
      '审阅与翻拍工作台',
      '账号管理',
    ])
  })

  it('preserves the data-center review dialog link instead of redirecting it to the workbench', async () => {
    authMock.user = { role: 'admin', roles: ['admin'], teamId: 'team-1' }
    await router.push('/global-search?group_id=g-123&page=1&page_size=20&review=1')

    expect(router.currentRoute.value.fullPath).toBe('/global-search?group_id=g-123&page=1&page_size=20&review=1')
  })
})
