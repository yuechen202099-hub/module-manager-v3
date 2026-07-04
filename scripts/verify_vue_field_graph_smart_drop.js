const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const designerPath = path.join(root, 'v2-web', 'src', 'components', 'project-fields', 'FieldGraphDesigner.vue')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

if (!fs.existsSync(designerPath)) {
  fail('FieldGraphDesigner.vue must exist')
}

const source = fs.readFileSync(designerPath, 'utf8')

const requiredTokens = [
  'type FieldDropIntent',
  'function fieldDropIntentForTarget',
  'function fieldDropIntentForDeviceNode',
  'function deviceNodeTriggerFieldKey',
  'function inferredRelationRoleForDrop',
  'function conditionalRuleForDrop',
  'selectedCustomFieldIndex',
  'selectedCustomFieldForSmartDrop',
  'type DeviceHierarchyGuideItem',
  'deviceHierarchyGuideItems',
  'function smartDropFieldIndexFromSelection',
  'function applySmartDropUpdates',
  'function onSmartDropField',
  'function onSmartDropDeviceNode',
  'function onSmartDropTargetClick',
  "fieldDropIntentForTarget('core'",
  "fieldDropIntentForTarget('device'",
  "@drop=\"onSmartDropField('task-core'",
  "@drop=\"onSmartDropField('main-device'",
  "@drop=\"onSmartDropField('accessory-confirm'",
  "@drop=\"onSmartDropField('conditional-accessory'",
  "@click=\"onSmartDropTargetClick('task-core'",
  "@click=\"onSmartDropTargetClick('main-device'",
  "@click=\"onSmartDropTargetClick('accessory-confirm'",
  "@click=\"onSmartDropTargetClick('conditional-accessory'",
  "@keydown.enter.prevent=\"onSmartDropTargetClick('task-core'",
  "@keydown.space.prevent=\"onSmartDropTargetClick('task-core'",
  '@drop="onSmartDropDeviceNode(customFields[item.selectIndex], $event)"',
  "relationRole: inferredRelationRoleForDrop(intent, field)",
  "requiredWhen: conditionalRuleForDrop(intent, parentKey, triggerFieldKey)",
  "options: replacementConfirmOptionsForDrop(field)",
  "fieldDropIntentForDeviceNode(targetField, field)",
  "deviceNodeTriggerFieldKey(targetField)",
  "targetField.relationRole === 'replacement_device'",
  "if (isEvidenceField(field)) return 'evidence_photo'",
  '选中字段后点击应用',
  '先选择字段，再点击落点应用',
  'field-device-hierarchy-guide',
  'tap-enabled',
  'tap-disabled',
  '拖到任务核心',
  '拖到主设备更换',
  '拖到附属设备确认',
  '拖到条件采集',
  '换模块：任务对象 -> 附属设备更换',
  '换终端：任务对象 -> 主设备更换 -> 附属设备确认',
  '换模块：在任务对象下更换附属设备',
  '换终端：先确认附属设备是否更换',
]

for (const token of requiredTokens) {
  if (!source.includes(token)) {
    fail(`FieldGraphDesigner.vue missing smart drop token: ${token}`)
  }
}

const roleInferencePattern =
  /function inferredRelationRoleForDrop[\s\S]*?case 'main-device':[\s\S]*?return 'replacement_device'[\s\S]*?case 'accessory-confirm':[\s\S]*?return 'accessory_replace_confirm'[\s\S]*?case 'conditional-accessory':[\s\S]*?return isRecoveredDeviceField\(field\) \? 'old_device' : 'accessory_new_device'/
if (!roleInferencePattern.test(source)) {
  fail('smart drop must infer main device, accessory confirmation, and conditional accessory roles')
}

const deviceNodeDropPattern =
  /function fieldDropIntentForDeviceNode[\s\S]*?targetField\.relationRole === 'replacement_device'[\s\S]*?return 'accessory-confirm'[\s\S]*?accessory_replace_confirm[\s\S]*?return 'conditional-accessory'/
if (!deviceNodeDropPattern.test(source)) {
  fail('device-node drops must preserve hierarchy: main device creates accessory confirmation, accessory confirmation creates conditional child fields')
}

const deviceNodeHandlerPattern =
  /function onSmartDropDeviceNode[\s\S]*?draggedFieldIndexFromEvent[\s\S]*?fieldDropIntentForDeviceNode\(targetField, field\)[\s\S]*?deviceNodeTriggerFieldKey\(targetField\)[\s\S]*?applySmartDropUpdates/
if (!deviceNodeHandlerPattern.test(source)) {
  fail('device-node drop handler must compute intent and required_when from the target device node')
}

const updatePayloadPattern =
  /emit\('update-field', \{[\s\S]*?type: 'custom'[\s\S]*?fieldIndex[\s\S]*?updates/
if (!updatePayloadPattern.test(source)) {
  fail('smart drop must update custom field payloads, not only parent links')
}

console.log('[OK] Vue field graph smart drop is wired.')
