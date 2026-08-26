export type StaticPageKey =
  | 'project-board'
  | 'claim-tasks'
  | 'global-search'
  | 'construction'
  | 'collector-inventory'
  | 'review-workbench'
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
    roles: ['admin'],
    migrationStatus: 'native_vue',
  },
  {
    key: 'claim-tasks',
    title: '任务派发',
    subtitle: '',
    routePath: '/claim-tasks',
    roles: ['admin'],
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
    key: 'collector-inventory',
    title: '采集器盘点',
    subtitle: '手机扫码与补拍',
    routePath: '/collector-inventory',
    roles: ['admin', 'constructor'],
    migrationStatus: 'native_vue',
  },
  {
    key: 'review-workbench',
    title: '审阅与翻拍',
    subtitle: '甲方平台资料人工翻拍辅助',
    routePath: '/review-workbench',
    roles: ['admin'],
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
