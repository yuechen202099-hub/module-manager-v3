const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const typesPath = path.join(root, 'v2-web', 'src', 'api', 'types.ts')
const servicesPath = path.join(root, 'v2-web', 'src', 'api', 'services.ts')
const reviewPath = path.join(root, 'v2-web', 'src', 'views', 'ReviewView.vue')
const taskHallPath = path.join(root, 'v2-web', 'src', 'views', 'TaskHallView.vue')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

for (const filePath of [typesPath, servicesPath, reviewPath, taskHallPath]) {
  if (!fs.existsSync(filePath)) fail(`${path.basename(filePath)} must exist`)
}

const types = fs.readFileSync(typesPath, 'utf8')
const services = fs.readFileSync(servicesPath, 'utf8')
const review = fs.readFileSync(reviewPath, 'utf8')
const taskHall = fs.readFileSync(taskHallPath, 'utf8')

const requiredTokens = [
  [types, 'suggestedReviewReturnReason', 'review work order type must expose suggested return reason'],
  [services, 'suggested_review_return_reason', 'services must read backend suggested return reason'],
  [services, 'suggestedReviewReturnReason', 'services must map suggested return reason'],
  [review, 'reviewReturnReasonSuggestion', 'ReviewView must compute return reason suggestion'],
  [review, 'applyReviewReturnReasonSuggestion', 'ReviewView must let reviewers apply the suggestion'],
  [review, '建议退回原因', 'ReviewView must label the suggested return reason'],
  [review, '采用缺口原因', 'ReviewView must expose the apply action'],
  [taskHall, 'platformReviewReturnReasonSuggestion', 'TaskHallView must compute platform return reason suggestion'],
  [taskHall, '建议退回原因', 'TaskHallView must mention suggested return reason'],
  [taskHall, 'inputValue: platformReviewReturnReasonSuggestion', 'TaskHall return prompt must default to suggestion'],
]

for (const [source, token, message] of requiredTokens) {
  if (!source.includes(token)) fail(`${message}: ${token}`)
}

console.log('[OK] Vue review return reason suggestions are wired.')
