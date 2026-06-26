import { createRouter, createWebHistory } from 'vue-router'

import AppLayout from '@/layouts/AppLayout.vue'
import { staticPages } from '@/router/staticPages'
import { useAuthStore } from '@/stores/auth'

const nativePageComponents = {
  'project-board': () => import('@/views/ProjectBoardView.vue'),
  'claim-tasks': () => import('@/views/ClaimTasksView.vue'),
  'task-hall': () => import('@/views/TaskHallView.vue'),
  'global-search': () => import('@/views/GlobalSearchView.vue'),
  construction: () => import('@/views/ConstructionView.vue'),
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
        if (page === 'unmatched') return { path: '/task-hall', query: {} }
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
          path: 'review/:groupId',
          name: 'review',
          component: () => import('@/views/ReviewView.vue'),
          meta: { title: '资料审阅' },
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

  const allowedRoles = (to.meta.roles as string[] | undefined) || []
  if (allowedRoles.length) {
    if (!auth.user) {
      try {
        await auth.hydrateFromLegacySession()
      } catch {
        auth.logout()
        return { name: 'login', query: { redirect: to.fullPath } }
      }
    }
    const role = auth.user?.role || ''
    const roles = new Set<string>([role, ...(auth.user?.roles || [])].filter(Boolean).map(String))
    const isAllowed = allowedRoles.some((item) => roles.has(item)) || roles.has('admin')
    if (!isAllowed) {
      return defaultRouteForRole(role)
    }
  }

  return true
})

export default router
