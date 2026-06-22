export type StaticPageKey =
  | 'project-board'
  | 'claim-tasks'
  | 'task-hall'
  | 'construction'
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
    subtitle: '项目进度、风险与采集审阅态势',
    routePath: '/project-board',
    roles: ['admin', 'reviewer'],
    migrationStatus: 'native_vue',
  },
  {
    key: 'claim-tasks',
    title: '任务领取',
    subtitle: '按终端领取审阅任务',
    routePath: '/claim-tasks',
    roles: ['admin', 'reviewer'],
    migrationStatus: 'native_vue',
  },
  {
    key: 'task-hall',
    title: '审阅工作台',
    subtitle: '图片分类、异常处理、补图',
    routePath: '/task-hall',
    roles: ['admin', 'reviewer'],
    migrationStatus: 'native_vue',
  },
  {
    key: 'construction',
    title: '施工采集',
    subtitle: '手机采集、扫码、拍照、离线缓存',
    routePath: '/construction',
    roles: ['admin', 'constructor'],
    migrationStatus: 'native_vue',
  },
  {
    key: 'sync-config',
    title: '导入配置',
    subtitle: '历史兼容配置入口',
    routePath: '/sync-config',
    roles: ['admin'],
    migrationStatus: 'native_vue',
  },
]

export function findStaticPage(key: string | undefined) {
  return staticPages.find((page) => page.key === key)
}
