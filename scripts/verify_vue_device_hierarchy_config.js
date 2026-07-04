const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const projectsView = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue'), 'utf8')
const fieldDesigner = fs.readFileSync(
  path.join(root, 'v2-web', 'src', 'components', 'project-fields', 'FieldGraphDesigner.vue'),
  'utf8',
)
const constructionView = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ConstructionView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

function between(source, startToken, endToken) {
  const start = source.indexOf(startToken)
  if (start === -1) fail(`missing scope start token: ${startToken}`)
  const end = endToken ? source.indexOf(endToken, start + startToken.length) : -1
  return source.slice(start, end === -1 ? undefined : end)
}

function fieldBlock(source, key) {
  const pattern = new RegExp(`\\{\\s*\\n\\s*key: '${key}'`)
  const match = pattern.exec(source)
  if (!match) fail(`missing field block: ${key}`)
  const start = match.index
  let depth = 0
  for (let index = start; index < source.length; index += 1) {
    const char = source[index]
    if (char === '{') depth += 1
    if (char === '}') {
      depth -= 1
      if (depth === 0) return source.slice(start, index + 1)
    }
  }
  fail(`unterminated field block: ${key}`)
}

const projectTokens = [
  "const replacementConfirmOptions = ['更换', '不更换', '待确认']",
  "relationRole?: ProjectFieldDefinition['relationRole']",
  "relationRole: 'task_object'",
  "relationRole: 'task_detail'",
  "relationRole: 'old_device'",
  "key: 'new_terminal_no'",
  "relationRole: 'replacement_device'",
  "relationRole: 'accessory_replace_confirm'",
  "relationRole: 'accessory_new_device'",
  "relationRole: 'evidence_photo'",
  "id: 'module-replacement'",
  "name: '更换模块'",
  "label: '模块（需更换）'",
  "label: '采集器（确认是否更换）'",
  "key: 'communication_module_replace_confirm'",
  "label: '通讯模块是否更换'",
  "key: 'sim_card_replace_confirm'",
  "label: 'SIM卡是否更换'",
  "dataType: 'enum'",
  "captureMethod: 'select'",
  'options: replacementConfirmOptions',
  "label: '新通讯模块号（更换时扫码）'",
  "requiredWhen: { fieldKey: 'communication_module_replace_confirm', equals: '更换' }",
  "label: '新SIM卡号（更换时录入）'",
  "requiredWhen: { fieldKey: 'sim_card_replace_confirm', equals: '更换' }",
  'terminalDeviceHierarchyFieldDefaults',
  'syncTerminalDeviceHierarchyFields',
  'syncTerminalDeviceHierarchyFields(form)',
  'syncTerminalDeviceHierarchyFields(schemaForm)',
]

for (const token of projectTokens) {
  if (!projectsView.includes(token)) fail(`ProjectsView.vue missing device hierarchy token: ${token}`)
}

if (
  !/key: 'new_terminal_no'[\s\S]*?captureMethod: 'scan'[\s\S]*?required: true[\s\S]*?parentKey: 'terminal_no'[\s\S]*?relationRole: 'replacement_device'/.test(projectsView)
) {
  fail('terminal replacement must include a required scanned new terminal device under terminal_no')
}

if (
  !/key: 'old_new_module_photo'[\s\S]*?relationRole: 'evidence_photo'[\s\S]*?requiredWhen: \{ fieldKey: 'communication_module_replace_confirm', equals: '更换' \}/.test(projectsView)
) {
  fail('terminal module comparison photo must depend on communication module replacement confirmation')
}

