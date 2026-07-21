const fs = require('fs')

const source = fs.readFileSync('v2-web/src/views/TaskHallView.vue', 'utf8')

function assertContains(pattern, message) {
  if (!pattern.test(source)) throw new Error(message)
}

function assertNotContains(pattern, message) {
  if (pattern.test(source)) throw new Error(message)
}

assertContains(/fetchReviewTaskGroups/, 'TaskHallView must use the bounded review queue API')
assertContains(/<ElPagination/, 'TaskHallView must render review queue pagination')
assertContains(/:page-size="20"/, 'TaskHallView review queue page size must be 20')
assertNotContains(/limit=1000/, 'TaskHallView must not request 1000 review groups')
assertNotContains(/fetchTaskGroups\(currentTaskId\)/, 'TaskHallView background refresh must not fetch every group')
assertContains(/items\.slice\(0, 4\)/, 'TaskHallView may preload at most four thumbnails')
assertNotContains(/items\.slice\(0, 8\)/, 'TaskHallView must not preload eight thumbnails')
assertContains(
  /warmupFirstReviewGroup\(taskId:\s*string,\s*requestEpoch:\s*number\)[\s\S]*reviewQueueEpoch\.isCurrent\(requestEpoch\)/,
  'TaskHallView thumbnail warmup must remain bound to the current review queue request',
)
assertContains(
  /fetchGroupDetailCached\(\s*groupId:\s*string,\s*cacheGuard:[\s\S]*cacheGuard\(\)[\s\S]*groupDetailCache\.set/,
  'TaskHallView detail cache writes must support a request-epoch guard',
)
assertContains(
  /groupDetailRequests\s*=\s*new Map<[\s\S]*cacheEpoch:\s*number[\s\S]*requestEpoch:\s*number[\s\S]*request:\s*Promise<GroupDetail>/,
  'TaskHallView in-flight group details must record the cache and review request epochs',
)
assertContains(
  /groupDetailRequests\.set\(groupId,\s*\{ cacheEpoch, requestEpoch, request \}\)/,
  'TaskHallView must store each in-flight detail request with its cache and review epochs',
)
assertContains(
  /groupDetailRequests\.get\(groupId\)\?\.request === request/,
  'TaskHallView must only clear the matching in-flight detail request',
)
assertContains(
  /fetchGroupDetailCached\(\s*group\.id,\s*\(\) =>[\s\S]*reviewQueueEpoch\.isCurrent\(requestEpoch\)[\s\S]*,\s*requestEpoch,\s*\)/,
  'TaskHallView warmup must guard detail-cache writes with the current request epoch',
)
assertContains(
  /function invalidateGroupDetailCache\(\)[\s\S]*groupDetailCacheEpoch \+= 1[\s\S]*groupRequestSeq \+= 1[\s\S]*groupDetailCache\.clear\(\)[\s\S]*groupDetailRequests\.clear\(\)/,
  'TaskHallView must invalidate cached and in-flight group details as one generation',
)
assertContains(
  /const cacheEpoch = groupDetailCacheEpoch[\s\S]*cacheEpoch === groupDetailCacheEpoch && cacheGuard\(\)[\s\S]*groupDetailCache\.set/,
  'TaskHallView must reject detail-cache writes from an invalidated cache generation',
)
assertContains(
  /if \(existing && existing\.cacheEpoch === cacheEpoch && existing\.requestEpoch === requestEpoch\) return existing\.request/,
  'TaskHallView must not reuse an in-flight group detail from an invalidated cache generation',
)
assertContains(
  /if \(taskChanged \|\| options\.invalidateDetails\) invalidateGroupDetailCache\(\)/,
  'TaskHallView must invalidate group details when the same task is explicitly refreshed',
)
assertContains(
  /loadGroups\(selectedTaskId\.value,[\s\S]*invalidateDetails: Boolean\(options\.force\)[\s\S]*if \(options\.force && activeGroupId && selectedGroupId\.value === activeGroupId\)[\s\S]*await loadGroup\(activeGroupId\)/,
  'TaskHallView manual refresh must reload the currently open group detail',
)
assertContains(
  /async function refreshGroupsSilently\(\)[\s\S]*loadGroups\(currentTaskId, \{[\s\S]*invalidateDetails: true/,
  'TaskHallView silent and external refreshes must invalidate same-task group details',
)
assertContains(
  /async function refreshTaskAndGroupsSilently\(\)[\s\S]*await refreshTasksSilently\(\)[\s\S]*await refreshGroupsSilently\(\)/,
  'TaskHallView must refresh both task totals and the current review page after completing mutations',
)
assertContains(
  /if \(job\.completedGroup\)[\s\S]*await saveReview\(job\.groupId, 'approved'\)[\s\S]*await refreshTaskAndGroupsSilently\(\)/,
  'TaskHallView single-photo completion must refresh task totals and review groups',
)
assertContains(
  /async function archiveGroup\(\)[\s\S]*await completeGroupIfReady\(\)[\s\S]*await refreshTasksSilently\(\)[\s\S]*await selectNextUnfinishedGroup/,
  'TaskHallView full-group archive must refresh task totals before selecting the next group',
)
assertContains(
  /async function saveCurrentGroup\(\)[\s\S]*await completeGroupIfReady\(\)[\s\S]*await refreshTaskAndGroupsSilently\(\)/,
  'TaskHallView metadata save must refresh task totals and review groups',
)

console.log('task hall pagination checks passed')
