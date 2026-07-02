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
  'importWizardPrimaryLabel',
  'importWizardPrimaryType',
  'importWizardPrimaryLoading',
  'canRunImportWizardPrimaryAction',
  'runImportWizardPrimaryAction',
  'canOpenImportWizardNextActions',
  'openImportWizardNextAction',
]) {
  if (!source.includes(token)) {
    fail(`Projects import wizard must define ${token}`)
  }
}

const footerMatch = source.match(/<template #footer>\s*<ElButton @click="validationDialogVisible = false">[\s\S]*?<\/template>\s*<\/ElDialog>/)
if (!footerMatch) {
  fail('Projects import validation dialog footer must be found')
}

const footer = footerMatch[0]
if (!footer.includes('@click="runImportWizardPrimaryAction"')) {
  fail('Projects import validation dialog must expose one primary next-step action')
}
if (!footer.includes('{{ importWizardPrimaryLabel }}')) {
  fail('Projects import validation dialog must use the computed primary action label')
}
for (const oldAction of [
  '@click="createImportDraftFromValidation"',
  '@click="confirmImportBatchFromDraft"',
  '@click="createWorkOrderTaskFromBatch"',
  '@click="executeWorkOrderTaskFromPlan"',
]) {
  if (footer.includes(oldAction)) {
    fail(`Projects import validation dialog footer must not expose ${oldAction} directly`)
  }
}
if (!footer.includes('@click="rollbackWorkOrderTaskFromExecution"')) {
  fail('Projects import validation dialog must keep rollback available after execution')
}
if (!footer.includes('v-if="canOpenImportWizardNextActions"')) {
  fail('Projects import validation dialog must show next business actions after platform access')
}
if (!footer.includes("@click=\"openImportWizardNextAction('/construction')\"")) {
  fail('Projects import validation dialog must link to construction collection after platform access')
}
if (!footer.includes("@click=\"openImportWizardNextAction('/task-hall')\"")) {
  fail('Projects import validation dialog must link to review workbench after platform access')
}
if (!footer.includes('去施工采集') || !footer.includes('去审阅工作台')) {
  fail('Projects import validation dialog must use non-technical next-step labels')
}

console.log('[OK] Vue project import dialog uses a single guided primary action.')