const hierarchyPatterns = [
  [
    /id: 'module-replacement'[\s\S]*?key: 'old_module_no'[\s\S]*?captureMethod: 'scan'[\s\S]*?parentKey: 'meter_no'[\s\S]*?relationRole: 'old_device'/,
    'module replacement old module must be a recovered device under meter_no',
  ],
  [
    /id: 'module-replacement'[\s\S]*?key: 'collector_replace_confirm'[\s\S]*?dataType: 'enum'[\s\S]*?captureMethod: 'select'[\s\S]*?parentKey: 'meter_no'[\s\S]*?relationRole: 'accessory_replace_confirm'/,
    'module replacement collector must be an accessory replacement confirmation under meter_no',
  ],
  [
    /key: 'old_collector_no'[\s\S]*?captureMethod: 'scan'[\s\S]*?parentKey: 'meter_no'[\s\S]*?relationRole: 'old_device'[\s\S]*?requiredWhen: \{ fieldKey: 'collector_replace_confirm'/,
    'old collector must be conditionally required under collector replacement confirmation',
  ],
  [
    /key: 'collector_no'[\s\S]*?captureMethod: 'scan'[\s\S]*?parentKey: 'meter_no'[\s\S]*?relationRole: 'accessory_new_device'[\s\S]*?requiredWhen: \{ fieldKey: 'collector_replace_confirm'/,
    'new collector must be conditionally required under collector replacement confirmation',
  ],
  [
    /key: 'communication_module_replace_confirm'[\s\S]*?dataType: 'enum'[\s\S]*?captureMethod: 'select'[\s\S]*?parentKey: 'terminal_no'[\s\S]*?relationRole: 'accessory_replace_confirm'/,
    'terminal communication module must be an accessory replacement confirmation under terminal_no',
  ],
  [
    /key: 'old_communication_module_no'[\s\S]*?captureMethod: 'scan'[\s\S]*?parentKey: 'terminal_no'[\s\S]*?relationRole: 'old_device'[\s\S]*?requiredWhen: \{ fieldKey: 'communication_module_replace_confirm'/,
    'old communication module must be conditionally required under communication module confirmation',
  ],
  [
    /key: 'communication_module_no'[\s\S]*?captureMethod: 'scan'[\s\S]*?parentKey: 'terminal_no'[\s\S]*?relationRole: 'accessory_new_device'[\s\S]*?requiredWhen: \{ fieldKey: 'communication_module_replace_confirm'/,
    'new communication module must be conditionally required under communication module confirmation',
  ],
  [
    /key: 'sim_card_replace_confirm'[\s\S]*?dataType: 'enum'[\s\S]*?captureMethod: 'select'[\s\S]*?parentKey: 'terminal_no'[\s\S]*?relationRole: 'accessory_replace_confirm'/,
    'terminal SIM card must be an accessory replacement confirmation under terminal_no',
  ],
  [
    /key: 'old_sim_card_no'[\s\S]*?parentKey: 'terminal_no'[\s\S]*?relationRole: 'old_device'[\s\S]*?requiredWhen: \{ fieldKey: 'sim_card_replace_confirm'/,
    'old SIM card must be conditionally required under SIM replacement confirmation',
  ],
  [
    /key: 'new_sim_card_no'[\s\S]*?parentKey: 'terminal_no'[\s\S]*?relationRole: 'accessory_new_device'[\s\S]*?requiredWhen: \{ fieldKey: 'sim_card_replace_confirm'/,
    'new SIM card must be conditionally required under SIM replacement confirmation',
  ],
]

const modulePreset = between(projectsView, "id: 'module-replacement'", "id: 'terminal-replacement'")
const moduleAssetField = fieldBlock(modulePreset, 'module_asset_no')
for (const [token, message] of [
  ["captureMethod: 'scan'", 'module replacement new module must be scanned'],
  ['required: true', 'module replacement new module must be required'],
  ["parentKey: 'meter_no'", 'module replacement new module must belong to meter_no'],
  ["relationRole: 'accessory_new_device'", 'module replacement new module must be modeled as an accessory device'],
]) {
  if (!moduleAssetField.includes(token)) fail(message)
}

for (const [pattern, message] of hierarchyPatterns) {
  if (!pattern.test(projectsView)) fail(message)
}

const terminalSyncDefaults = projectsView.match(/const terminalDeviceHierarchyFieldDefaults: CreateFieldForm\[\] = \[[\s\S]*?\]\nconst projectTypePresets/)
if (!terminalSyncDefaults) fail('terminal device hierarchy sync defaults must be present')
if (
  !/key: 'old_new_module_photo'[\s\S]*?dataType: 'image'[\s\S]*?requiredWhen: \{ fieldKey: 'communication_module_replace_confirm', equals: '更换' \}/.test(
    terminalSyncDefaults[0],
  )
) {
  fail('terminal existing-schema sync must add conditional old/new module photo')
}

const designerTokens = [
  'roleOptions',
  'relationRoleLabel',
  'requiredWhenSummary',
  'dependsOnFieldKey',
  'device-dependency',
  '字段关系',
  'deviceReplacementRole',
  'deviceRelationClass',
  'deviceRelationConnectorClass',
  'isMainOldDeviceField',
  'isReplacementConfirmationField',
  'isRequiredReplacementField',
  'main-old-device-child',
  'main-old-device-link',
  '主设备 · 更换后',
  '附属设备 · 是否更换',
  '附属设备 · 新设备',
  '附属设备 · 拆回',
  '第三层 · 设备动作/证据',
  'main-replacement-child',
  'accessory-confirm-child',
  'accessory-new-child',
  'old-device-child',
  'conditional-child',
  'main-replacement-link',
  'accessory-confirm-link',
  'conditional-link',
  'fieldOptionsText',
  'updateFieldOptions',
  '字段选项',
  '确认是否更换',
]

for (const token of designerTokens) {
  if (!fieldDesigner.includes(token)) fail(`FieldGraphDesigner.vue missing device hierarchy token: ${token}`)
}

if (
  !/function isMainOldDeviceField\(field: FieldForm\)[\s\S]*?field\.relationRole !== 'old_device'[\s\S]*?field\.requiredWhen\?\.fieldKey[\s\S]*?props\.customFields\.some\(\(item\) => item\.relationRole === 'replacement_device'\)/.test(
    fieldDesigner,
  )
) {
  fail('FieldGraphDesigner.vue must classify old_device as main old device when the schema has a main replacement device')
}

const fieldMetaFunction = between(fieldDesigner, 'function fieldMeta(field: FieldForm) {', 'function requiredWhenSummary')
if (!fieldMetaFunction.includes('isMainOldDeviceField(field)')) {
  fail('field metadata must use the main old device role before falling back to generic old_device labels')
}

if (
  !/function deviceReplacementRole\(field: FieldForm\)[\s\S]*?isMainOldDeviceField\(field\)[\s\S]*?field\.relationRole === 'old_device'/.test(
    fieldDesigner,
  )
) {
  fail('main old device label must be checked before generic old_device label')
}

if (
  !/function deviceRelationClass\(field: FieldForm\)[\s\S]*?isMainOldDeviceField\(field\)[\s\S]*?main-old-device-child/.test(
    fieldDesigner,
  )
) {
  fail('main old device node must have its own visual class')
}

if (
  !/function deviceRelationConnectorClass\(field: FieldForm\)[\s\S]*?isMainOldDeviceField\(field\)[\s\S]*?main-old-device-link/.test(
    fieldDesigner,
  )
) {
  fail('main old device connector must have its own visual class')
}

const constructionTokens = [
  'shouldUseFieldSelect',
  'fieldSelectOptions',
  '<el-select',
  '<el-option',
  'field.captureMethod === \'select\'',
  "field.dataType === 'enum'",
]

for (const token of constructionTokens) {
  if (!constructionView.includes(token)) fail(`ConstructionView.vue missing select collection token: ${token}`)
}

console.log('[OK] Vue device hierarchy configuration is represented.')
