import assert from 'node:assert/strict'
import fs from 'node:fs'

const view = fs.readFileSync('v2-web/src/views/ClaimTasksView.vue', 'utf8')
const services = fs.readFileSync('v2-web/src/api/services.ts', 'utf8')

assert.match(services, /constructionPriority:\s*Boolean\(raw\.construction_priority\)/)
assert.match(services, /constructionAvailable:\s*Boolean\(raw\.construction_available\)/)
assert.match(services, /reviewAvailable:\s*Boolean\(raw\.review_available\)/)
for (const label of ['全部', '优先施工', '可施工', '可领取审阅']) assert.ok(view.includes(label))
assert.match(view, /task\.constructionPriority/)
assert.match(view, /task\.constructionAvailable/)
assert.match(view, /task\.reviewAvailable/)
assert.doesNotMatch(view, /constructionAvailable\s*=\s*computed/)

console.log('Claim task construction priority verification passed.')
