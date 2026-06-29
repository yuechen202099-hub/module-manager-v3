export type StaticPageKey =
  | 'project-board'
  | 'claim-tasks'
  | 'task-hall'
  | 'global-search'
  | 'construction'
  | 'account-management'
  | 'sync-config'

export type StaticPageMigrationStatus = 'native_vue'

export type StaticPageRoute = {
  key: StaticPageKey
  title: string
  subtitle: string
  routePath: string
  roles: string[]
  migrationStatus: StaticPageMigrationStatus
}

export const staticPages: StaticPageRoute[] = [
  {
    key: 'project-board',
    title: '项目驾驶舱',
    subtitle: '',
    routePath: '/project-board',
    roles: ['admin', 'reviewer'],
    migrationStatus: 'native_vue',
  },
  {
    key: 'claim-tasks',
    title: '任务领取',
    subtitle: '',
    routePath: '/claim-tasks',
    roles: ['admin', 'reviewer'],
    migrationStatus: 'native_vue',
  },
  {
    key: 'task-hall',
    title: '审阅工作台',
    subtitle: '',
    routePath: '/task-hall',
    roles: ['admin', 'reviewer'],
    migrationStatus: 'native_vue',
  },
  {
    key: 'global-search',
    title: '数据中台',
    subtitle: '',
    routePath: '/global-search',
    roles: ['admin'],
    migrationStatus: 'native_vue',
  },
  {
    key: 'construction',
    title: '施工采集',
    subtitle: '',
    routePath: '/construction',
    roles: ['admin', 'constructor'],
    migrationStatus: 'native_vue',
  },
  {
    key: 'account-management',
    title: '账号管理',
    subtitle: '',
    routePath: '/account-management',
    roles: ['admin'],
    migrationStatus: 'native_vue',
  },
  {
    key: 'sync-config',
    title: '导入配置',
    subtitle: '',
    routePath: '/sync-config',
    roles: ['admin'],
    migrationStatus: 'native_vue',
  },
]

export function findStaticPage(key: string | undefined) {
  return staticPages.find((page) => page.key === key)
}
