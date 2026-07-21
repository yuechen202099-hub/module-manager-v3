export function isClaimTasksCacheValid(cached) {
  return Boolean(cached?.tasks?.length) && cached.tasks.every((task) => (
    typeof task?.constructionPriority === 'boolean'
    && typeof task?.constructionAvailable === 'boolean'
    && typeof task?.reviewAvailable === 'boolean'
  ))
}

export function hydrateClaimTasksCache(storage, cacheKey, legacyCacheKey) {
  storage.removeItem(legacyCacheKey)
  try {
    const cached = JSON.parse(storage.getItem(cacheKey) || 'null')
    if (!isClaimTasksCacheValid(cached)) {
      storage.removeItem(cacheKey)
      return null
    }
    return cached
  } catch {
    storage.removeItem(cacheKey)
    return null
  }
}

export function filterClaimTasks(tasks, filter) {
  const items = tasks.filter((task) => {
    if (filter === 'priority') return task.constructionPriority
    if (filter === 'construction') return task.constructionAvailable
    if (filter === 'review') return task.reviewAvailable
    return true
  })
  if (filter !== 'all' && filter !== 'construction') return items
  return items.sort((left, right) => Number(right.constructionPriority) - Number(left.constructionPriority))
}

export function createTaskRequestEpoch() {
  let value = 0
  return {
    begin() {
      value += 1
      return value
    },
    invalidate() {
      value += 1
      return value
    },
    isCurrent(epoch) {
      return epoch === value
    },
  }
}

export function priorityRequestBody(priority) {
  return { priority: Boolean(priority) }
}

export function replaceTaskById(tasks, updated) {
  return tasks.map((task) => (task.id === updated.id ? updated : task))
}
