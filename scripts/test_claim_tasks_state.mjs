import assert from 'node:assert/strict'

import {
  applyTaskMutation,
  createTaskRequestEpoch,
  createVisibleLoadTracker,
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

function createLoadHarness(initialTasks = [{ ...tasks[0], constructionPriority: false }]) {
  const epoch = createTaskRequestEpoch()
  const visibleLoads = createVisibleLoadTracker()
  const state = {
    cacheVersion: 'before',
    error: '',
    loading: false,
    tasks: initialTasks,
    version: 'before',
  }

  async function load({ silent = false, status, result }) {
    const requestEpoch = epoch.begin()
    const releaseVisibleLoad = silent ? null : visibleLoads.acquire()
    if (!silent) state.loading = visibleLoads.isLoading()
    state.error = ''
    try {
      const nextStatus = await status
      if (!epoch.isCurrent(requestEpoch)) return
      const nextTasks = await result
      if (!epoch.isCurrent(requestEpoch)) return
      state.tasks = nextTasks
      state.version = nextStatus.version
      state.cacheVersion = nextStatus.version
    } catch (error) {
      if (epoch.isCurrent(requestEpoch)) state.error = error instanceof Error ? error.message : String(error)
    } finally {
      if (releaseVisibleLoad) {
        releaseVisibleLoad()
        state.loading = visibleLoads.isLoading()
      }
    }
  }

  async function applyMutation(request, priority) {
    return applyTaskMutation({
      epoch,
      onSuccess(updated) {
        state.tasks = replaceTaskById(state.tasks, updated)
        state.version = ''
        state.cacheVersion = ''
      },
      priority,
      request,
      taskId: state.tasks[0].id,
    })
  }

  return { applyMutation, load, state }
}

async function flush() {
  await Promise.resolve()
  await Promise.resolve()
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

const patchRace = createLoadHarness()
const staleStatus = deferred()
const staleResult = deferred()
const visiblePatchLoad = patchRace.load({ silent: false, status: staleStatus.promise, result: staleResult.promise })
assert.equal(patchRace.state.loading, true)
await patchRace.applyMutation(async () => ({ ...tasks[0], constructionPriority: true }), true)
staleStatus.resolve({ version: 'stale' })
staleResult.resolve([{ ...tasks[0], constructionPriority: false }])
await visiblePatchLoad
assert.equal(patchRace.state.loading, false)
assert.equal(patchRace.state.tasks[0].constructionPriority, true)
assert.equal(patchRace.state.version, '')
assert.equal(patchRace.state.cacheVersion, '')

for (const resolveVisibleFirst of [true, false]) {
  const race = createLoadHarness()
  const visibleStatus = deferred()
  const visibleResult = deferred()
  const silentStatus = deferred()
  const silentResult = deferred()
  const visibleLoad = race.load({ status: visibleStatus.promise, result: visibleResult.promise })
  const silentLoad = race.load({ silent: true, status: silentStatus.promise, result: silentResult.promise })
  assert.equal(race.state.loading, true)
  if (resolveVisibleFirst) {
    visibleStatus.resolve({ version: 'visible' })
    visibleResult.resolve([{ ...tasks[0], constructionPriority: false }])
    await visibleLoad
    assert.equal(race.state.loading, false)
    silentStatus.resolve({ version: 'silent' })
    silentResult.resolve([{ ...tasks[0], constructionPriority: true }])
    await silentLoad
  } else {
    silentStatus.resolve({ version: 'silent' })
    silentResult.resolve([{ ...tasks[0], constructionPriority: true }])
    await silentLoad
    assert.equal(race.state.loading, true)
    visibleStatus.resolve({ version: 'visible' })
    visibleResult.resolve([{ ...tasks[0], constructionPriority: false }])
    await visibleLoad
  }
  assert.equal(race.state.loading, false)
}

for (const resolveFirstLoadFirst of [true, false]) {
  const race = createLoadHarness()
  const firstStatus = deferred()
  const firstResult = deferred()
  const secondStatus = deferred()
  const secondResult = deferred()
  const firstLoad = race.load({ status: firstStatus.promise, result: firstResult.promise })
  const secondLoad = race.load({ status: secondStatus.promise, result: secondResult.promise })
  assert.equal(race.state.loading, true)
  if (resolveFirstLoadFirst) {
    firstStatus.resolve({ version: 'first' })
    firstResult.resolve([{ ...tasks[0], constructionPriority: false }])
    await firstLoad
    assert.equal(race.state.loading, true)
    secondStatus.resolve({ version: 'second' })
    secondResult.resolve([{ ...tasks[0], constructionPriority: true }])
    await secondLoad
  } else {
    secondStatus.resolve({ version: 'second' })
    secondResult.resolve([{ ...tasks[0], constructionPriority: true }])
    await secondLoad
    assert.equal(race.state.loading, true)
    firstStatus.resolve({ version: 'first' })
    firstResult.resolve([{ ...tasks[0], constructionPriority: false }])
    await firstLoad
  }
  assert.equal(race.state.loading, false)
}

const failedMutation = createLoadHarness()
const unchangedState = { ...failedMutation.state }
await assert.rejects(
  failedMutation.applyMutation(async () => {
    throw new Error('priority update rejected')
  }, true),
  /priority update rejected/,
)
assert.equal(failedMutation.state.tasks, unchangedState.tasks)
assert.equal(failedMutation.state.version, unchangedState.version)
assert.equal(failedMutation.state.cacheVersion, unchangedState.cacheVersion)
await flush()

console.log('claim task state behavior checks passed')
