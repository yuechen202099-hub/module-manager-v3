import { createRouter, createWebHistory } from 'vue-router'

import AppLayout from '@/layouts/AppLayout.vue'
import { staticPages } from '@/router/staticPages'
import { useAuthStore } from '@/stores/auth'

const nativePageComponents = {
  'project-board': () => import('@/views/ProjectBoardView.vue'),
  'claim-tasks': () => import('@/views/ClaimTasksView.vue'),
  'global-search': () => import('@/views/GlobalSearchView.vue'),
  construction: () => import('@/views/ConstructionView.vue'),
  'collector-inventory': () => import('@/views/CollectorInventoryView.vue'),
  'review-workbench': () => import('@/views/ReviewRephotoWorkbenchView.vue'),
  'account-management': () => import('@/views/AccountManagementView.vue'),
  'sync-config': () => import('@/views/SyncConfigView.vue'),
} as const

function defaultRouteForRole(role = '') {
  if (role === 'constructor') return { name: 'construction' }
  return { name: 'project-board' }
}

const router = createRouter({
  history: createWebHistory('/'),
  routes: [
    {
      path: '/',
      redirect: '/project-board',
    },
    {
      path: '/app',
      redirect: (to) => {
        const page = String(to.query.page || 'project-board')
        if (page === 'construction-cache') return { path: '/construction', query: {} }
        if (page === 'unmatched') {
          return {
            path: '/global-search',
            query: {
              data_type: 'unmatched',
              page: '1',
              page_size: '20',
            },
          }
        }
        return `/${page}`
      },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true, title: '登录' },
    },
    {
      path: '/',
      component: AppLayout,
      children: [
        ...staticPages.map((page) => ({
          path: page.routePath.replace(/^\//, ''),
          name: page.key,
          component: nativePageComponents[page.key],
          meta: {
            title: page.title,
            staticPageKey: page.key,
            roles: page.roles,
            migrationStatus: page.migrationStatus,
          },
        })),
        {
          path: 'dashboard',
          redirect: '/project-board',
        },
        {
          path: 'collector-batches',
          redirect: '/review-workbench',
        },
        {
          path: 'collector-workbench',
          redirect: '/review-workbench',
        },
        {
          path: 'projects',
          name: 'projects',
          component: () => import('@/views/ProjectsView.vue'),
          meta: { title: '项目管理' },
        },
        {
          path: 'checklists',
          name: 'checklists',
          component: () => import('@/views/ChecklistView.vue'),
          meta: { title: '清单管理' },
        },
        {
          path: 'tasks',
          redirect: '/claim-tasks',
        },
        {
          path: 'task-hall',
          redirect: '/global-search',
        },
        {
          path: 'review/:groupId',
          redirect: (to) => ({
            path: '/review-workbench',
            query: { group_id: String(to.params.groupId || '') },
          }),
        },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  if (to.name === 'login' && auth.isAuthenticated) {
    return defaultRouteForRole(auth.user?.role)
  }

  if (!to.meta.public && !auth.user) {
    try {
      await auth.hydrateFromLegacySession()
    } catch {
      auth.logout()
      return { name: 'login', query: { redirect: to.fullPath } }
    }
  }

  const role = auth.user?.role || ''
  const roles = new Set<string>([role, ...(auth.user?.roles || [])].filter(Boolean).map(String))
  if (roles.has('constructor') && !roles.has('admin') && to.path !== '/construction' && to.path !== '/login') {
    return { name: 'construction' }
  }

  const allowedRoles = (to.meta.roles as string[] | undefined) || []
  if (allowedRoles.length) {
    const isAllowed = allowedRoles.some((item) => roles.has(item)) || roles.has('admin')
    if (!isAllowed) {
      return defaultRouteForRole(role)
    }
  }

  return true
})

export default router
