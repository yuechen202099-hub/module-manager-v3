const fs = require('fs')

function read(path) {
  return fs.readFileSync(path, 'utf8')
}

function assertContains(source, pattern, message) {
  if (!source.includes(pattern)) {
    throw new Error(message)
  }
}

function assertNotContains(source, pattern, message) {
  if (source.includes(pattern)) {
    throw new Error(message)
  }
}

const claimTasks = read('v2-web/src/views/ClaimTasksView.vue')

assertContains(claimTasks, 'function isTaskReviewComplete(task: ReviewTask)', 'ClaimTasksView must define review completion detection')
assertContains(claimTasks, "if (isTaskReviewComplete(task)) return '已审阅'", 'review-complete tasks must display 已审阅 before claimed state')
assertContains(claimTasks, '(Number(task.reviewRate) || 0) >= 1', 'review completion must use the raw 100% review rate')
assertContains(claimTasks, 'Math.min(99, Math.floor((Number(task.reviewRate) || 0) * 100))', 'unfinished review progress must not round up to 100%')
assertNotContains(claimTasks, '已审完', 'task claim page must not use the old 已审完 label')

assertContains(claimTasks, 'function isTaskConstructionComplete(task: ReviewTask)', 'ClaimTasksView must define construction completion detection')
assertContains(claimTasks, "return isTaskConstructionComplete(task) ? '已施工' : taskConstructorName(task)", 'construction-complete tasks must display 已施工')
assertContains(claimTasks, 'task.constructionUnbuiltCount !== undefined', 'construction completion must respect unbuilt count from backend')
assertContains(claimTasks, 'task.constructionUploadedCount ?? task.uploadedCount ?? 0', 'construction completion must fall back to uploaded count')
assertContains(claimTasks, '(Number(task.uploadRate) || 0) >= 1', 'construction completion must use the raw 100% upload rate')
assertContains(claimTasks, '{{ taskConstructionLabel(task) }}', 'construction line must render the completion-aware label')
assertContains(
  claimTasks,
  '!isTaskConstructionComplete(task) && taskConstructorAccountHint(task)',
  'completed construction rows should not show account hint as the primary status',
)

assertContains(claimTasks, 'function reviewActionLabel(task: ReviewTask)', 'ClaimTasksView must define review action label')
assertContains(claimTasks, "if (isTaskReviewComplete(task)) return '已审阅'", 'review-complete action button must display 已审阅')
assertContains(claimTasks, 'function isReviewActionDisabled(task: ReviewTask)', 'ClaimTasksView must define review action disabled state')
assertContains(claimTasks, 'if (isTaskReviewComplete(task)) return true', 'review-complete action button must be disabled')
assertContains(claimTasks, ':disabled="isReviewActionDisabled(task)"', 'review action button must use the completion-aware disabled state')
assertContains(claimTasks, '{{ reviewActionLabel(task) }}', 'review action button must render the completion-aware label')

assertContains(claimTasks, 'function constructionActionLabel(task: ReviewTask)', 'ClaimTasksView must define construction action label')
assertContains(claimTasks, "if (isTaskConstructionComplete(task)) return '已施工'", 'construction-complete action button must display 已施工')
assertContains(claimTasks, 'function isConstructionActionDisabled(task: ReviewTask)', 'ClaimTasksView must define construction action disabled state')
assertContains(claimTasks, 'return isTaskConstructionComplete(task)', 'construction-complete action button must be disabled')
assertContains(claimTasks, ':disabled="isConstructionActionDisabled(task)"', 'construction action button must use the completion-aware disabled state')
assertContains(claimTasks, '{{ constructionActionLabel(task) }}', 'construction action button must render the completion-aware label')
assertContains(claimTasks, ':disabled="isTaskReviewComplete(task) || (!task.claimedBy && !isAdmin)"', 'dropdown release action must be disabled for reviewed tasks')
assertContains(claimTasks, 'if (isTaskReviewComplete(task)) return\n  errorMessage.value', 'claim and release handlers must ignore reviewed tasks')
assertContains(claimTasks, 'if (isTaskConstructionComplete(task)) return\n  assignmentTargetTask.value', 'assignment dialog must ignore constructed tasks')
assertContains(claimTasks, "if (command.action === 'assign') {\n    if (isTaskConstructionComplete(task)) return", 'dropdown assign command must guard constructed tasks')
assertContains(claimTasks, "if (command.action === 'release') {\n    if (isTaskReviewComplete(task)) return", 'dropdown release command must guard reviewed tasks')

console.log('claim task completion status checks passed')
