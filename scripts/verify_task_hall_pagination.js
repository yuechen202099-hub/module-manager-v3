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

console.log('task hall pagination checks passed')
