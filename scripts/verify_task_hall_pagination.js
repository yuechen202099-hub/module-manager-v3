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
  /fetchGroupDetailCached\(groupId:\s*string,\s*cacheGuard:[\s\S]*if \(cacheGuard\(\)\) groupDetailCache\.set/,
  'TaskHallView detail cache writes must support a request-epoch guard',
)
assertContains(
  /groupDetailRequests\.get\(groupId\) === request/,
  'TaskHallView must only clear the matching in-flight detail request',
)
assertContains(
  /fetchGroupDetailCached\(\s*group\.id,\s*\(\) =>[\s\S]*reviewQueueEpoch\.isCurrent\(requestEpoch\)/,
  'TaskHallView warmup must guard detail-cache writes with the current request epoch',
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
