import type { ReviewTask } from './types'

export function isClaimTasksCacheValid(cached: unknown): boolean
export function hydrateClaimTasksCache(
  storage: Pick<Storage, 'getItem' | 'removeItem'>,
  cacheKey: string,
  legacyCacheKey: string,
): { version?: string; tasks: ReviewTask[] } | null
export function filterClaimTasks(tasks: ReviewTask[], filter: 'all' | 'priority' | 'construction' | 'review'): ReviewTask[]
export function createTaskRequestEpoch(): {
  begin(): number
  invalidate(): number
  isCurrent(epoch: number): boolean
}
export function priorityRequestBody(priority: boolean): { priority: boolean }
export function replaceTaskById(tasks: ReviewTask[], updated: ReviewTask): ReviewTask[]
