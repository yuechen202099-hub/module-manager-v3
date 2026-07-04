const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const templatesSource = fs.readFileSync(path.join(root, 'v2-api', 'app', 'services', 'platform', 'templates.py'), 'utf8')
const typesSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'api', 'types.ts'), 'utf8')
const servicesSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'api', 'services.ts'), 'utf8')
const designerSource = fs.readFileSync(
  path.join(root, 'v2-web', 'src', 'components', 'project-fields', 'FieldGraphDesigner.vue'),
  'utf8',
)
const projectsSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const backendTokens = [
  ['template_hierarchy_role', 'backend preview must expose a readable hierarchy role'],
  ['template_parent_label', 'backend preview must expose a readable parent label'],
  ['template_condition_hint', 'backend preview must expose a readable conditional hint'],
  ['_template_hierarchy_role', 'backend must define hierarchy role helper'],
  ['_template_parent_label', 'backend must define parent label helper'],
  ['_template_condition_hint', 'backend must define condition hint helper'],
  ['"parent_key": field.get("parent_key", "")', 'backend preview must preserve parent_key'],
  ['"relation_role": field.get("relation_role", "")', 'backend preview must preserve relation_role'],
  ['"required_when": field.get("required_when") or None', 'backend preview must preserve required_when'],
  ['field.get("parent_key") or field.get("parentKey")', 'backend field cleaner must accept camelCase parentKey'],
  ['field.get("relation_role") or field.get("relationRole")', 'backend field cleaner must accept camelCase relationRole'],
  ['field.get("required_when") or field.get("requiredWhen")', 'backend field cleaner must accept camelCase requiredWhen'],
  ['"层级角色"', 'downloaded workbook fields sheet must include hierarchy role column'],
  ['"父字段"', 'downloaded workbook fields sheet must include parent column'],
  ['"条件采集"', 'downloaded workbook fields sheet must include conditional column'],
]

for (const [token, message] of backendTokens) {
  if (!templatesSource.includes(token)) fail(message)
}

const typeTokens = [
  ['parentKey: string', 'frontend type must keep parentKey'],
  ['relationRole: string', 'frontend type must keep relationRole'],
  ['requiredWhen: { fieldKey: string; equals: string | string[] } | null', 'frontend type must keep requiredWhen'],
  ['showInConstructionPanel: boolean', 'frontend type must keep construction visibility'],
  ['templateHierarchyRole: string', 'frontend type must keep hierarchy role hint'],
  ['templateParentLabel: string', 'frontend type must keep parent label hint'],
  ['templateConditionHint: string', 'frontend type must keep conditional hint'],
]

for (const [token, message] of typeTokens) {
  if (!typesSource.includes(token)) fail(message)
}

const serviceTokens = [
  ['parentKey: String(field.parent_key || \'\')', 'service mapper must map parent_key'],
  ['relationRole: String(field.relation_role || \'\')', 'service mapper must map relation_role'],
  ['requiredWhen: mapTemplatePreviewRequiredWhen(field.required_when)', 'service mapper must map required_when'],
  ['showInConstructionPanel: Boolean(field.show_in_construction_panel)', 'service mapper must map construction visibility'],
  ['templateHierarchyRole: String(field.template_hierarchy_role || \'\')', 'service mapper must map hierarchy role'],
  ['templateParentLabel: String(field.template_parent_label || \'\')', 'service mapper must map parent label'],
  ['templateConditionHint: String(field.template_condition_hint || \'\')', 'service mapper must map conditional hint'],
  ['function mapTemplatePreviewRequiredWhen', 'service mapper must define required_when helper'],
]

for (const [token, message] of serviceTokens) {
  if (!servicesSource.includes(token)) fail(message)
}

const designerTokens = [
  ['TemplatePreviewFieldRow', 'designer must define rich template preview field row'],
  ['initialTemplateFieldRows', 'designer must use initial template field rows'],
  ['externalCompletedTemplateFieldRows', 'designer must use external completed field rows'],
  ['templateHierarchyHint', 'designer must render hierarchy hints'],
  ['template-preview-field-list', 'designer must render field metadata list'],
  ['任务核心', 'designer must show task core hierarchy wording'],
  ['附属设备确认', 'designer must show accessory confirmation hierarchy wording'],
  ['条件采集', 'designer must show conditional hierarchy wording'],
]

for (const [token, message] of designerTokens) {
  if (!designerSource.includes(token)) fail(message)
}

const projectTokens = [
  ['initialWorkOrderFields', 'projects view must pass initial template field rows'],
  ['externalCompletedFields', 'projects view must pass external completed field rows'],
]

for (const [token, message] of projectTokens) {
  if (!projectsSource.includes(token)) fail(message)
}

console.log('[OK] Field template hierarchy hints are wired.')
