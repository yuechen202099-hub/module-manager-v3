export function createReviewQueueRequestEpoch() {
  let value = 0
  return {
    begin() {
      value += 1
      return value
    },
    invalidate() {
      value += 1
    },
    isCurrent(candidate) {
      return candidate === value
    },
  }
}

export function nextReviewQueuePageAfterMutation({ page, pageSize, total, remainingOnPage }) {
  if (remainingOnPage > 0 || page <= 1) return Math.max(1, page)
  return Math.max(1, Math.min(page - 1, Math.ceil(Math.max(0, total - 1) / pageSize)))
}
