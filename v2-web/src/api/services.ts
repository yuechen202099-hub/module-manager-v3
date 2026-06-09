import { mockGroups, mockPhotos, mockProjects, mockTasks, mockUser } from './mock'
import type { CurrentUser, MaterialGroup, Project, ReviewPhoto, ReviewTask, TaskStatus } from './types'

const delay = (ms = 180) => new Promise((resolve) => window.setTimeout(resolve, ms))

export async function login(username: string, password: string): Promise<{ token: string; user: CurrentUser }> {
  await delay()
  if (!username || !password) {
    throw new Error('请输入账号和密码')
  }

  return {
    token: 'mock-token',
    user: { ...mockUser, name: username === 'admin' ? '管理员' : mockUser.name, role: username === 'admin' ? 'admin' : 'reviewer' },
  }
}

export async function fetchCurrentUser(): Promise<CurrentUser> {
  await delay()
  return mockUser
}

export async function fetchProjects(): Promise<Project[]> {
  await delay()
  return mockProjects
}

export async function fetchTasks(): Promise<ReviewTask[]> {
  await delay()
  return mockTasks
}

export async function claimTask(taskId: string): Promise<ReviewTask> {
  await delay()
  const task = mockTasks.find((item) => item.id === taskId)
  if (!task) {
    throw new Error('任务不存在')
  }
  return { ...task, status: 'in_review', ownerName: mockUser.name }
}

export async function fetchTaskGroups(taskId = 't-001'): Promise<MaterialGroup[]> {
  await delay()
  return mockGroups.filter((group) => group.taskId === taskId)
}

export async function fetchGroup(groupId: string): Promise<{ group: MaterialGroup; photos: ReviewPhoto[] }> {
  await delay()
  const group = mockGroups.find((item) => item.id === groupId) || mockGroups[0]
  return { group, photos: mockPhotos }
}

export async function saveReview(groupId: string, status: TaskStatus): Promise<MaterialGroup> {
  await delay()
  const group = mockGroups.find((item) => item.id === groupId) || mockGroups[0]
  return { ...group, status }
}
