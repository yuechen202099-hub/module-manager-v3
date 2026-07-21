export type ReviewQueueRequestEpoch = {
  begin(): number
  invalidate(): void
  isCurrent(candidate: number): boolean
}

export function createReviewQueueRequestEpoch(): ReviewQueueRequestEpoch

export function nextReviewQueuePageAfterMutation(options: {
  page: number
  pageSize: number
  total: number
  remainingOnPage: number
}): number
