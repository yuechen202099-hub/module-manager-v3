export type LatestRequest = {
  signal: AbortSignal
  isCurrent: () => boolean
  finish: () => void
}

export type LatestRequestGate = {
  begin: () => LatestRequest
  cancel: () => void
}

export function isAbortError(error: unknown): boolean
export function createLatestRequestGate(setLoading?: (loading: boolean) => void): LatestRequestGate
