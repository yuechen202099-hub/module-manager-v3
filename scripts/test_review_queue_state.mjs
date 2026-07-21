import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createReviewQueueRequestEpoch,
  nextReviewQueuePageAfterMutation,
} from '../v2-web/src/api/reviewQueueState.mjs'

test('stale review queue requests cannot replace a newer page', () => {
  const epoch = createReviewQueueRequestEpoch()
  const first = epoch.begin()
  const second = epoch.begin()

  assert.equal(epoch.isCurrent(first), false)
  assert.equal(epoch.isCurrent(second), true)
})

test('invalidating the review queue rejects every earlier request', () => {
  const epoch = createReviewQueueRequestEpoch()
  const request = epoch.begin()

  epoch.invalidate()

  assert.equal(epoch.isCurrent(request), false)
})

test('empty last page falls back to the previous valid page', () => {
  assert.equal(
    nextReviewQueuePageAfterMutation({ page: 3, pageSize: 20, total: 40, remainingOnPage: 0 }),
    2,
  )
  assert.equal(
    nextReviewQueuePageAfterMutation({ page: 1, pageSize: 20, total: 0, remainingOnPage: 0 }),
    1,
  )
})

test('a page with remaining rows stays selected', () => {
  assert.equal(
    nextReviewQueuePageAfterMutation({ page: 3, pageSize: 20, total: 45, remainingOnPage: 4 }),
    3,
  )
})
