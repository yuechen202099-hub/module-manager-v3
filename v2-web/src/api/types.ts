export type ApiEnvelope<T> = {
  data: T
  error: null
  request_id: string
}

export type ApiErrorEnvelope = {
  data: null
  error: {
    code: string
    message: string
    details?: Record<string, unknown>
  }
  request_id: string
}

export type UserRole = 'admin' | 'reviewer'

export type CurrentUser = {
  id: string
  name: string
  role: UserRole
}

export type Project = {
  id: string
  name: string
  status: 'active' | 'archived'
  totalGroups: number
  completedGroups: number
  exceptionGroups: number
  updatedAt: string
}

export type TaskStatus = 'pending' | 'in_review' | 'complete' | 'exception' | 'incomplete' | 'locked'

export type ReviewTask = {
  id: string
  projectId: string
  name: string
  stage: string
  status: TaskStatus
  totalGroups: number
  claimedGroups: number
  completedGroups: number
  ownerName?: string
}

export type MaterialGroup = {
  id: string
  taskId: string
  address: string
  meterNo: string
  terminal: string
  status: TaskStatus
  photoCount: number
}

export type ReviewPhoto = {
  id: string
  url: string
  name: string
  status: 'unclassified' | 'valid' | 'invalid' | 'exception'
}
