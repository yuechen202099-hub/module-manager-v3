import type { CurrentUser, MaterialGroup, Project, ReviewPhoto, ReviewTask } from './types'

export const mockUser: CurrentUser = {
  id: 'reviewer',
  username: 'reviewer',
  name: '资料审阅员',
  role: 'reviewer',
  roles: ['reviewer'],
  teamId: 'default-team',
}

export const mockProjects: Project[] = [
  {
    id: 'local-test',
    name: '模块更换项目',
    status: 'active',
    totalGroups: 0,
    completedGroups: 0,
    exceptionGroups: 0,
    updatedAt: '2026-06-19',
  },
]

export const mockTasks: ReviewTask[] = [
  {
    id: '1',
    projectId: 'local-test',
    name: '终端示例',
    stage: '本地测试',
    terminal: 'T-001',
    status: 'pending',
    totalGroups: 0,
    claimedGroups: 0,
    completedGroups: 0,
    canClaim: false,
    hasScanInfo: false,
    renovationCount: 0,
    uploadedCount: 0,
    reviewedCount: 0,
    unreviewedCount: 0,
    reviewRate: 0,
  },
]

export const mockGroups: MaterialGroup[] = [
  {
    id: 'g-001',
    taskId: '1',
    address: '待导入总清单地址',
    meterNo: '0000000000',
    terminal: 'T-001',
    status: 'pending',
    photoCount: 0,
  },
]

export const mockPhotos: ReviewPhoto[] = [
  {
    id: 'ph-001',
    name: '示例照片',
    url: '',
    status: 'unclassified',
  },
]
