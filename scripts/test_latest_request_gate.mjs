import assert from 'node:assert/strict'
import test from 'node:test'

import * as latestRequestGate from '../v2-web/src/utils/latestRequestGate.mjs'

const { createLatestRequestGate, isAbortError } = latestRequestGate


test('latest response wins and stale completion cannot clear current loading state', async () => {
  const loadingStates = []
  const gate = createLatestRequestGate((loading) => loadingStates.push(loading))
  const rows = []

  const first = gate.begin()
  const second = gate.begin()
  assert.equal(first.signal.aborted, true)
  assert.equal(second.signal.aborted, false)

  if (second.isCurrent()) rows.push('newest')
  second.finish()
  if (first.isCurrent()) rows.push('stale')
  first.finish()

  assert.deepEqual(rows, ['newest'])
  assert.deepEqual(loadingStates, [true, true, false])
})

test('cancel aborts teardown requests and abort errors stay silent', () => {
  const loadingStates = []
  const gate = createLatestRequestGate((loading) => loadingStates.push(loading))
  const request = gate.begin()

  gate.cancel()

  assert.equal(request.signal.aborted, true)
  assert.equal(request.isCurrent(), false)
  assert.deepEqual(loadingStates, [true, false])
  assert.equal(isAbortError(new DOMException('aborted', 'AbortError')), true)
  assert.equal(isAbortError(new Error('network down')), false)
})

test('mutation-guarded requests record mutation version and invalidate stale loads', () => {
  assert.equal(typeof latestRequestGate.createMutationGuardedRequestGate, 'function')

  const loadingStates = []
  const gate = latestRequestGate.createMutationGuardedRequestGate((loading) => loadingStates.push(loading))
  const first = gate.begin(0)

  assert.equal(first.serial, 1)
  assert.equal(first.mutationVersion, 0)
  assert.equal(first.isCurrent(0), true)

  gate.invalidate()

  assert.equal(first.signal.aborted, true)
  assert.equal(first.isCurrent(1), false)

  const second = gate.begin(1)
  assert.equal(second.serial, 2)
  assert.equal(second.mutationVersion, 1)
  assert.equal(second.isCurrent(1), true)

  second.finish()
  first.finish()

  assert.deepEqual(loadingStates, [true, false, true, false])
})
