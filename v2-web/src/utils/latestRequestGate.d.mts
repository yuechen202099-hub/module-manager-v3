export type LatestRequest = {
  signal: AbortSignal
  isCurrent: () => boolean
  finish: () => void
}

export type MutationGuardedRequest = {
  signal: AbortSignal
  serial: number
  mutationVersion: number
  isCurrent: (currentMutationVersion: number) => boolean
  finish: () => void
}

export type LatestRequestGate = {
  begin: () => LatestRequest
  cancel: () => void
}

export type MutationGuardedRequestGate = {
  begin: (mutationVersion?: number) => MutationGuardedRequest
  invalidate: () => void
  cancel: () => void
}

export function isAbortError(error: unknown): boolean
export function createLatestRequestGate(setLoading?: (loading: boolean) => void): LatestRequestGate
export function createMutationGuardedRequestGate(setLoading?: (loading: boolean) => void): MutationGuardedRequestGate
