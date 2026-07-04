const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const designerPath = path.join(root, 'v2-web', 'src', 'components', 'project-fields', 'FieldGraphDesigner.vue')
const projectsPath = path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const designerSource = fs.readFileSync(designerPath, 'utf8')
const projectsSource = fs.readFileSync(projectsPath, 'utf8')

const designerTokens = [
  ['function aggregateGuardIssueList', 'designer must compute aggregate guard issues'],
  ['const aggregateGuardReadinessCards', 'designer must expose aggregate readiness cards'],
  ['selectedRelationRoleOptions', 'designer must filter relation role options by selected field type'],
  ['option.value !== \'aggregate\'', 'custom fields must not offer aggregate as a relation role option'],
  ['single-active-aggregate', 'designer must render the one-active-aggregate readiness item'],
  ['extra-custom-aggregate', 'designer must flag custom fields marked as aggregate'],
]

for (const [token, message] of designerTokens) {
  if (!designerSource.includes(token)) fail(message)
}

const projectTokens = [
  ['function aggregateFieldSaveIssues', 'projects view must compute aggregate save issues'],
  ['...aggregateFieldSaveIssues(form)', 'hierarchy save issues must include aggregate save issues'],
  ['Only one aggregate field is allowed', 'save guard must keep backend aggregate rule wording traceable'],
  ['validateFieldHierarchyBeforeSave(createForm)', 'create flow must call the combined aggregate and hierarchy save guard'],
  ['validateFieldHierarchyBeforeSave(schemaForm)', 'schema save flow must call the combined aggregate and hierarchy save guard'],
]

for (const [token, message] of projectTokens) {
  if (!projectsSource.includes(token)) fail(message)
}

const createOrderPattern = /if \(!validateFieldForm\(createForm\)\) return[\s\S]*?if \(!validateFieldHierarchyBeforeSave\(createForm\)\) return[\s\S]*?creatingProject\.value = true/
if (!createOrderPattern.test(projectsSource)) {
  fail('create flow must validate aggregate and hierarchy before creating project draft')
}

const saveOrderPattern = /if \(!validateFieldForm\(schemaForm\)\) return[\s\S]*?if \(!validateFieldHierarchyBeforeSave\(schemaForm\)\) return[\s\S]*?savingSchema\.value = true/
if (!saveOrderPattern.test(projectsSource)) {
  fail('schema save flow must validate aggregate and hierarchy before saving')
}

console.log('[OK] Vue field graph aggregate guard is wired.')
