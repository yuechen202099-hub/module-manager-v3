import assert from 'node:assert/strict'
import test from 'node:test'

import * as claimTasksState from '../v2-web/src/api/claimTasksState.mjs'


test('claimTasksState only exposes the production priority request helper', () => {
  assert.deepEqual(Object.keys(claimTasksState).sort(), ['priorityRequestBody'])
  assert.deepEqual(claimTasksState.priorityRequestBody(true), { priority: true })
  assert.deepEqual(claimTasksState.priorityRequestBody(false), { priority: false })
})
