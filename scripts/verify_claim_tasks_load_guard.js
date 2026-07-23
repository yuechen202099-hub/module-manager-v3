const fs = require('node:fs')
const assert = require('node:assert/strict')

const source = fs.readFileSync('v2-web/src/views/ClaimTasksView.vue', 'utf8')

function assertContains(pattern, message) {
  assert.match(source, pattern, message)
}

assertContains(/createMutationGuardedRequestGate/, 'ClaimTasksView must use the mutation-guarded request gate')
assertContains(/let taskMutationVersion = 0/, 'ClaimTasksView must track the current mutation version')
assertContains(/const request = taskLoadGate\.begin\(taskMutationVersion\)/, 'ClaimTasksView loads must capture the current mutation version')
assertContains(/fetchTaskSnapshot\(\{\s*force,\s*signal: request\.signal\s*\}\)/, 'ClaimTasksView must forward the abort signal to fetchTaskSnapshot')
assertContains(/request\.isCurrent\(taskMutationVersion\)/, 'ClaimTasksView must reject stale or mutated responses before overwriting tasks')
assertContains(/taskMutationVersion \+= 1/, 'ClaimTasksView successful mutations must advance the mutation version')
assertContains(/taskLoadGate\.invalidate\(\)/, 'ClaimTasksView successful mutations must invalidate in-flight loads')

console.log('verify_claim_tasks_load_guard: OK')
