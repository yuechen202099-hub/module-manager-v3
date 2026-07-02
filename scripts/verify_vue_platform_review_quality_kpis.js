const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const boardPath = path.join(root, 'v2-web', 'src', 'views', 'ProjectBoardView.vue')
const projectsPath = path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue')
const board = fs.readFileSync(boardPath, 'utf8')
const projects = fs.readFileSync(projectsPath, 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

for (const token of [
  'platformReviewQualityCards',
  'platformReviewQualitySummary',
  '审阅质量',
  '通过归档',
  '退回返工',
  '待审工单',
  '通过率',
  '返工率',
  'platform-review-quality-grid',
  'platform-review-quality-note',
]) {
  if (!board.includes(token)) {
    fail(`ProjectBoardView must expose review quality KPI token: ${token}`)
  }
}

for (const expression of [
  'tasks?.approvedArchive || tasks?.archived || 0',
  'tasks?.returnedRework || 0',
  'tasks?.pendingReview || tasks?.reviewing || 0',
]) {
  if (!board.includes(expression)) {
    fail(`ProjectBoardView review quality must derive from task summary: ${expression}`)
  }
}

for (const token of [
  'platform-review-quality-line',
  '审阅质量',
  '通过 {{ row.tasks?.approvedArchive || row.tasks?.archived || 0 }}',
  '返工 {{ row.tasks?.returnedRework || 0 }}',
  '待审 {{ row.tasks?.pendingReview || row.tasks?.reviewing || 0 }}',
  '通过率 {{ row.tasks?.reviewRate || 0 }}%',
]) {
  if (!projects.includes(token)) {
    fail(`ProjectsView must expose compact review quality token: ${token}`)
  }
}

console.log('[OK] Vue project views connect delivery KPIs with review quality metrics.')
