const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const projectsViewPath = path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue')
const source = fs.readFileSync(projectsViewPath, 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

for (const token of [
  'templateUsageCards',
  'initial_work_orders',
  'external_completed',
  '运行到一半的项目接入平台',
  '系统外已经完成，只需要接入审阅和归档',
  'importWizardStepCards',
  '校验模板',
  '生成预览',
  '确认批次',
  '生成工单',
  '接入平台',
  'importWizardNextActionHint',
  '下一步建议',
  '去施工采集',
  '去审阅工作台',
  '可以回滚本次本地接入',
]) {
  if (!source.includes(token)) {
    fail(`Projects import wizard guidance must include: ${token}`)
  }
}

for (const className of [
  'template-usage-grid',
  'template-usage-card',
  'import-wizard-steps',
  'import-wizard-next-hint',
]) {
  if (!source.includes(className)) {
    fail(`Projects import wizard guidance must style: ${className}`)
  }
}

const dialogMatch = source.match(/<ElDialog[\s\S]*?:title="`导入前校验报告[\s\S]*?<\/ElDialog>/)
if (!dialogMatch) {
  fail('Projects import validation dialog must be found')
}

const dialog = dialogMatch[0]
if (!dialog.includes('importWizardStepCards') || !dialog.includes('importWizardNextActionHint')) {
  fail('Projects import validation dialog must show guided steps and next-action hint')
}

console.log('[OK] Vue project import wizard explains template choices and next actions.')
