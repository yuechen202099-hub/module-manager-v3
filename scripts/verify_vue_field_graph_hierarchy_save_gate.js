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
  ['type FieldHierarchyReadinessIssue', 'designer must define hierarchy readiness issue type'],
  ['type FieldHierarchyReadinessCard', 'designer must define hierarchy readiness card type'],
  ['const fieldGraphHierarchyReadinessCards', 'designer must compute hierarchy readiness cards'],
  ['function fieldGraphHierarchyIssueList', 'designer must compute hierarchy issues'],
  ['层级完整性', 'designer must label hierarchy readiness'],
  ['换模块完整性', 'designer must show module replacement completeness'],
  ['换终端完整性', 'designer must show terminal replacement completeness'],
  ['可保存', 'designer must show save-ready state'],
  ['需补齐', 'designer must show blocking state'],
  ['换模块需要在任务对象下保留新附属设备和旧设备/回收证据', 'designer must explain module replacement save rule'],
  ['换终端需要主设备更换、旧设备、附属设备确认和条件采集', 'designer must explain terminal replacement save rule'],
  ['class="field-hierarchy-readiness-panel"', 'designer must render hierarchy readiness panel'],
  ['field-hierarchy-readiness-card', 'designer must render hierarchy readiness cards'],
]

for (const [token, message] of designerTokens) {
  if (!designerSource.includes(token)) fail(message)
}

const projectTokens = [
  ['function fieldHierarchySaveIssues', 'projects view must compute save-time hierarchy issues'],
  ['function validateFieldHierarchyBeforeSave', 'projects view must validate hierarchy before save'],
  ['validateFieldHierarchyBeforeSave(createForm)', 'create flow must call hierarchy save gate'],
  ['validateFieldHierarchyBeforeSave(schemaForm)', 'schema save flow must call hierarchy save gate'],
  ['换模块需要在任务对象下保留新附属设备和旧设备/回收证据', 'save gate must explain module replacement rule'],
  ['换终端需要主设备更换、旧设备、附属设备确认和条件采集', 'save gate must explain terminal replacement rule'],
]

for (const [token, message] of projectTokens) {
  if (!projectsSource.includes(token)) fail(message)
}

const createOrderPattern = /if \(!validateFieldForm\(createForm\)\) return[\s\S]*?if \(!validateFieldHierarchyBeforeSave\(createForm\)\) return[\s\S]*?creatingProject\.value = true/
if (!createOrderPattern.test(projectsSource)) {
  fail('create flow must validate hierarchy before creating project draft')
}

const saveOrderPattern = /if \(!validateFieldForm\(schemaForm\)\) return[\s\S]*?if \(!validateFieldHierarchyBeforeSave\(schemaForm\)\) return[\s\S]*?savingSchema\.value = true/
if (!saveOrderPattern.test(projectsSource)) {
  fail('schema save flow must validate hierarchy before saving')
}

console.log('[OK] Vue field graph hierarchy save gate is wired.')
