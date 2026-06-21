import { createRouter, createWebHistory } from 'vue-router'

import AppLayout from '@/layouts/AppLayout.vue'
import { staticPages } from '@/router/staticPages'
import { useAuthStore } from '@/stores/auth'

const nativePageComponents = {
  'project-board': () => import('@/views/ProjectBoardView.vue'),
  'claim-tasks': () => import('@/views/ClaimTasksView.vue'),
  'task-hall': () => import('@/views/TaskHallView.vue'),
  construction: () => import('@/views/ConstructionView.vue'),
  'sync-config': () => import('@/views/SyncConfigView.vue'),
} as const

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

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  if (to.name === 'login' && auth.isAuthenticated) {
    return { name: 'project-board' }
  }

  return true
})

export default router
