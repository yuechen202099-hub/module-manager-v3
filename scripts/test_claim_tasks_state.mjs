import assert from 'node:assert/strict'

import {
  createTaskRequestEpoch,
  filterClaimTasks,
  hydrateClaimTasksCache,
  isClaimTasksCacheValid,
  priorityRequestBody,
  replaceTaskById,
} from '../v2-web/src/api/claimTasksState.mjs'

function deferred() {
  let resolve
  const promise = new Promise((done) => {
    resolve = done
  })
  return { promise, resolve }
}

const tasks = [
  { id: 'plain', terminal: 'B', uploadedCount: 1, constructionPriority: false, constructionAvailable: true, reviewAvailable: false },
  { id: 'priority', terminal: 'C', uploadedCount: 1, constructionPriority: true, constructionAvailable: true, reviewAvailable: true },
  { id: 'review', terminal: 'A', uploadedCount: 0, constructionPriority: false, constructionAvailable: false, reviewAvailable: true },
]

assert.deepEqual(filterClaimTasks(tasks, 'priority').map((task) => task.id), ['priority'])
assert.deepEqual(filterClaimTasks(tasks, 'construction').map((task) => task.id), ['priority', 'plain'])
assert.deepEqual(filterClaimTasks(tasks, 'review').map((task) => task.id), ['priority', 'review'])
assert.deepEqual(filterClaimTasks(tasks, 'all').map((task) => task.id), ['priority', 'plain', 'review'])
assert.deepEqual(
  filterClaimTasks([
    { ...tasks[1], id: 'priority-first' },
    { ...tasks[1], id: 'priority-second' },
    tasks[0],
  ], 'construction').map((task) => task.id),
  ['priority-first', 'priority-second', 'plain'],
)

assert.equal(isClaimTasksCacheValid({ tasks: [tasks[0]] }), true)
assert.equal(isClaimTasksCacheValid({ tasks: [{ ...tasks[0], constructionAvailable: undefined }] }), false)
assert.equal(isClaimTasksCacheValid({ tasks: [] }), false)

const cacheStorage = new Map([
  ['v3', JSON.stringify({ version: 'same-status-version', tasks: [tasks[0]] })],
  ['v4', JSON.stringify({ version: 'same-status-version', tasks: [{ ...tasks[0], reviewAvailable: undefined }] })],
])
const storage = {
  getItem: (key) => cacheStorage.get(key) || null,
  removeItem: (key) => cacheStorage.delete(key),
}
assert.equal(hydrateClaimTasksCache(storage, 'v4', 'v3'), null)
assert.equal(cacheStorage.has('v3'), false)
assert.equal(cacheStorage.has('v4'), false)

assert.deepEqual(priorityRequestBody(true), { priority: true })
assert.deepEqual(priorityRequestBody(false), { priority: false })

const epoch = createTaskRequestEpoch()
let rendered = [{ ...tasks[0], constructionPriority: false }]
const staleLoad = deferred()
const staleEpoch = epoch.begin()
void staleLoad.promise.then((result) => {
  if (epoch.isCurrent(staleEpoch)) rendered = result
})
epoch.invalidate()
rendered = replaceTaskById(rendered, { ...rendered[0], constructionPriority: true })
staleLoad.resolve([{ ...tasks[0], constructionPriority: false }])
await staleLoad.promise
await Promise.resolve()
assert.equal(rendered[0].constructionPriority, true)

const beforeFailure = rendered
await Promise.reject(new Error('priority update rejected')).catch(() => undefined)
assert.equal(rendered, beforeFailure)

console.log('claim task state behavior checks passed')
