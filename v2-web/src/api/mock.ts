import type { CurrentUser, MaterialGroup, Project, ReviewPhoto, ReviewTask } from './types'

export const mockUser: CurrentUser = {
  id: 'u-001',
  name: '资料审阅员',
  role: 'reviewer',
}

export const mockProjects: Project[] = [
  {
    id: 'p-001',
    name: '聚丰园路模块更换',
    status: 'active',
    totalGroups: 23000,
    completedGroups: 12860,
    exceptionGroups: 214,
    updatedAt: '2026-06-09 10:20',
  },
]

export const mockTasks: ReviewTask[] = [
  {
    id: 't-001',
    projectId: 'p-001',
    name: '聚丰园路188弄 第1批',
    stage: '一期',
    status: 'in_review',
    totalGroups: 320,
    claimedGroups: 80,
    completedGroups: 53,
    ownerName: '资料审阅员',
  },
  {
    id: 't-002',
    projectId: 'p-001',
    name: '聚丰园路95弄 第2批',
    stage: '二期',
    status: 'pending',
    totalGroups: 280,
    claimedGroups: 0,
    completedGroups: 0,
  },
  {
    id: 't-003',
    projectId: 'p-001',
    name: '聚丰园路188弄 异常复核',
    stage: '复核',
    status: 'exception',
    totalGroups: 46,
    claimedGroups: 12,
    completedGroups: 6,
    ownerName: '管理员',
  },
]

export const mockGroups: MaterialGroup[] = [
  {
    id: 'g-001',
    taskId: 't-001',
    address: '聚丰园路188弄52号101室',
    meterNo: '0012345678',
    terminal: 'A-01',
    status: 'in_review',
    photoCount: 5,
  },
  {
    id: 'g-002',
    taskId: 't-001',
    address: '聚丰园路188弄52号102室',
    meterNo: '0012345679',
    terminal: 'A-02',
    status: 'pending',
    photoCount: 4,
  },
  {
    id: 'g-003',
    taskId: 't-001',
    address: '聚丰园路188弄53号201室',
    meterNo: '0012345680',
    terminal: 'B-01',
    status: 'incomplete',
    photoCount: 2,
  },
]

export const mockPhotos: ReviewPhoto[] = [
  {
    id: 'ph-001',
    name: '表前照片',
    url: 'https://images.unsplash.com/photo-1558618666-fcd25c85cd64?auto=format&fit=crop&w=1200&q=80',
    status: 'valid',
  },
  {
    id: 'ph-002',
    name: '表后照片',
    url: 'https://images.unsplash.com/photo-1581092160607-ee22621dd758?auto=format&fit=crop&w=1200&q=80',
    status: 'unclassified',
  },
  {
    id: 'ph-003',
    name: '铭牌照片',
    url: 'https://images.unsplash.com/photo-1581092580497-e0d23cbdf1dc?auto=format&fit=crop&w=1200&q=80',
    status: 'unclassified',
  },
]
