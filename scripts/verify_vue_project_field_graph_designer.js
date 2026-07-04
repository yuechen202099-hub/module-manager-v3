const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const projectsViewPath = path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue')
const designerPath = path.join(root, 'v2-web', 'src', 'components', 'project-fields', 'FieldGraphDesigner.vue')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

if (!fs.existsSync(designerPath)) {
  fail('FieldGraphDesigner.vue must exist under project-fields components')
}

const projectsSource = fs.readFileSync(projectsViewPath, 'utf8')
const designerSource = fs.readFileSync(designerPath, 'utf8')

const requiredProjectTokens = [
  'FieldGraphDesigner',
  '@/components/project-fields/FieldGraphDesigner.vue',
  'aggregateFieldPresetOptions',
  'terminalAggregateFieldPresetOptions',
  ':disabled="preset.group === \'aggregate\' && createForm.primaryField.key === preset.key"',
  ':disabled="preset.group === \'aggregate\' && schemaForm.primaryField.key === preset.key"',
  ':primary-field="schemaForm.primaryField"',
  ':aggregate-field="schemaForm.aggregateField"',
  ':custom-fields="schemaForm.customFields"',
  ':primary-field="createForm.primaryField"',
  ':aggregate-field="createForm.aggregateField"',
  ':custom-fields="createForm.customFields"',
  '@update-parent="handleSchemaFieldParentUpdate"',
  '@update-field="handleSchemaFieldUpdate"',
  '@update-parent="handleCreateFieldParentUpdate"',
  '@update-field="handleCreateFieldUpdate"',
  'handleSchemaFieldUpdate',
  'handleCreateFieldUpdate',
  'buildWorkItemSchemaPayload(schemaForm)',
  'previewProjectTemplateFields',
  'schemaTemplateBindingPreview',
  ':template-preview="schemaTemplateBindingPreview"',
  'createTemplateBindingPreview',
  ':template-preview="createTemplateBindingPreview"',
  '@template-action="handleCreateTemplateAction"',
]

for (const token of requiredProjectTokens) {
  if (!projectsSource.includes(token)) fail(`ProjectsView.vue missing field graph token: ${token}`)
}

const requiredDesignerTokens = [
  'defineProps',
  'defineEmits',
  'field-mind-map',
  'field-map-connector',
  'field-map-layer aggregate-layer',
  'field-map-layer core-layer',
  'field-map-layer device-layer',
  'mindMapCoreItems',
  'mindMapDeviceItems',
  'mindMapConnectors',
  'viewBox="0 0 1000 300"',
  ':d="connector.d"',
  'core-parallel',
  'device-child',
  '字段关系图',
  '聚合字段',
  '主字段',
  '导入字段',
  '现场采集',
  '照片证据',
  '平台必备',
  'draggable',
  'dragstart',
  'dragover',
  'drop',
  'update-parent',
  'update-field',
  'selectedField',
  'selectedFieldDetail',
  '字段详情',
  '字段名称',
  '字段编码',
  '字段来源',
  '采集方式',
  '字段格式',
  '是否必填',
  '模板绑定预览',
  '初始接入模板',
  '系统外已完成模板',
  '现场必采清单',
  '下载模板',
  'initialTemplateFields',
  'externalCompletedTemplateFields',
  'siteRequiredFields',
  'templatePreview?: TemplateBindingPreview',
  'ElSelect',
  'ElSwitch',
  'parentKey',
  'fieldRoleBuckets',
  '字段角色分组',
  '可拖拽子字段',
  'field-drop-zone',
  '拖到聚合字段下',
  '拖到主字段下',
  'selectedParentLabel',
  '层级归属',
  'isSelected',
  'selected',
]

for (const token of requiredDesignerTokens) {
  if (!designerSource.includes(token)) fail(`FieldGraphDesigner.vue missing token: ${token}`)
}

console.log('[OK] Vue project field graph designer is wired.')
