import assert from 'node:assert/strict'
import test from 'node:test'

import { createLatestRequestGate, isAbortError } from '../v2-web/src/utils/latestRequestGate.mjs'


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
