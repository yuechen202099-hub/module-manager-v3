const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const projectsViewPath = path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue')
const designerPath = path.join(root, 'v2-web', 'src', 'components', 'project-fields', 'FieldGraphDesigner.vue')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

if (!fs.existsSync(designerPath)) fail('FieldGraphDesigner.vue must exist')
if (!fs.existsSync(projectsViewPath)) fail('ProjectsView.vue must exist')

const designerSource = fs.readFileSync(designerPath, 'utf8')
const projectsSource = fs.readFileSync(projectsViewPath, 'utf8')

const designerTokens = [
  'template-action',
  'TemplateActionPayload',
  "action: 'download' | 'validate'",
  "templateType: 'initial_work_orders' | 'external_completed'",
  "emit('template-action'",
  '下载初始接入模板',
  '校验初始接入模板',
  '下载系统外已完成模板',
  '校验系统外已完成模板',
  '施工端必采',
  '现场采集入口',
  '安装人员',
  '安装时间',
  '在线时间',
  '照片数量',
  '旧设备回收',
  'site-checklist-panel',
  'platformKpiChecklistFields',
  'platformChecklistFields',
  '...siteRequiredFields.value',
  '...platformChecklistFields.value',
]

for (const token of designerTokens) {
  if (!designerSource.includes(token)) fail(`FieldGraphDesigner.vue missing template-action token: ${token}`)
}

const projectTokens = [
  'handleSchemaTemplateAction',
  '@template-action="handleSchemaTemplateAction"',
  'schemaProject.value',
  "payload.action === 'validate'",
  'requestTemplateValidation(project, payload.templateType)',
  'downloadTemplate(project, payload.templateType)',
]

for (const token of projectTokens) {
  if (!projectsSource.includes(token)) fail(`ProjectsView.vue missing template-action token: ${token}`)
}

console.log('[OK] Field graph template actions are wired.')
