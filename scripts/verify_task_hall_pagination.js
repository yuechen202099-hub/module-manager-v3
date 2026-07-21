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

console.log('task hall pagination checks passed')
