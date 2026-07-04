<script setup lang="ts">
import { computed, ref } from 'vue'

type FieldSource = 'import' | 'field_collection' | 'review' | 'system'
type CaptureMethod = 'manual' | 'scan' | 'photo' | 'select' | 'datetime' | 'location' | 'system' | 'none'
type DataType = 'text' | 'number' | 'datetime' | 'image' | 'enum' | 'duration' | 'location' | 'boolean'
type FieldRequiredWhen = {
  fieldKey: string
  equals: string | string[]
}

type FieldForm = {
  key: string
  label: string
  dataType: DataType
  source: FieldSource
  captureMethod: CaptureMethod
  required: boolean
  parentKey?: string
  kpiEnabled: boolean
  showInConstructionPanel?: boolean
  options?: string[]
  requiredWhen?: FieldRequiredWhen
  relationRole?:
    | 'aggregate'
    | 'task_object'
    | 'task_detail'
    | 'replacement_device'
    | 'old_device'
    | 'accessory_replace_confirm'
    | 'accessory_new_device'
    | 'evidence_photo'
    | 'supporting_field'
}

type FieldGraphItem = {
  field: FieldForm
  index: number
  role: string
}

type FieldRoleBucket = {
  id: string
  label: string
  helper: string
  items: FieldGraphItem[]
}

type MindMapItem = {
  key: string
  label: string
  meta: string
  role: string
  className: string
  connectorClassName?: string
  selectType: FieldSelectionType
  selectIndex: number
  dependsOnFieldKey?: string
}

type MindMapConnector = {
  id: string
  d: string
  className: string
  label: string
  labelX: number
  labelY: number
  labelClassName?: string
}

type FieldSelectionType = 'aggregate' | 'primary' | 'custom' | 'platform'
type FieldDropIntent =
  | 'aggregate'
  | 'task-core'
  | 'main-device'
  | 'accessory-confirm'
  | 'conditional-accessory'
  | 'evidence-photo'
type FieldDropTarget = 'aggregate' | 'core' | 'device'

type DeviceHierarchyGuideItem = {
  title: string
  relation: string
  note: string
}

type ReplacementHierarchyModeId =
  | 'no_device_replacement_fields'
  | 'accessory_under_task_object'
  | 'main_device_with_accessory_confirmation'

type ReplacementHierarchyModeCard = {
  id: string
  title: string
  description: string
  value: string
  className: string
}

type ReplacementHierarchyTemplateId = 'module-replacement' | 'terminal-replacement'

type ReplacementHierarchyTemplateCard = {
  id: ReplacementHierarchyTemplateId
  title: string
  mode: string
  helper: string
  className: string
}

type ReplacementHierarchyTemplatePayload = {
  templateId: ReplacementHierarchyTemplateId
}

type FieldHierarchyReadinessIssue = {
  id: string
  mode: 'aggregate' | 'module' | 'terminal'
  message: string
}

type FieldHierarchyReadinessCard = {
  id: string
  title: string
  value: '可保存' | '需补齐'
  note: string
  issueCount: number
  className: string
}

type BackendDeviceHierarchyReadinessCheck = {
  id: string
  status: 'passed' | 'failed' | string
  action?: string
  evidence?: Record<string, unknown>
}

type BackendDeviceHierarchyIssue = {
  id: string
  label: string
  helper: string
  keys: string[]
  className: string
}

type FieldUpdatePayload = {
  type: Exclude<FieldSelectionType, 'platform'>
  fieldIndex?: number
  updates: Partial<FieldForm>
}

type TemplatePreviewFieldRow = {
  key: string
  label: string
  source: string
  captureMethod: string
  dataType: string
  required: boolean
  parentKey: string
  relationRole: string
  requiredWhen: FieldRequiredWhen | null
  showInConstructionPanel: boolean
  templateHierarchyRole: string
  templateParentLabel: string
  templateConditionHint: string
  platformFillRule: string
}

type TemplateBindingPreview = {
  initialWorkOrders: string[]
  externalCompleted: string[]
  siteRequiredFields: string[]
  initialWorkOrderFields?: TemplatePreviewFieldRow[]
  externalCompletedFields?: TemplatePreviewFieldRow[]
}

type PlatformGeneratedTemplateRow = {
  key: string
  label: string
  helper: string
}

type TemplateImpactSummaryCard = {
  id: string
  title: string
  value: string
  helper: string
  className: string
}

type TemplateDownloadGuideCard = {
  id: string
  title: string
  value: string
  helper: string
  note: string
  className: string
}

type TemplateActionPayload = {
  action: 'download' | 'validate'
  templateType: 'initial_work_orders' | 'external_completed'
}

type DashboardMetricForm = {
  key: string
  label: string
  source?: string
  scope?: string
}

type DashboardMetricPresetCard = {
  id: string
  title: string
  helper: string
  scope: string
  metrics: DashboardMetricForm[]
}

const props = defineProps<{
  primaryField: FieldForm
  aggregateField: FieldForm
  customFields: FieldForm[]
  platformRequiredFields?: FieldForm[]
  dashboardMetrics?: DashboardMetricForm[]
  templatePreview?: TemplateBindingPreview | null
  backendReadinessCheck?: BackendDeviceHierarchyReadinessCheck | null
  editable: boolean
}>()

const emit = defineEmits<{
  (event: 'update-parent', payload: { fieldIndex: number; parentKey: string }): void
  (event: 'update-field', payload: FieldUpdatePayload): void
  (event: 'template-action', payload: TemplateActionPayload): void
  (event: 'update-dashboard-metrics', payload: DashboardMetricForm[]): void
  (event: 'apply-replacement-template', payload: ReplacementHierarchyTemplatePayload): void
}>()

const selectedField = ref<{ type: FieldSelectionType; index: number } | null>(null)
const draggingFieldIndex = ref<number | null>(null)

const sourceOptions: Array<{ value: FieldSource; label: string }> = [
  { value: 'import', label: '初始导入' },
  { value: 'field_collection', label: '现场采集' },
  { value: 'review', label: '审阅补录' },
  { value: 'system', label: '系统生成' },
]

const captureMethodOptions: Array<{ value: CaptureMethod; label: string }> = [
  { value: 'manual', label: '录入' },
  { value: 'scan', label: '扫码' },
  { value: 'photo', label: '拍照' },
  { value: 'select', label: '选择' },
  { value: 'datetime', label: '时间' },
  { value: 'location', label: '定位' },
  { value: 'system', label: '系统' },
  { value: 'none', label: '无采集' },
]

const dataTypeOptions: Array<{ value: DataType; label: string }> = [
  { value: 'text', label: '文本' },
  { value: 'number', label: '数字' },
  { value: 'datetime', label: '时间' },
  { value: 'image', label: '图片' },
  { value: 'enum', label: '选项' },
  { value: 'duration', label: '时长' },
  { value: 'location', label: '位置' },
  { value: 'boolean', label: '是/否' },
]

const roleOptions: Array<{ value: NonNullable<FieldForm['relationRole']>; label: string }> = [
  { value: 'aggregate', label: '聚合口径' },
  { value: 'task_object', label: '任务对象' },
  { value: 'task_detail', label: '任务详情' },
  { value: 'replacement_device', label: '主设备 · 更换后' },
  { value: 'old_device', label: '旧设备 · 拆回/更换前' },
  { value: 'accessory_replace_confirm', label: '附属设备 · 是否更换' },
  { value: 'accessory_new_device', label: '附属设备 · 新设备' },
  { value: 'evidence_photo', label: '照片证据' },
  { value: 'supporting_field', label: '辅助字段' },
]

const replacementHierarchyTemplateCards: ReplacementHierarchyTemplateCard[] = [
  {
    id: 'module-replacement',
    title: '换模块层级',
    mode: '任务对象下更换附属设备',
    helper: '电能表作为任务对象，旧模块、新模块、采集器确认和照片都挂在同一个任务对象下。',
    className: 'template-module',
  },
  {
    id: 'terminal-replacement',
    title: '换终端层级',
    mode: '主设备更换后确认附属设备',
    helper: '终端作为任务对象，先记录旧终端和新终端，再确认通讯模块、SIM 卡是否更换。',
    className: 'template-terminal',
  },
]

const dashboardMetricPresetCards: DashboardMetricPresetCard[] = [
  {
    id: 'project_progress',
    title: '项目进度',
    helper: '看总量、完成量和推进速度',
    scope: 'progress',
    metrics: [
      { key: 'total_work_orders', label: '工单总数', source: 'project_schema', scope: 'progress' },
      { key: 'completed_work_orders', label: '已完成工单', source: 'project_schema', scope: 'progress' },
    ],
  },
  {
    id: 'delivery_capability',
    title: '交付能力',
    helper: '看完工能力和交付周期',
    scope: 'delivery',
    metrics: [
      { key: 'completed_work_orders', label: '已完成工单', source: 'project_schema', scope: 'delivery' },
      { key: 'average_completion_duration', label: '平均完工时长', source: 'project_schema', scope: 'delivery' },
    ],
  },
  {
    id: 'field_collection',
    title: '现场采集',
    helper: '看施工同步和采集覆盖',
    scope: 'field_collection',
    metrics: [
      { key: 'collected_work_orders', label: '已采集工单', source: 'project_schema', scope: 'field_collection' },
    ],
  },
  {
    id: 'review_quality',
    title: '审阅质量',
    helper: '看异常、返工和资料质量',
    scope: 'review',
    metrics: [
      { key: 'exception_work_orders', label: '异常工单', source: 'project_schema', scope: 'review' },
    ],
  },
  {
    id: 'kpi_efficiency',
    title: 'KPI 效率',
    helper: '看在线时长和施工效率',
    scope: 'kpi',
    metrics: [
      { key: 'average_online_duration', label: '平均在线时长', source: 'project_schema', scope: 'kpi' },
      { key: 'average_completion_duration', label: '平均完工时长', source: 'project_schema', scope: 'kpi' },
    ],
  },
]

const aggregateKey = computed(() => props.aggregateField.key || 'aggregate')
const primaryKey = computed(() => props.primaryField.key || 'primary')
const selectedDashboardMetricKeys = computed(() =>
  new Set((props.dashboardMetrics || []).map((metric) => metric.key).filter(Boolean)),
)

const customItems = computed<FieldGraphItem[]>(() =>
  props.customFields.map((field, index) => ({
    field,
    index,
    role: fieldRole(field),
  })),
)

const aggregateChildren = computed(() =>
  customItems.value.filter((item) => (item.field.parentKey || primaryKey.value) === aggregateKey.value),
)

const primaryChildren = computed(() =>
  customItems.value.filter((item) => (item.field.parentKey || primaryKey.value) !== aggregateKey.value),
)

const terminalAggregateCandidateKeys = new Set(['area_no', 'station_area', 'region_name', 'manufacturer_name'])
const mindMapCoreItems = computed<MindMapItem[]>(() => [
  {
    key: primaryKey.value,
    label: fieldTitle(props.primaryField, '任务对象'),
    meta: `${fieldMeta(props.primaryField)} / ${constructionPanelLabel(props.primaryField)}`,
    role: '任务对象',
    className: 'core-parallel',
    selectType: 'primary',
    selectIndex: -1,
  },
  ...customItems.value
    .filter((item) => isCoreField(item.field))
    .map((item) => ({
      key: item.field.key || `core-${item.index}`,
      label: fieldTitle(item.field, `核心字段${item.index + 1}`),
      meta: `${fieldMeta(item.field)} / ${constructionPanelLabel(item.field)}`,
      role: '核心字段',
      className: 'core-parallel',
      selectType: 'custom' as FieldSelectionType,
      selectIndex: item.index,
    })),
])
const mindMapDeviceItems = computed<MindMapItem[]>(() =>
  customItems.value
    .filter((item) => !isCoreField(item.field))
    .map((item) => ({
      key: item.field.key || `device-${item.index}`,
      label: fieldTitle(item.field, `附属字段${item.index + 1}`),
      meta: `${fieldRole(item.field)} / ${fieldMeta(item.field)} / ${constructionPanelLabel(item.field)}${requiredWhenSummary(item.field)}`,
      role: isEvidenceField(item.field) ? '照片证据' : deviceReplacementRole(item.field),
      className: deviceRelationClass(item.field),
      connectorClassName: deviceRelationConnectorClass(item.field),
      selectType: 'custom' as FieldSelectionType,
      selectIndex: item.index,
      dependsOnFieldKey: item.field.requiredWhen?.fieldKey,
    })),
)
const mindMapConnectors = computed<MindMapConnector[]>(() => {
  const connectors: MindMapConnector[] = []
  const coreCount = Math.max(mindMapCoreItems.value.length, 1)
  const deviceCount = Math.max(mindMapDeviceItems.value.length, 1)
  for (let index = 0; index < mindMapCoreItems.value.length; index += 1) {
    const y = layerNodeY(index, coreCount)
    connectors.push({
      id: `aggregate-core-${mindMapCoreItems.value[index].key}`,
      d: `M 240 150 C 330 150, 350 ${y}, 425 ${y}`,
      className: 'aggregate-to-core',
      label: index === 0 ? '聚合分组' : '平行核心字段',
      labelX: 330,
      labelY: Math.round((150 + y) / 2) - 5,
      labelClassName: 'connector-label-core-parallel',
    })
  }
  const primaryY = layerNodeY(0, coreCount)
  for (let index = 0; index < mindMapDeviceItems.value.length; index += 1) {
    const y = layerNodeY(index, deviceCount)
    const item = mindMapDeviceItems.value[index]
    connectors.push({
      id: `core-device-${item.key}`,
      d: `M 610 ${primaryY} C 690 ${primaryY}, 690 ${y}, 760 ${y}`,
      className: `core-to-device ${item.connectorClassName || ''}`.trim(),
      label: parentConnectorLabel(item),
      labelX: 675,
      labelY: Math.round((primaryY + y) / 2) - 5,
      labelClassName: item.connectorClassName || 'connector-label-task-device',
    })
  }
  const deviceYByKey = new Map(mindMapDeviceItems.value.map((item, index) => [item.key, layerNodeY(index, deviceCount)]))
  for (const item of mindMapDeviceItems.value) {
    if (!item.dependsOnFieldKey || !deviceYByKey.has(item.dependsOnFieldKey)) continue
    const fromY = deviceYByKey.get(item.dependsOnFieldKey) || 150
    const toY = deviceYByKey.get(item.key) || 150
    connectors.push({
      id: `device-dependency-${item.dependsOnFieldKey}-${item.key}`,
      d: `M 910 ${fromY} C 970 ${fromY}, 970 ${toY}, 910 ${toY}`,
      className: `device-dependency conditional-link ${item.connectorClassName || ''}`.trim(),
      label: '条件触发',
      labelX: 950,
      labelY: Math.round((fromY + toY) / 2) - 5,
      labelClassName: 'conditional-link-label',
    })
  }
  return connectors
})

const mindMapConnectorLegend = [
  { label: '平行核心字段', className: 'legend-core-parallel' },
  { label: '隶属任务对象', className: 'legend-task-device' },
  { label: '条件触发', className: 'legend-conditional' },
]

const deviceRelationshipSummaryItems = computed(() => {
  const deviceFields = customItems.value.filter((item) => !isCoreField(item.field))
  const mainReplacementCount = deviceFields.filter((item) => item.field.relationRole === 'replacement_device' || isMainOldDeviceField(item.field)).length
  const accessoryConfirmCount = deviceFields.filter((item) => item.field.relationRole === 'accessory_replace_confirm').length
  const conditionalCount = deviceFields.filter((item) => item.field.requiredWhen?.fieldKey).length
  const corePeerCount = Math.max(mindMapCoreItems.value.length - 1, 0)
  return [
    { label: '任务核心同级', value: `${corePeerCount} 个`, className: 'summary-core-peer' },
    { label: '主设备更换', value: `${mainReplacementCount} 个`, className: 'summary-main-device' },
    { label: '附属设备确认', value: `${accessoryConfirmCount} 个`, className: 'summary-accessory-confirm' },
    { label: '条件采集', value: `${conditionalCount} 条`, className: 'summary-conditional' },
  ]
})
const replacementHierarchyModeCards = computed<ReplacementHierarchyModeCard[]>(() => {
  const fields = props.customFields
  const mode = deviceReplacementHierarchyMode(fields)
  const mainReplacementCount = fields.filter((field) => field.relationRole === 'replacement_device').length
  const accessoryConfirmCount = fields.filter((field) => field.relationRole === 'accessory_replace_confirm').length
  const directAccessoryCount = fields.filter((field) => field.relationRole === 'accessory_new_device' && !field.requiredWhen?.fieldKey).length
  const conditionalAccessoryCount = fields.filter((field) => field.requiredWhen?.fieldKey).length
  const modeCopy: Record<ReplacementHierarchyModeId, ReplacementHierarchyModeCard> = {
    no_device_replacement_fields: {
      id: 'no_device_replacement_fields',
      title: '无设备更换层级',
      description: '当前项目还没有配置主设备或附属设备更换字段。',
      value: '未配置',
      className: 'replacement-mode-empty',
    },
    accessory_under_task_object: {
      id: 'accessory_under_task_object',
      title: '任务对象下更换附属设备',
      description: '适合换模块：任务对象保持不变，模块、采集器等作为附属设备挂在任务对象下。',
      value: `${directAccessoryCount} 个直连附属设备`,
      className: 'replacement-mode-accessory',
    },
    main_device_with_accessory_confirmation: {
      id: 'main_device_with_accessory_confirmation',
      title: '主设备更换后确认附属设备',
      description: '适合换终端：先记录旧主设备和新主设备，再确认通讯模块、SIM 卡等附属设备是否更换。',
      value: `${mainReplacementCount} 个主设备`,
      className: 'replacement-mode-main',
    },
  }
  return [
    modeCopy[mode],
    {
      id: 'accessory_confirmation',
      title: '附属设备确认',
      description: '用于决定旧件、新件、照片是否需要现场补采。',
      value: `${accessoryConfirmCount} 个确认项`,
      className: 'replacement-mode-confirm',
    },
    {
      id: 'conditional_accessory',
      title: '条件采集',
      description: '只有确认“更换”后才出现的旧设备、新设备或照片。',
      value: `${conditionalAccessoryCount} 条条件规则`,
      className: 'replacement-mode-conditional',
    },
  ]
})
const aggregateGuardReadinessCards = computed<FieldHierarchyReadinessCard[]>(() => {
  const issues = aggregateGuardIssueList(props.primaryField, props.aggregateField, props.customFields)
  return [
    {
      id: 'single-active-aggregate',
      title: '聚合口径',
      value: issues.length ? '需补齐' : '可保存',
      note: issues[0]?.message || '同一项目只能选择台区、地区或厂家中的一种作为聚合字段，其余导入字段放在任务核心字段。',
      issueCount: issues.length,
      className: issues.length ? 'hierarchy-readiness-blocked' : 'hierarchy-readiness-ready',
    },
  ]
})
const fieldGraphHierarchyReadinessCards = computed<FieldHierarchyReadinessCard[]>(() => {
  const aggregateIssues = aggregateGuardIssueList(props.primaryField, props.aggregateField, props.customFields)
  const hierarchyIssues = fieldGraphHierarchyIssueList(props.customFields)
  const issues = [...aggregateIssues, ...hierarchyIssues]
  const moduleIssues = issues.filter((issue) => issue.mode === 'module')
  const terminalIssues = issues.filter((issue) => issue.mode === 'terminal')
  return [
    ...aggregateGuardReadinessCards.value,
    {
      id: 'overall',
      title: '层级完整性',
      value: issues.length ? '需补齐' : '可保存',
      note: issues[0]?.message || '字段层级可用于模板、施工、审阅和交付归档。',
      issueCount: issues.length,
      className: issues.length ? 'hierarchy-readiness-blocked' : 'hierarchy-readiness-ready',
    },
    {
      id: 'module',
      title: '换模块完整性',
      value: moduleIssues.length ? '需补齐' : '可保存',
      note: moduleIssues[0]?.message || '换模块需要在任务对象下保留新附属设备和旧设备/回收证据。',
      issueCount: moduleIssues.length,
      className: moduleIssues.length ? 'hierarchy-readiness-blocked' : 'hierarchy-readiness-ready',
    },
    {
      id: 'terminal',
      title: '换终端完整性',
      value: terminalIssues.length ? '需补齐' : '可保存',
      note: terminalIssues[0]?.message || '换终端需要主设备更换、旧设备、附属设备确认和条件采集。',
      issueCount: terminalIssues.length,
      className: terminalIssues.length ? 'hierarchy-readiness-blocked' : 'hierarchy-readiness-ready',
    },
  ]
})
const backendDeviceHierarchyIssues = computed(() =>
  backendDeviceHierarchyIssueList(props.backendReadinessCheck),
)
const backendDeviceHierarchyIssueKeys = computed(() =>
  new Set(backendDeviceHierarchyIssues.value.flatMap((issue) => issue.keys)),
)
const backendDeviceHierarchyStatusLabel = computed(() =>
  props.backendReadinessCheck?.status === 'failed' ? '后端需补齐' : '后端已通过',
)
const backendDeviceHierarchyContractNotes = computed(() =>
  backendDeviceHierarchyContractList(props.backendReadinessCheck),
)
const smartDropGuideItems = [
  '换模块：在任务对象下更换附属设备',
  '换终端：先确认附属设备是否更换',
]
const deviceHierarchyGuideItems = computed<DeviceHierarchyGuideItem[]>(() => {
  const taskObject = fieldTitle(props.primaryField, '任务对象')
  return [
    {
      title: 'module-replacement',
      relation: '换模块：任务对象 -> 附属设备更换',
      note: `${taskObject} 保持不变，模块、采集器、旧件回收和照片都挂在同一个任务对象下。`,
    },
    {
      title: 'terminal-replacement',
      relation: '换终端：任务对象 -> 主设备更换 -> 附属设备确认',
      note: `${taskObject} 先记录终端本体更换，再确认通讯模块、SIM 卡等附属设备是否同步更换。`,
    },
  ]
})

const importFields = computed(() => customItems.value.filter((item) => item.field.source === 'import'))
const collectionFields = computed(() =>
  customItems.value.filter((item) => item.field.source === 'field_collection' && item.field.dataType !== 'image'),
)
const photoFields = computed(() =>
  customItems.value.filter((item) => item.field.captureMethod === 'photo' || item.field.dataType === 'image'),
)
const platformKpiChecklistFields = ['安装人员', '安装时间', '在线时间', '照片数量', '旧设备回收']
const platformChecklistFields = computed(() =>
  Array.from(
    new Set([
      ...(props.platformRequiredFields || []).map((field) => fieldTitle(field, '平台必备字段')),
      ...platformKpiChecklistFields,
    ]),
  ).filter(Boolean),
)
const fieldRoleBuckets = computed<FieldRoleBucket[]>(() => [
  {
    id: 'import',
    label: '导入字段',
    helper: '初始建单可以从清单带入',
    items: importFields.value,
  },
  {
    id: 'collection',
    label: '现场采集',
    helper: '施工端扫码、拍照或录入',
    items: collectionFields.value,
  },
  {
    id: 'photo',
    label: '照片证据',
    helper: '审阅需要看到的影像资料',
    items: photoFields.value,
  },
  {
    id: 'platform',
    label: '平台必备',
    helper: '用于 KPI、效率和追溯',
    items: (props.platformRequiredFields || []).map((field, index) => ({
      field,
      index,
      role: '平台必备',
    })),
  },
])
const initialTemplateFields = computed(() =>
  props.templatePreview?.initialWorkOrders?.length
    ? props.templatePreview.initialWorkOrders
    : uniqueFieldLabels([
        props.primaryField,
        props.aggregateField,
        ...importFields.value.map((item) => item.field),
      ]),
)
const externalCompletedTemplateFields = computed(() =>
  props.templatePreview?.externalCompleted?.length
    ? props.templatePreview.externalCompleted
    : uniqueFieldLabels([
        props.primaryField,
        props.aggregateField,
        ...importFields.value.map((item) => item.field),
        ...collectionFields.value.map((item) => item.field),
        ...photoFields.value.map((item) => item.field),
      ]),
)
const localInitialTemplateFieldRows = computed(() =>
  uniqueTemplatePreviewRows([
    templatePreviewRowFromField(props.primaryField),
    templatePreviewRowFromField(props.aggregateField),
    ...importFields.value.map((item) => templatePreviewRowFromField(item.field)),
  ]),
)
const localExternalCompletedTemplateFieldRows = computed(() =>
  uniqueTemplatePreviewRows([
    templatePreviewRowFromField(props.primaryField),
    templatePreviewRowFromField(props.aggregateField),
    ...importFields.value.map((item) => templatePreviewRowFromField(item.field)),
    ...collectionFields.value.map((item) => templatePreviewRowFromField(item.field)),
    ...photoFields.value.map((item) => templatePreviewRowFromField(item.field)),
  ]),
)
const initialTemplateFieldRows = computed(() =>
  props.templatePreview?.initialWorkOrderFields?.length
    ? props.templatePreview.initialWorkOrderFields
    : localInitialTemplateFieldRows.value,
)
const externalCompletedTemplateFieldRows = computed(() =>
  props.templatePreview?.externalCompletedFields?.length
    ? props.templatePreview.externalCompletedFields
    : localExternalCompletedTemplateFieldRows.value,
)
const siteRequiredFields = computed(() =>
  props.templatePreview?.siteRequiredFields?.length
    ? props.templatePreview.siteRequiredFields
    : uniqueFieldLabels(
        customItems.value
          .filter((item) => item.field.required && item.field.source === 'field_collection')
          .map((item) => item.field),
      ),
)
const siteChecklistFields = computed(() =>
  Array.from(new Set([...siteRequiredFields.value, ...platformChecklistFields.value])),
)
const platformGeneratedTemplateRows = computed<PlatformGeneratedTemplateRow[]>(() =>
  platformChecklistFields.value.map((label, index) => ({
    key: `platform-generated-${index}-${label}`,
    label,
    helper: '上传时平台生成，用于 KPI、效率、审阅和追溯。',
  })),
)
const templateImpactSummaryCards = computed<TemplateImpactSummaryCard[]>(() => [
  {
    id: 'initial',
    title: '初始接入',
    value: `${initialTemplateFieldRows.value.length} 列`,
    helper: '只放清单能提前提供的任务对象、聚合字段和导入字段。',
    className: 'impact-initial',
  },
  {
    id: 'external-completed',
    title: '系统外已完成',
    value: `${externalCompletedTemplateFieldRows.value.length} 列`,
    helper: '允许填已完成施工能提供的设备、照片和条件采集资料。',
    className: 'impact-completed',
  },
  {
    id: 'platform-generated',
    title: '平台补齐',
    value: `${platformGeneratedTemplateRows.value.length} 项`,
    helper: '安装人员、上传时间、照片数量等按上传或审阅动作生成。',
    className: 'impact-platform',
  },
])
const templateDownloadHierarchyGuide = computed(() => {
  const mode = deviceReplacementHierarchyMode(props.customFields)
  if (mode === 'accessory_under_task_object') {
    return {
      value: '任务对象下更换附属设备',
      note: '换模块下载前会提示附属设备挂在任务对象下，旧件、新件、采集器和照片都跟随同一任务对象。',
    }
  }
  if (mode === 'main_device_with_accessory_confirmation') {
    return {
      value: '主设备更换后确认附属设备',
      note: '换终端下载前会提示先记录旧主设备和新主设备，再确认通讯模块、SIM卡等附属设备是否更换。',
    }
  }
  return {
    value: '字段层级待配置',
    note: '配置设备更换字段后，Excel说明页会同步标注换模块或换终端的层级关系。',
  }
})
const templateDownloadGuideCards = computed<TemplateDownloadGuideCard[]>(() => [
  {
    id: 'workbook-sheets',
    title: 'Excel说明页',
    value: 'template / fields / instructions',
    helper: 'template 填数据，fields 查字段编码，instructions 看字段层级、父字段、条件采集和平台补齐。',
    note: '下载前先确认三页内容，减少系统外项目接入时的返工。',
    className: 'download-guide-workbook',
  },
  {
    id: 'replacement-hierarchy',
    title: '更换层级说明',
    value: templateDownloadHierarchyGuide.value.value,
    helper: templateDownloadHierarchyGuide.value.note,
    note: '系统外已完成模板会保留这些层级提示，缺失的平台字段按上传时补齐。',
    className: 'download-guide-hierarchy',
  },
])

const selectedFieldDetail = computed(() => {
  if (!selectedField.value) return null
  if (selectedField.value.type === 'aggregate') return props.aggregateField
  if (selectedField.value.type === 'primary') return props.primaryField
  if (selectedField.value.type === 'platform') return props.platformRequiredFields?.[selectedField.value.index]
  return props.customFields[selectedField.value.index]
})

const selectedFieldEditable = computed(() => Boolean(props.editable && selectedField.value && selectedField.value.type !== 'platform'))
const selectedRelationRoleOptions = computed(() => {
  if (selectedField.value?.type === 'aggregate') {
    return roleOptions.filter((option) => option.value === 'aggregate')
  }
  return roleOptions.filter((option) => option.value !== 'aggregate')
})
const selectedCustomFieldIndex = computed(() => (selectedField.value?.type === 'custom' ? selectedField.value.index : null))
const selectedCustomFieldForSmartDrop = computed(() => {
  const index = selectedCustomFieldIndex.value
  return index === null ? null : props.customFields[index] || null
})
const canApplySmartDropTarget = computed(() => Boolean(props.editable && selectedCustomFieldForSmartDrop.value))
const smartDropTapHint = computed(() =>
  canApplySmartDropTarget.value ? '选中字段后点击应用' : '先选择字段，再点击落点应用',
)
const requiredWhenCandidateFields = computed(() => {
  if (!selectedField.value || selectedField.value.type !== 'custom') return []
  const currentIndex = selectedField.value.index
  const currentField = props.customFields[currentIndex]
  const currentParentKey = currentField?.parentKey || primaryKey.value
  return props.customFields
    .map((field, index) => {
      const fieldRequiredWhenKey = field.requiredWhen?.fieldKey
      return {
        value: field.key,
        label: fieldTitle(field, `更换确认${index + 1}`),
        meta: `${field.key}${fieldRequiredWhenKey ? ` / 已关联 ${fieldRequiredWhenKey}` : ''}`,
        equals: replacementConditionValue(field),
        index,
        field,
      }
    })
    .filter((item) => {
      if (!item.value || item.index === currentIndex) return false
      const parentKey = item.field.parentKey || primaryKey.value
      if (parentKey !== currentParentKey) return false
      return item.field.relationRole === 'accessory_replace_confirm' || isReplacementConfirmationField(item.field)
    })
})
const selectedRequiredWhenFieldKey = computed(() => selectedFieldDetail.value?.requiredWhen?.fieldKey || '')
const selectedFieldHierarchyHint = computed(() => {
  const field = selectedFieldDetail.value
  if (!field) return ''
  if (field.requiredWhen?.fieldKey) {
    return '条件采集：只有附属设备确认更换后，才采集这个旧件、新件或照片。'
  }
  if (isMainOldDeviceField(field)) {
    return '主设备 · 更换前：旧终端、旧总表等拆回字段，和新主设备同属于任务对象。'
  }
  if (field.relationRole === 'replacement_device') {
    return '主设备 · 更换后：新终端、新总表等本体更换字段；换主设备时还要确认通讯模块、SIM 卡等附属设备是否更换。'
  }
  if (field.relationRole === 'accessory_replace_confirm' || isReplacementConfirmationField(field)) {
    return '附属设备确认：通讯模块、SIM 卡、采集器等先确认是否更换，再触发后续采集。'
  }
  if (
    field.relationRole === 'accessory_new_device'
    && props.customFields.some((item) => item.relationRole === 'replacement_device')
  ) {
    return '换主设备时，附属设备不能直接平铺；请先设置“是否更换”确认字段，再把旧件、新件或照片挂到确认字段。'
  }
  if (field.relationRole === 'accessory_new_device' || field.relationRole === 'old_device' || isRecoveredDeviceField(field)) {
    return '任务对象下的附属设备：适合换模块，在同一任务对象下记录旧件、新件、回收和照片。'
  }
  if (isEvidenceField(field)) {
    return '照片证据：按父字段和条件规则归档到对应任务对象或附属设备确认下。'
  }
  return ''
})

function fieldTitle(field: FieldForm, fallback: string) {
  return field.label?.trim() || field.key?.trim() || fallback
}

function uniqueFieldLabels(fields: FieldForm[]) {
  return Array.from(new Set(fields.map((field) => fieldTitle(field, '未命名字段')).filter(Boolean)))
}

function uniqueTemplatePreviewRows(rows: TemplatePreviewFieldRow[]) {
  const seen = new Set<string>()
  const uniqueRows: TemplatePreviewFieldRow[] = []
  for (const row of rows) {
    const key = String(row.key || row.label || '').trim()
    if (!key || seen.has(key)) continue
    uniqueRows.push(row)
    seen.add(key)
  }
  return uniqueRows
}

function templatePreviewRowFromField(field: FieldForm): TemplatePreviewFieldRow {
  return {
    key: field.key || field.label,
    label: fieldTitle(field, '未命名字段'),
    source: field.source,
    captureMethod: field.captureMethod,
    dataType: field.dataType,
    required: field.required,
    parentKey: field.parentKey || '',
    relationRole: field.relationRole || '',
    requiredWhen: field.requiredWhen || null,
    showInConstructionPanel: field.showInConstructionPanel !== false,
    templateHierarchyRole: templateHierarchyRoleFromField(field),
    templateParentLabel: templateParentLabelForField(field),
    templateConditionHint: templateConditionHintForField(field),
    platformFillRule: field.source === 'system' ? '上传时平台生成' : '',
  }
}

function templateHierarchyRoleFromField(field: FieldForm) {
  if (field.requiredWhen?.fieldKey) return '条件采集'
  if (field.relationRole) return relationRoleLabel(field.relationRole)
  return fieldRole(field)
}

function templateParentLabelForField(field: FieldForm) {
  const parentKey = String(field.parentKey || '').trim()
  if (!parentKey) return ''
  if (parentKey === primaryKey.value) return fieldTitle(props.primaryField, '任务对象')
  if (parentKey === aggregateKey.value) return fieldTitle(props.aggregateField, '聚合字段')
  const parentField = props.customFields.find((item) => item.key === parentKey)
  return parentField ? fieldTitle(parentField, parentKey) : parentKey
}

function templateConditionHintForField(field: FieldForm) {
  const requiredWhen = field.requiredWhen
  if (!requiredWhen?.fieldKey) return ''
  const triggerField = props.customFields.find((item) => item.key === requiredWhen.fieldKey)
  const triggerLabel = triggerField ? fieldTitle(triggerField, requiredWhen.fieldKey) : requiredWhen.fieldKey
  const equals = Array.isArray(requiredWhen.equals) ? requiredWhen.equals.join('/') : requiredWhen.equals
  return `${triggerLabel} = ${equals} 时需要提供`
}

function fieldRole(field: FieldForm) {
  if (field.captureMethod === 'photo' || field.dataType === 'image') return '照片证据'
  if (field.source === 'import') return '导入字段'
  if (field.source === 'field_collection') return '现场采集'
  if (field.source === 'review') return '审阅补录'
  return '系统字段'
}

function fieldMeta(field: FieldForm) {
  const required = field.required ? '必填' : '选填'
  const capture = captureLabel(field.captureMethod)
  const type = dataTypeLabel(field.dataType)
  const role = isMainOldDeviceField(field) ? '主设备 · 更换前' : relationRoleLabel(field.relationRole)
  return `${role} · ${capture} · ${type} · ${required}`
}

function requiredWhenSummary(field: FieldForm) {
  const fieldKey = field.requiredWhen?.fieldKey
  if (!fieldKey) return ''
  const equals = Array.isArray(field.requiredWhen?.equals)
    ? field.requiredWhen.equals.join('/')
    : field.requiredWhen?.equals
  return ` / ${fieldKey}=${equals} 时必填`
}

function relationRoleLabel(role: FieldForm['relationRole']) {
  const match = roleOptions.find((option) => option.value === role)
  return match?.label || '未分类'
}

function templateHierarchyHint(field: TemplatePreviewFieldRow) {
  if (field.templateHierarchyRole) return field.templateHierarchyRole
  const roleLabels: Record<string, string> = {
    aggregate: '聚合字段',
    task_object: '任务对象',
    task_detail: '任务核心',
    replacement_device: '主设备更换',
    old_device: '旧设备',
    accessory_replace_confirm: '附属设备确认',
    accessory_new_device: '附属设备更换',
    evidence_photo: '照片证据',
    supporting_field: '辅助字段',
  }
  if (field.requiredWhen?.fieldKey) return '条件采集'
  return roleLabels[field.relationRole] || (field.showInConstructionPanel ? '现场采集' : '模板字段')
}

function captureLabel(method: CaptureMethod) {
  const labels: Record<CaptureMethod, string> = {
    manual: '录入',
    scan: '扫码',
    photo: '拍照',
    select: '选择',
    datetime: '时间',
    location: '定位',
    system: '系统',
    none: '无采集',
  }
  return labels[method] || method
}

function dataTypeLabel(type: DataType) {
  const labels: Record<DataType, string> = {
    text: '文本',
    number: '数字',
    datetime: '时间',
    image: '图片',
    enum: '选项',
    duration: '时长',
    location: '位置',
    boolean: '是/否',
  }
  return labels[type] || type
}

function normalizedFieldKey(field: FieldForm) {
  return String(field.key || '').trim().toLowerCase()
}

function isEvidenceField(field: FieldForm) {
  return field.captureMethod === 'photo' || field.dataType === 'image'
}

function normalizedFieldLabel(field: FieldForm) {
  return String(field.label || '').trim().toLowerCase()
}

function isReplacementConfirmationField(field: FieldForm) {
  const text = `${normalizedFieldKey(field)} ${normalizedFieldLabel(field)}`
  return field.relationRole === 'accessory_replace_confirm'
    || text.includes('replace_confirm')
    || text.includes('replacement_confirm')
    || text.includes('是否更换')
    || text.includes('确认是否更换')
}

function isRequiredReplacementField(field: FieldForm) {
  const text = `${normalizedFieldKey(field)} ${normalizedFieldLabel(field)}`
  return text.includes('需更换') || text.includes('新通讯模块') || text.includes('新sim')
}

function isRecoveredDeviceField(field: FieldForm) {
  const text = `${normalizedFieldKey(field)} ${normalizedFieldLabel(field)}`
  return text.includes('旧设备') || text.includes('旧终端') || text.includes('拆回') || text.includes('回收')
}

function isMainOldDeviceField(field: FieldForm) {
  if (field.relationRole !== 'old_device' || field.requiredWhen?.fieldKey) return false
  return props.customFields.some((item) => item.relationRole === 'replacement_device')
}

function deviceReplacementHierarchyMode(fields: FieldForm[]): ReplacementHierarchyModeId {
  const hasDeviceReplacement = fields.some((field) =>
    field.relationRole === 'replacement_device'
    || field.relationRole === 'old_device'
    || field.relationRole === 'accessory_replace_confirm'
    || field.relationRole === 'accessory_new_device'
    || isReplacementConfirmationField(field),
  )
  if (!hasDeviceReplacement) return 'no_device_replacement_fields'
  if (fields.some((field) => field.relationRole === 'replacement_device')) {
    return 'main_device_with_accessory_confirmation'
  }
  return 'accessory_under_task_object'
}

function aggregateGuardIssueList(
  primaryField: FieldForm,
  aggregateField: FieldForm,
  fields: FieldForm[],
): FieldHierarchyReadinessIssue[] {
  const issues: FieldHierarchyReadinessIssue[] = []
  if (primaryField.relationRole === 'aggregate') {
    issues.push({
      id: 'primary-field-aggregate',
      mode: 'aggregate',
      message: '主字段不能作为聚合口径；台区、地区或厂家只能放在第一层聚合字段。',
    })
  }
  if (aggregateField.relationRole && aggregateField.relationRole !== 'aggregate') {
    issues.push({
      id: 'aggregate-field-role',
      mode: 'aggregate',
      message: '第一层聚合字段必须保留为聚合口径，不能改成任务字段或附属设备字段。',
    })
  }
  const extraAggregateFields = fields.filter((field) => field.relationRole === 'aggregate')
  if (extraAggregateFields.length) {
    const labels = extraAggregateFields.map((field) => fieldTitle(field, field.key || '字段')).join('、')
    issues.push({
      id: 'extra-custom-aggregate',
      mode: 'aggregate',
      message: `同一项目只能保留一个聚合字段；${labels} 应改为任务核心字段或施工展示字段。`,
    })
  }
  return issues
}

function fieldGraphHierarchyIssueList(fields: FieldForm[]): FieldHierarchyReadinessIssue[] {
  const issues: FieldHierarchyReadinessIssue[] = []
  const mode = deviceReplacementHierarchyMode(fields)
  const accessoryNewDevices = fields.filter((field) => field.relationRole === 'accessory_new_device')
  const directAccessoryNewDevices = accessoryNewDevices.filter((field) => !field.requiredWhen?.fieldKey)
  const directOldDeviceOrEvidenceFields = fields.filter((field) =>
    !field.requiredWhen?.fieldKey
    && (field.relationRole === 'old_device' || field.relationRole === 'evidence_photo' || isRecoveredDeviceField(field)),
  )
  const mainReplacementFields = fields.filter((field) => field.relationRole === 'replacement_device')
  const mainOldDeviceFields = fields.filter((field) => field.relationRole === 'old_device' && !field.requiredWhen?.fieldKey)
  const accessoryConfirmFields = fields.filter((field) =>
    field.relationRole === 'accessory_replace_confirm' || isReplacementConfirmationField(field),
  )
  const accessoryConfirmKeys = new Set(accessoryConfirmFields.map((field) => field.key).filter(Boolean))
  const conditionalChildFields = fields.filter((field) =>
    Boolean(field.requiredWhen?.fieldKey && accessoryConfirmKeys.has(field.requiredWhen.fieldKey)),
  )
  const unconditionalMainAccessoryFields = mainReplacementFields.length
    ? directAccessoryNewDevices
    : []

  if (mode === 'accessory_under_task_object') {
    if (!directAccessoryNewDevices.length) {
      issues.push({
        id: 'module-accessory-new-device',
        mode: 'module',
        message: '换模块需要在任务对象下保留新附属设备和旧设备/回收证据。',
      })
    }
    if (!directOldDeviceOrEvidenceFields.length) {
      issues.push({
        id: 'module-old-device-evidence',
        mode: 'module',
        message: '换模块需要在任务对象下保留新附属设备和旧设备/回收证据。',
      })
    }
  }

  if (mode === 'main_device_with_accessory_confirmation') {
    if (!mainReplacementFields.length || !mainOldDeviceFields.length) {
      issues.push({
        id: 'terminal-main-device',
        mode: 'terminal',
        message: '换终端需要主设备更换、旧设备、附属设备确认和条件采集。',
      })
    }
    if (!accessoryConfirmFields.length) {
      issues.push({
        id: 'terminal-accessory-confirm',
        mode: 'terminal',
        message: '换终端需要主设备更换、旧设备、附属设备确认和条件采集。',
      })
    }
    if (!conditionalChildFields.length) {
      issues.push({
        id: 'terminal-conditional-child',
        mode: 'terminal',
        message: '换终端需要主设备更换、旧设备、附属设备确认和条件采集。',
      })
    }
    if (unconditionalMainAccessoryFields.length) {
      issues.push({
        id: 'terminal-unconditional-accessory',
        mode: 'terminal',
        message: '换终端的附属设备不能直接平铺，需要先确认是否更换，再按条件采集旧件、新件或照片。',
      })
    }
  }

  return issues
}

function backendDeviceHierarchyEvidenceList(
  check: BackendDeviceHierarchyReadinessCheck | null | undefined,
  key: string,
) {
  const value = check?.evidence?.[key]
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item || '').trim()).filter(Boolean)
}

function backendDeviceHierarchyEvidenceFlag(
  check: BackendDeviceHierarchyReadinessCheck | null | undefined,
  key: string,
) {
  return Boolean(check?.evidence?.[key])
}

function backendDeviceHierarchyContractList(
  check: BackendDeviceHierarchyReadinessCheck | null | undefined,
) {
  const contract = check?.evidence?.hierarchy_contract
  if (!contract || typeof contract !== 'object') return []
  return ['module_replacement', 'terminal_replacement', 'conditional_collection']
    .map((key) => String((contract as Record<string, unknown>)[key] || '').trim())
    .filter(Boolean)
}

function backendDeviceHierarchyIssueList(
  check: BackendDeviceHierarchyReadinessCheck | null | undefined,
): BackendDeviceHierarchyIssue[] {
  if (!check || check.id !== 'device_hierarchy' || check.status !== 'failed') return []

  const issueSpecs = [
    {
      id: 'missing-parent',
      evidenceKey: 'missing_parent_keys',
      label: '字段未挂到任务对象',
      helper: '更换模块时，新模块、旧设备和证据要挂在同一任务对象下；更换终端时，主设备和附属设备确认也要从任务对象展开。',
      className: 'backend-issue-parent',
    },
    {
      id: 'missing-confirmation-role',
      evidenceKey: 'missing_confirmation_keys',
      label: '附属设备确认角色不完整',
      helper: '换终端要先确认通讯模块、SIM 卡等附属设备是否更换，再决定后续采集。',
      className: 'backend-issue-confirm',
    },
    {
      id: 'invalid-conditional',
      evidenceKey: 'invalid_conditional_keys',
      label: '条件采集未关联确认项',
      helper: '旧件、新件和照片需要指向同一任务对象下的“是否更换”确认字段。',
      className: 'backend-issue-conditional',
    },
    {
      id: 'unconditional-child',
      evidenceKey: 'unconditional_child_keys',
      label: '附属设备应按条件采集',
      helper: '换终端时，通讯模块、SIM 卡等附属设备不能直接平铺，要由确认项触发。',
      className: 'backend-issue-unconditional',
    },
    {
      id: 'confirmation-without-child',
      evidenceKey: 'confirmation_without_child_keys',
      label: '确认项缺少后续采集',
      helper: '确认更换后，需要有旧件、新件或照片证据承接现场数据。',
      className: 'backend-issue-missing-child',
    },
  ]

  const issues = issueSpecs.flatMap((item) => {
    const keys = backendDeviceHierarchyEvidenceList(check, item.evidenceKey)
    if (!keys.length) return []
    return [{
      id: item.id,
      label: item.label,
      helper: item.helper,
      keys,
      className: item.className,
    }]
  })

  if (backendDeviceHierarchyEvidenceFlag(check, 'missing_main_accessory_confirmation')) {
    issues.push({
      id: 'missing-main-accessory-confirmation',
      label: '缺少附属设备确认',
      helper: '换终端需要通讯模块、SIM 卡等附属设备是否更换的确认项。',
      keys: backendDeviceHierarchyEvidenceList(check, 'main_replacement_keys'),
      className: 'backend-issue-main-confirm',
    })
  }

  return issues
}

function deviceReplacementRole(field: FieldForm) {
  if (isMainOldDeviceField(field)) return '主设备 · 更换前'
  if (field.relationRole === 'replacement_device') return '主设备 · 更换后'
  if (field.relationRole === 'accessory_replace_confirm') return '附属设备 · 是否更换'
  if (field.relationRole === 'accessory_new_device') return '附属设备 · 新设备'
  if (field.relationRole === 'old_device') return '附属设备 · 拆回'
  if (field.relationRole) return relationRoleLabel(field.relationRole)
  if (isReplacementConfirmationField(field)) return '附属设备 · 确认项'
  if (isRequiredReplacementField(field)) return '附属设备 · 必换'
  if (isRecoveredDeviceField(field)) return '附属设备 · 拆回'
  return '附属设备'
}

function deviceRelationClass(field: FieldForm) {
  const classes = ['device-child']
  const isMainOldDevice = isMainOldDeviceField(field)
  if (isMainOldDevice) classes.push('main-old-device-child')
  if (field.relationRole === 'replacement_device') classes.push('main-replacement-child')
  if (field.relationRole === 'accessory_replace_confirm') classes.push('accessory-confirm-child')
  if (field.relationRole === 'accessory_new_device') classes.push('accessory-new-child')
  if (field.relationRole === 'old_device' && !isMainOldDevice) classes.push('old-device-child')
  if (isEvidenceField(field)) classes.push('evidence-child')
  if (field.requiredWhen?.fieldKey) classes.push('conditional-child')
  return classes.join(' ')
}

function deviceRelationConnectorClass(field: FieldForm) {
  if (isMainOldDeviceField(field)) return 'main-old-device-link'
  if (field.relationRole === 'replacement_device') return 'main-replacement-link'
  if (field.relationRole === 'accessory_replace_confirm') return 'accessory-confirm-link'
  if (field.relationRole === 'accessory_new_device') return 'accessory-new-link'
  if (field.relationRole === 'old_device') return 'old-device-link'
  if (isEvidenceField(field)) return 'evidence-link'
  return ''
}

function parentConnectorLabel(item: MindMapItem) {
  if (item.connectorClassName === 'main-old-device-link') return '主设备更换前'
  if (item.connectorClassName === 'main-replacement-link') return '主设备更换'
  if (item.connectorClassName === 'accessory-confirm-link') return '附属设备确认'
  if (item.connectorClassName === 'evidence-link') return '证据照片'
  return '隶属任务对象'
}

function isCoreField(field: FieldForm) {
  if (field.relationRole === 'task_object' || field.relationRole === 'task_detail') return true
  if (
    field.relationRole === 'replacement_device'
    || field.relationRole === 'old_device'
    || field.relationRole === 'accessory_replace_confirm'
    || field.relationRole === 'accessory_new_device'
    || field.relationRole === 'evidence_photo'
  ) {
    return false
  }
  const key = normalizedFieldKey(field)
  if (terminalAggregateCandidateKeys.has(key)) return true
  if (field.source === 'import') return true
  return key.includes('address') || key.includes('location')
}

function constructionPanelLabel(field: FieldForm) {
  return field.showInConstructionPanel === false ? '施工隐藏' : '施工展示'
}

function fieldOptionsText(field: FieldForm) {
  return (field.options || []).join('、')
}

function parseFieldOptions(value: string) {
  return String(value || '')
    .split(/[、,，\n]/)
    .map((option) => option.trim())
    .filter(Boolean)
}

function updateFieldOptions(value: string) {
  updateSelectedField({ options: parseFieldOptions(value) })
}

function replacementConditionValue(field: FieldForm) {
  const replacementOption = (field.options || []).find((option) => option.includes('更换') && !option.includes('不'))
  return replacementOption || field.options?.[0] || '更换'
}

function updateRequiredWhenField(value: unknown) {
  const fieldKey = String(value || '').trim()
  if (!fieldKey) {
    clearRequiredWhenField()
    return
  }
  const candidate = requiredWhenCandidateFields.value.find((option) => option.value === fieldKey)
  updateSelectedField({ requiredWhen: { fieldKey, equals: candidate?.equals || '更换' } })
}

function clearRequiredWhenField() {
  updateSelectedField({ requiredWhen: undefined })
}

function layerNodeY(index: number, total: number) {
  if (total <= 1) return 150
  const top = 54
  const bottom = 246
  return Math.round(top + ((bottom - top) / Math.max(total - 1, 1)) * index)
}

function selectField(type: FieldSelectionType, index = -1) {
  selectedField.value = { type, index }
}

function isSelected(type: FieldSelectionType, index = -1) {
  return selectedField.value?.type === type && selectedField.value.index === index
}

function selectedParentLabel(field: FieldForm) {
  const parentKey = field.parentKey || primaryKey.value
  if (parentKey === aggregateKey.value) return fieldTitle(props.aggregateField, '聚合字段')
  if (parentKey === primaryKey.value) return fieldTitle(props.primaryField, '主字段')
  return parentKey || '项目对象'
}

function selectBucketItem(bucket: FieldRoleBucket) {
  const item = bucket.items[0]
  if (!item) return
  selectField(bucket.id === 'platform' ? 'platform' : 'custom', item.index)
}

function emitTemplateAction(action: TemplateActionPayload['action'], templateType: TemplateActionPayload['templateType']) {
  emit('template-action', { action, templateType })
}

function updateSelectedField(updates: Partial<FieldForm>) {
  if (!selectedField.value || selectedField.value.type === 'platform') return
  emit('update-field', {
    type: selectedField.value.type,
    fieldIndex: selectedField.value.type === 'custom' ? selectedField.value.index : undefined,
    updates,
  })
}

function fieldDropIntentForTarget(target: FieldDropTarget, field?: FieldForm): FieldDropIntent {
  if (target === 'aggregate') return 'aggregate'
  if (target === 'core') return 'task-core'
  if (!field) return 'conditional-accessory'
  if (isEvidenceField(field)) return 'evidence-photo'
  if (field.relationRole === 'replacement_device') return 'main-device'
  if (field.relationRole === 'accessory_replace_confirm' || isReplacementConfirmationField(field)) return 'accessory-confirm'
  return 'conditional-accessory'
}

function fieldDropIntentForDeviceNode(targetField: FieldForm, field?: FieldForm): FieldDropIntent {
  if (field && isEvidenceField(field)) return 'evidence-photo'
  if (targetField.relationRole === 'replacement_device') return 'accessory-confirm'
  if (targetField.relationRole === 'accessory_replace_confirm' || isReplacementConfirmationField(targetField)) {
    return 'conditional-accessory'
  }
  return fieldDropIntentForTarget('device', field || targetField)
}

function deviceNodeTriggerFieldKey(targetField: FieldForm) {
  if (targetField.relationRole === 'accessory_replace_confirm' || isReplacementConfirmationField(targetField)) {
    return targetField.key || undefined
  }
  return undefined
}

function inferredRelationRoleForDrop(intent: FieldDropIntent, field: FieldForm): FieldForm['relationRole'] {
  switch (intent) {
    case 'aggregate':
      return field.relationRole || 'supporting_field'
    case 'task-core':
      return 'task_detail'
    case 'main-device':
      return 'replacement_device'
    case 'accessory-confirm':
      return 'accessory_replace_confirm'
    case 'conditional-accessory':
      if (isEvidenceField(field)) return 'evidence_photo'
      return isRecoveredDeviceField(field) ? 'old_device' : 'accessory_new_device'
    case 'evidence-photo':
      return 'evidence_photo'
    default:
      return field.relationRole
  }
}

function replacementConfirmOptionsForDrop(field: FieldForm) {
  return field.options?.length ? field.options : ['更换', '不更换', '待确认']
}

function firstAccessoryConfirmFieldUnderParent(parentKey: string) {
  return props.customFields.find((field) => {
    const candidateParentKey = field.parentKey || primaryKey.value
    if (candidateParentKey !== parentKey) return false
    return field.relationRole === 'accessory_replace_confirm' || isReplacementConfirmationField(field)
  })
}

function replacementConditionForDrop(triggerFieldKey: string) {
  const triggerField = props.customFields.find((field) => field.key === triggerFieldKey)
  return triggerField ? replacementConditionValue(triggerField) : '更换'
}

function conditionalRuleForDrop(
  intent: FieldDropIntent,
  parentKey: string,
  triggerFieldKey?: string,
): FieldRequiredWhen | undefined {
  if (intent !== 'conditional-accessory' && intent !== 'evidence-photo') return undefined
  const fieldKey = triggerFieldKey || firstAccessoryConfirmFieldUnderParent(parentKey)?.key
  if (!fieldKey) return undefined
  return { fieldKey, equals: replacementConditionForDrop(fieldKey) }
}

function draggedFieldIndexFromEvent(event: DragEvent) {
  const rawIndex = event.dataTransfer?.getData('text/plain')
  const fieldIndex = rawIndex ? Number(rawIndex) : draggingFieldIndex.value
  draggingFieldIndex.value = null
  return Number.isInteger(fieldIndex) ? fieldIndex : null
}

function smartDropFieldIndexFromSelection() {
  const fieldIndex = selectedCustomFieldIndex.value
  if (fieldIndex === null || !props.customFields[fieldIndex]) return null
  return fieldIndex
}

function applySmartDropUpdates(fieldIndex: number, intent: FieldDropIntent, parentKey: string, triggerFieldKey?: string) {
  const field = props.customFields[fieldIndex]
  if (!field) return
  const updates: Partial<FieldForm> = {
    parentKey,
    relationRole: inferredRelationRoleForDrop(intent, field),
    requiredWhen: conditionalRuleForDrop(intent, parentKey, triggerFieldKey),
  }

  if (intent === 'task-core') {
    updates.source = field.source === 'field_collection' ? 'field_collection' : 'import'
    updates.showInConstructionPanel = field.showInConstructionPanel ?? true
  }
  if (intent === 'main-device') {
    updates.source = 'field_collection'
    updates.required = true
    if (field.captureMethod === 'manual' && field.dataType === 'text') updates.captureMethod = 'scan'
  }
  if (intent === 'accessory-confirm') {
    Object.assign(updates, {
      source: 'field_collection',
      captureMethod: 'select',
      dataType: 'enum',
      required: true,
      options: replacementConfirmOptionsForDrop(field),
    })
  }
  if (intent === 'conditional-accessory') {
    updates.source = 'field_collection'
    updates.required = true
  }
  if (intent === 'evidence-photo') {
    updates.source = 'field_collection'
    updates.captureMethod = 'photo'
    updates.dataType = 'image'
    updates.required = true
  }

  emit('update-field', {
    type: 'custom',
    fieldIndex,
    updates,
  })
  selectField('custom', fieldIndex)
}

function normalizeDashboardMetrics(metrics: DashboardMetricForm[]) {
  const seen = new Set<string>()
  const normalized: DashboardMetricForm[] = []
  for (const metric of metrics) {
    const key = String(metric.key || '').trim()
    const label = String(metric.label || key).trim()
    if (!key || !label || seen.has(key)) continue
    normalized.push({
      key,
      label,
      source: String(metric.source || '').trim() || undefined,
      scope: String(metric.scope || '').trim() || undefined,
    })
    seen.add(key)
  }
  return normalized
}

function metricSelectionCount(card: DashboardMetricPresetCard) {
  return card.metrics.filter((metric) => selectedDashboardMetricKeys.value.has(metric.key)).length
}

function metricCardSelected(card: DashboardMetricPresetCard) {
  return card.metrics.length > 0 && metricSelectionCount(card) === card.metrics.length
}

function toggleDashboardMetric(card: DashboardMetricPresetCard) {
  if (!props.editable) return
  const cardMetricKeys = new Set(card.metrics.map((metric) => metric.key))
  const currentMetrics = normalizeDashboardMetrics(props.dashboardMetrics || [])
  const shouldRemove = metricCardSelected(card)
  const nextMetrics = shouldRemove
    ? currentMetrics.filter((metric) => !cardMetricKeys.has(metric.key))
    : [...currentMetrics]
  if (!shouldRemove) {
    const nextKeys = new Set(nextMetrics.map((metric) => metric.key))
    for (const metric of card.metrics) {
      if (!nextKeys.has(metric.key)) {
        nextMetrics.push({ ...metric })
        nextKeys.add(metric.key)
      }
    }
  }
  emit('update-dashboard-metrics', normalizeDashboardMetrics(nextMetrics))
}

function applyReplacementHierarchyTemplate(templateId: ReplacementHierarchyTemplateId) {
  if (!props.editable) return
  emit('apply-replacement-template', { templateId })
}

function onSmartDropField(intent: FieldDropIntent, parentKey: string, event: DragEvent, triggerFieldKey?: string) {
  if (!props.editable) return
  const fieldIndex = draggedFieldIndexFromEvent(event)
  if (fieldIndex === null) return
  applySmartDropUpdates(fieldIndex, intent, parentKey, triggerFieldKey)
}

function onSmartDropDeviceNode(targetField: FieldForm | undefined, event: DragEvent) {
  if (!props.editable || !targetField) return
  const fieldIndex = draggedFieldIndexFromEvent(event)
  if (fieldIndex === null) return
  const field = props.customFields[fieldIndex]
  if (!field) return
  const parentKey = targetField.parentKey || primaryKey.value
  const intent = fieldDropIntentForDeviceNode(targetField, field)
  const triggerFieldKey = deviceNodeTriggerFieldKey(targetField)
  applySmartDropUpdates(fieldIndex, intent, parentKey, triggerFieldKey)
}

function onSmartDropTargetClick(intent: FieldDropIntent, parentKey: string, triggerFieldKey?: string) {
  if (!props.editable) return
  const fieldIndex = smartDropFieldIndexFromSelection()
  if (fieldIndex === null) return
  applySmartDropUpdates(fieldIndex, intent, parentKey, triggerFieldKey)
}

function onFieldDragStart(index: number, event: DragEvent) {
  if (!props.editable) return
  draggingFieldIndex.value = index
  event.dataTransfer?.setData('text/plain', String(index))
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function onDropParent(parentKey: string, event: DragEvent) {
  if (!props.editable) return
  const rawIndex = event.dataTransfer?.getData('text/plain')
  const fieldIndex = rawIndex ? Number(rawIndex) : draggingFieldIndex.value
  draggingFieldIndex.value = null
  if (fieldIndex === null || Number.isNaN(fieldIndex)) return
  emit('update-parent', { fieldIndex, parentKey })
}

function onDragEnd() {
  draggingFieldIndex.value = null
}
</script>

<template>
  <section class="field-graph-designer">
    <div class="field-graph-header">
      <div>
        <strong>字段关系图</strong>
        <span>用层级关系确认项目对象、导入字段、现场采集和照片证据。</span>
      </div>
      <span class="field-graph-mode">{{ editable ? '草稿可编辑' : '只读查看' }}</span>
    </div>

    <div class="field-mind-map" aria-label="项目字段层级关系图">
      <svg class="field-map-connector" viewBox="0 0 1000 300" preserveAspectRatio="none" aria-hidden="true">
        <path
          v-for="connector in mindMapConnectors"
          :key="connector.id"
          :d="connector.d"
          :class="connector.className"
        />
        <text
          v-for="connector in mindMapConnectors"
          :key="`${connector.id}-label`"
          class="field-map-connector-label"
          :class="connector.labelClassName"
          :x="connector.labelX"
          :y="connector.labelY"
        >
          {{ connector.label }}
        </text>
      </svg>
      <div class="field-map-legend" aria-label="字段连线说明">
        <span v-for="item in mindMapConnectorLegend" :key="item.label" :class="item.className">
          <i aria-hidden="true"></i>
          {{ item.label }}
        </span>
      </div>
      <div class="field-map-layer aggregate-layer">
        <span>第一层 · 聚合字段</span>
        <button
          type="button"
          class="field-map-node aggregate-node"
          :class="{ 'drop-enabled': editable, selected: isSelected('aggregate') }"
          @dragover.prevent
          @drop="onSmartDropField('aggregate', aggregateKey, $event)"
          @click="selectField('aggregate')"
        >
          <small>当前聚合口径</small>
          <strong>{{ fieldTitle(aggregateField, '聚合字段') }}</strong>
          <em>{{ constructionPanelLabel(aggregateField) }}</em>
        </button>
      </div>
      <div class="field-map-layer core-layer">
        <span>第二层 · 任务核心</span>
        <button
          v-for="item in mindMapCoreItems"
          :key="item.key"
          type="button"
          class="field-map-node"
          :class="[item.className, { 'drop-enabled': editable, selected: isSelected(item.selectType, item.selectIndex), 'backend-issue-node': backendDeviceHierarchyIssueKeys.has(item.key) }]"
          @dragover.prevent
          @drop="onSmartDropField(fieldDropIntentForTarget('core'), primaryKey, $event)"
          @click="selectField(item.selectType, item.selectIndex)"
        >
          <small>{{ item.role }}</small>
          <strong>{{ item.label }}</strong>
          <em>{{ item.meta }}</em>
        </button>
      </div>
      <div class="field-map-layer device-layer">
        <span>第三层 · 设备动作/证据</span>
        <button
          v-for="item in mindMapDeviceItems"
          :key="item.key"
          type="button"
          class="field-map-node"
          :class="[item.className, { 'drop-enabled': editable, selected: isSelected(item.selectType, item.selectIndex), 'backend-issue-node': backendDeviceHierarchyIssueKeys.has(item.key) }]"
          @dragover.prevent
          @drop="onSmartDropDeviceNode(customFields[item.selectIndex], $event)"
          @click="selectField(item.selectType, item.selectIndex)"
        >
          <small>{{ item.role }}</small>
          <strong>{{ item.label }}</strong>
          <em>{{ item.meta }}</em>
        </button>
      </div>
    </div>

    <div class="field-replacement-template-panel" aria-label="设备更换层级模板">
      <div class="field-replacement-template-head">
        <div>
          <strong>设备更换层级模板</strong>
          <span>按项目类型补齐任务对象、主设备、附属设备确认、条件采集和照片证据。</span>
        </div>
        <ElTag effect="plain">可调整</ElTag>
      </div>
      <div class="field-replacement-template-grid">
        <button
          v-for="card in replacementHierarchyTemplateCards"
          :key="card.id"
          type="button"
          class="field-replacement-template-card"
          :class="[card.className, { disabled: !editable }]"
          :disabled="!editable"
          @click="applyReplacementHierarchyTemplate(card.id)"
        >
          <span>{{ card.title }}</span>
          <strong>{{ card.mode }}</strong>
          <small>{{ card.helper }}</small>
        </button>
      </div>
    </div>

    <div class="field-replacement-mode-cards" aria-label="更换层级模式">
      <span class="field-replacement-mode-eyebrow">更换层级</span>
      <article v-for="item in replacementHierarchyModeCards" :key="item.id" :class="item.className">
        <strong>{{ item.value }}</strong>
        <span>{{ item.title }}</span>
        <small>{{ item.description }}</small>
      </article>
    </div>

    <div class="field-dashboard-metric-editor" aria-label="驾驶舱指标口径">
      <div class="field-dashboard-metric-head">
        <div>
          <strong>驾驶舱指标口径</strong>
          <span>选择这个项目要进入进度、交付、现场、审阅和 KPI 的指标。</span>
        </div>
        <ElTag effect="plain">{{ selectedDashboardMetricKeys.size }} 项</ElTag>
      </div>
      <div class="field-dashboard-metric-grid">
        <button
          v-for="card in dashboardMetricPresetCards"
          :key="card.id"
          type="button"
          class="dashboard-metric-editor-card"
          :class="{ selected: metricCardSelected(card), disabled: !editable }"
          :disabled="!editable"
          @click="toggleDashboardMetric(card)"
        >
          <span>{{ card.title }}</span>
          <strong>{{ metricSelectionCount(card) }}/{{ card.metrics.length }}</strong>
          <small>{{ card.helper }}</small>
          <em>
            <i v-for="metric in card.metrics" :key="metric.key">{{ metric.label }}</i>
          </em>
        </button>
      </div>
    </div>

    <div class="field-hierarchy-readiness-panel" aria-label="层级完整性">
      <article
        v-for="card in fieldGraphHierarchyReadinessCards"
        :key="card.id"
        class="field-hierarchy-readiness-card"
        :class="card.className"
      >
        <div>
          <strong>{{ card.title }}</strong>
          <small>{{ card.note }}</small>
        </div>
        <ElTag :type="card.issueCount ? 'warning' : 'success'" effect="light">
          {{ card.value }}
        </ElTag>
      </article>
    </div>

    <div v-if="backendReadinessCheck" class="field-backend-readiness-panel" aria-label="后端上线检查回显">
      <div class="field-backend-readiness-head">
        <div>
          <strong>后端上线检查回显</strong>
          <span>设备更换层级</span>
        </div>
        <ElTag :type="backendDeviceHierarchyIssues.length ? 'warning' : 'success'" effect="light">
          {{ backendDeviceHierarchyStatusLabel }}
        </ElTag>
      </div>
      <div v-if="backendDeviceHierarchyContractNotes.length" class="field-backend-hierarchy-contract">
        <strong>后端层级口径</strong>
        <span v-for="note in backendDeviceHierarchyContractNotes" :key="note">
          {{ note }}
        </span>
      </div>
      <div v-if="backendDeviceHierarchyIssues.length" class="field-backend-readiness-list">
        <article
          v-for="issue in backendDeviceHierarchyIssues"
          :key="issue.id"
          class="field-backend-readiness-issue"
          :class="issue.className"
        >
          <div>
            <strong>{{ issue.label }}</strong>
            <small>{{ issue.helper }}</small>
          </div>
          <span>
            <ElTag
              v-for="key in issue.keys"
              :key="`${issue.id}-${key}`"
              size="small"
              effect="plain"
            >
              {{ key }}
            </ElTag>
            <ElTag v-if="!issue.keys.length" size="small" effect="plain">
              整体规则
            </ElTag>
          </span>
        </article>
      </div>
      <small v-else>已保存配置的设备更换层级通过后端上线检查。</small>
    </div>

    <div class="field-map-relation-summary" aria-label="当前字段关系摘要">
      <span v-for="item in deviceRelationshipSummaryItems" :key="item.label" :class="item.className">
        <strong>{{ item.value }}</strong>
        {{ item.label }}
      </span>
    </div>

    <div class="field-smart-drop-panel" aria-label="字段智能拖拽落点">
      <div class="field-smart-drop-guide">
        <span v-for="item in smartDropGuideItems" :key="item">{{ item }}</span>
        <span class="field-smart-drop-selected">{{ smartDropTapHint }}</span>
      </div>
      <div class="field-device-hierarchy-guide" aria-label="设备更换层级规则">
        <article v-for="item in deviceHierarchyGuideItems" :key="item.title">
          <strong>{{ item.relation }}</strong>
          <span>{{ item.note }}</span>
        </article>
      </div>
      <div class="field-smart-drop-zones">
        <button
          type="button"
          class="field-smart-drop-zone task-core-drop"
          :class="{ 'drop-enabled': editable, 'tap-enabled': canApplySmartDropTarget, 'tap-disabled': editable && !canApplySmartDropTarget }"
          :aria-disabled="!canApplySmartDropTarget"
          @dragover.prevent
          @drop="onSmartDropField('task-core', primaryKey, $event)"
          @click="onSmartDropTargetClick('task-core', primaryKey)"
          @keydown.enter.prevent="onSmartDropTargetClick('task-core', primaryKey)"
          @keydown.space.prevent="onSmartDropTargetClick('task-core', primaryKey)"
        >
          <strong>拖到任务核心</strong>
          <small>安装地址、终端地址、终端号等同级任务详情</small>
        </button>
        <button
          type="button"
          class="field-smart-drop-zone main-device-drop"
          :class="{ 'drop-enabled': editable, 'tap-enabled': canApplySmartDropTarget, 'tap-disabled': editable && !canApplySmartDropTarget }"
          :aria-disabled="!canApplySmartDropTarget"
          @dragover.prevent
          @drop="onSmartDropField('main-device', primaryKey, $event)"
          @click="onSmartDropTargetClick('main-device', primaryKey)"
          @keydown.enter.prevent="onSmartDropTargetClick('main-device', primaryKey)"
          @keydown.space.prevent="onSmartDropTargetClick('main-device', primaryKey)"
        >
          <strong>拖到主设备更换</strong>
          <small>换终端时的新终端、换总表时的新总表</small>
        </button>
        <button
          type="button"
          class="field-smart-drop-zone accessory-confirm-drop"
          :class="{ 'drop-enabled': editable, 'tap-enabled': canApplySmartDropTarget, 'tap-disabled': editable && !canApplySmartDropTarget }"
          :aria-disabled="!canApplySmartDropTarget"
          @dragover.prevent
          @drop="onSmartDropField('accessory-confirm', primaryKey, $event)"
          @click="onSmartDropTargetClick('accessory-confirm', primaryKey)"
          @keydown.enter.prevent="onSmartDropTargetClick('accessory-confirm', primaryKey)"
          @keydown.space.prevent="onSmartDropTargetClick('accessory-confirm', primaryKey)"
        >
          <strong>拖到附属设备确认</strong>
          <small>通讯模块、SIM卡、采集器是否更换</small>
        </button>
        <button
          type="button"
          class="field-smart-drop-zone conditional-accessory-drop"
          :class="{ 'drop-enabled': editable, 'tap-enabled': canApplySmartDropTarget, 'tap-disabled': editable && !canApplySmartDropTarget }"
          :aria-disabled="!canApplySmartDropTarget"
          @dragover.prevent
          @drop="onSmartDropField('conditional-accessory', primaryKey, $event)"
          @click="onSmartDropTargetClick('conditional-accessory', primaryKey)"
          @keydown.enter.prevent="onSmartDropTargetClick('conditional-accessory', primaryKey)"
          @keydown.space.prevent="onSmartDropTargetClick('conditional-accessory', primaryKey)"
        >
          <strong>拖到条件采集</strong>
          <small>旧设备、新设备和照片按“更换”条件出现</small>
        </button>
      </div>
    </div>

    <div class="field-graph-layout">
      <div class="field-tree">
        <div
          class="field-node field-node-root"
          :class="{ 'drop-enabled': editable, selected: isSelected('aggregate') }"
          @dragover.prevent
          @drop="onDropParent(aggregateKey, $event)"
          @click="selectField('aggregate')"
        >
          <span>聚合字段</span>
          <strong>{{ fieldTitle(aggregateField, '聚合字段') }}</strong>
          <small>{{ fieldMeta(aggregateField) }}</small>
        </div>

        <div class="field-branch">
          <div
            class="field-drop-zone"
            :class="{ 'drop-enabled': editable }"
            @dragover.prevent
            @drop="onDropParent(aggregateKey, $event)"
          >
            <span>拖到聚合字段下</span>
            <small>适合台区、线路、区域等汇总对象的子字段。</small>
          </div>
          <div
            v-for="item in aggregateChildren"
            :key="`aggregate-${item.index}`"
            class="field-chip"
            :class="{ selected: isSelected('custom', item.index) }"
            :draggable="editable"
            @dragstart="onFieldDragStart(item.index, $event)"
            @dragend="onDragEnd"
            @click="selectField('custom', item.index)"
          >
            <span>{{ item.role }}</span>
            <strong>{{ fieldTitle(item.field, `字段${item.index + 1}`) }}</strong>
          </div>
        </div>

        <div
          class="field-node field-node-primary"
          :class="{ 'drop-enabled': editable, selected: isSelected('primary') }"
          @dragover.prevent
          @drop="onDropParent(primaryKey, $event)"
          @click="selectField('primary')"
        >
          <span>主字段</span>
          <strong>{{ fieldTitle(primaryField, '主字段') }}</strong>
          <small>{{ fieldMeta(primaryField) }}</small>
        </div>

        <div class="field-branch primary-branch">
          <div
            class="field-drop-zone"
            :class="{ 'drop-enabled': editable }"
            @dragover.prevent
            @drop="onDropParent(primaryKey, $event)"
          >
            <span>拖到主字段下</span>
            <small>适合终端、电能表、用户等施工对象的子字段。</small>
          </div>
          <div
            v-for="item in primaryChildren"
            :key="`primary-${item.index}`"
            class="field-chip"
            :class="{ required: item.field.required, selected: isSelected('custom', item.index) }"
            :draggable="editable"
            @dragstart="onFieldDragStart(item.index, $event)"
            @dragend="onDragEnd"
            @click="selectField('custom', item.index)"
          >
            <span>{{ item.role }}</span>
            <strong>{{ fieldTitle(item.field, `字段${item.index + 1}`) }}</strong>
            <small>{{ fieldMeta(item.field) }}</small>
          </div>
        </div>
      </div>

      <aside class="field-graph-side">
        <div class="field-group-list">
          <section>
            <span>导入字段</span>
            <strong>{{ importFields.length }}</strong>
          </section>
          <section>
            <span>现场采集</span>
            <strong>{{ collectionFields.length }}</strong>
          </section>
          <section>
            <span>照片证据</span>
            <strong>{{ photoFields.length }}</strong>
          </section>
          <section>
            <span>平台必备</span>
            <strong>{{ platformRequiredFields?.length || 0 }}</strong>
          </section>
        </div>

        <div class="field-role-buckets">
          <div class="field-role-heading">
            <strong>字段角色分组</strong>
            <span>可拖拽子字段先看角色，再决定挂到哪一层。</span>
          </div>
          <button
            v-for="bucket in fieldRoleBuckets"
            :key="bucket.id"
            type="button"
            class="field-role-row"
            @click="selectBucketItem(bucket)"
          >
            <span>{{ bucket.label }}</span>
            <strong>{{ bucket.items.length }}</strong>
            <small>{{ bucket.helper }}</small>
          </button>
        </div>

        <div class="selected-field-panel">
          <span>字段详情</span>
          <template v-if="selectedFieldDetail">
            <strong>{{ fieldTitle(selectedFieldDetail, '字段') }}</strong>
            <p>{{ fieldMeta(selectedFieldDetail) }}</p>
            <p>
              层级归属：
              {{ selectedField?.type === 'custom' ? selectedParentLabel(selectedFieldDetail) : '项目根对象' }}
            </p>
            <div v-if="selectedFieldHierarchyHint" class="field-hierarchy-hint-card">
              <strong>设备层级提示</strong>
              <span>{{ selectedFieldHierarchyHint }}</span>
            </div>
            <div v-if="selectedFieldEditable" class="field-detail-form">
              <label>
                <span>字段名称</span>
                <ElInput
                  :model-value="selectedFieldDetail.label"
                  size="small"
                  @update:model-value="updateSelectedField({ label: String($event) })"
                />
              </label>
              <label>
                <span>字段编码</span>
                <ElInput
                  :model-value="selectedFieldDetail.key"
                  size="small"
                  @update:model-value="updateSelectedField({ key: String($event) })"
                />
              </label>
              <label>
                <span>字段关系</span>
                <ElSelect
                  :model-value="selectedFieldDetail.relationRole"
                  size="small"
                  @change="updateSelectedField({ relationRole: $event as FieldForm['relationRole'] })"
                >
                  <ElOption
                    v-for="option in selectedRelationRoleOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </ElSelect>
              </label>
              <label>
                <span>字段来源</span>
                <ElSelect
                  :model-value="selectedFieldDetail.source"
                  size="small"
                  @change="updateSelectedField({ source: $event as FieldSource })"
                >
                  <ElOption
                    v-for="option in sourceOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </ElSelect>
              </label>
              <label>
                <span>采集方式</span>
                <ElSelect
                  :model-value="selectedFieldDetail.captureMethod"
                  size="small"
                  @change="updateSelectedField({ captureMethod: $event as CaptureMethod })"
                >
                  <ElOption
                    v-for="option in captureMethodOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </ElSelect>
              </label>
              <label>
                <span>字段格式</span>
                <ElSelect
                  :model-value="selectedFieldDetail.dataType"
                  size="small"
                  @change="updateSelectedField({ dataType: $event as DataType })"
                >
                  <ElOption
                    v-for="option in dataTypeOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </ElSelect>
              </label>
              <label v-if="selectedFieldDetail.captureMethod === 'select' || selectedFieldDetail.dataType === 'enum'">
                <span>字段选项</span>
                <ElInput
                  :model-value="fieldOptionsText(selectedFieldDetail)"
                  size="small"
                  placeholder="确认是否更换：更换、不更换、待确认"
                  @update:model-value="updateFieldOptions(String($event))"
                />
              </label>
              <label class="conditional-required-row">
                <span>更换时必填</span>
                <ElSelect
                  :model-value="selectedRequiredWhenFieldKey"
                  size="small"
                  clearable
                  placeholder="选择是否更换字段"
                  :disabled="!requiredWhenCandidateFields.length"
                  @change="updateRequiredWhenField"
                  @clear="clearRequiredWhenField"
                >
                  <ElOption
                    v-for="option in requiredWhenCandidateFields"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  >
                    <span>{{ option.label }}</span>
                    <small>{{ option.meta }}</small>
                  </ElOption>
                </ElSelect>
                <small>旧设备、新设备等附属字段可挂到同一任务对象下的“是否更换”确认字段。</small>
              </label>
              <div v-if="selectedFieldDetail.requiredWhen?.fieldKey" class="condition-summary-card">
                <strong>条件规则</strong>
                <span>
                  {{ selectedFieldDetail.requiredWhen.fieldKey }} =
                  {{
                    Array.isArray(selectedFieldDetail.requiredWhen.equals)
                      ? selectedFieldDetail.requiredWhen.equals.join('/')
                      : selectedFieldDetail.requiredWhen.equals
                  }}
                  时必填
                </span>
              </div>
              <label class="field-detail-switch">
                <span>是否必填</span>
                <ElSwitch
                  :model-value="selectedFieldDetail.required"
                  @change="updateSelectedField({ required: Boolean($event) })"
                />
              </label>
              <label class="field-detail-switch construction-toggle">
                <span>施工面板展示</span>
                <ElSwitch
                  :model-value="selectedFieldDetail.showInConstructionPanel !== false"
                  @change="updateSelectedField({ showInConstructionPanel: Boolean($event) })"
                />
              </label>
            </div>
          </template>
          <template v-else>
            <strong>未选择字段</strong>
            <p>点击字段节点可查看来源、格式和采集要求。</p>
          </template>
        </div>
      </aside>
    </div>

    <div class="template-binding-preview">
      <div class="template-binding-heading">
        <strong>模板绑定预览</strong>
        <span>字段结构会决定下载模板和中途接入项目时需要补哪些数据。</span>
      </div>
      <div class="template-impact-summary" aria-label="模板影响摘要">
        <article v-for="card in templateImpactSummaryCards" :key="card.id" :class="card.className">
          <span>{{ card.title }}</span>
          <strong>{{ card.value }}</strong>
          <small>{{ card.helper }}</small>
        </article>
      </div>
      <div class="template-download-guide" aria-label="模板下载说明">
        <article v-for="card in templateDownloadGuideCards" :key="card.id" :class="card.className">
          <span>{{ card.title }}</span>
          <strong>{{ card.value }}</strong>
          <small>{{ card.helper }}</small>
          <em>{{ card.note }}</em>
        </article>
      </div>
      <div class="template-binding-grid">
        <section>
          <span>初始接入模板</span>
          <div v-if="initialTemplateFieldRows.length" class="template-preview-field-list">
            <article v-for="field in initialTemplateFieldRows" :key="field.key">
              <strong>{{ field.label }}</strong>
              <span>{{ templateHierarchyHint(field) }}</span>
              <small v-if="field.templateParentLabel">父字段：{{ field.templateParentLabel }}</small>
              <small v-if="field.templateConditionHint">{{ field.templateConditionHint }}</small>
            </article>
          </div>
          <div v-else>
            <ElTag v-for="field in initialTemplateFields" :key="field" size="small" effect="plain">
              {{ field }}
            </ElTag>
          </div>
          <small>用于项目开始前建单，只放能从清单导入的字段。</small>
          <div class="template-action-row">
            <ElButton size="small" type="primary" plain @click="emitTemplateAction('download', 'initial_work_orders')">
              下载初始接入模板
            </ElButton>
            <ElButton size="small" plain @click="emitTemplateAction('validate', 'initial_work_orders')">
              校验初始接入模板
            </ElButton>
          </div>
        </section>
        <section>
          <span>系统外已完成模板</span>
          <div v-if="externalCompletedTemplateFieldRows.length" class="template-preview-field-list">
            <article v-for="field in externalCompletedTemplateFieldRows" :key="field.key">
              <strong>{{ field.label }}</strong>
              <span>{{ templateHierarchyHint(field) }}</span>
              <small v-if="field.templateParentLabel">父字段：{{ field.templateParentLabel }}</small>
              <small v-if="field.templateConditionHint">{{ field.templateConditionHint }}</small>
              <small v-else-if="field.platformFillRule">{{ field.platformFillRule }}</small>
            </article>
          </div>
          <div v-else>
            <ElTag v-for="field in externalCompletedTemplateFields" :key="field" size="small" type="warning" effect="plain">
              {{ field }}
            </ElTag>
          </div>
          <div v-if="platformGeneratedTemplateRows.length" class="platform-generated-template-list">
            <strong>上传时平台生成</strong>
            <article v-for="field in platformGeneratedTemplateRows" :key="field.key">
              <span>{{ field.label }}</span>
              <small>{{ field.helper }}</small>
            </article>
          </div>
          <small>用于把运行到一半的项目接入平台，系统字段按上传时生成。</small>
          <div class="template-action-row">
            <ElButton size="small" type="warning" plain @click="emitTemplateAction('download', 'external_completed')">
              下载系统外已完成模板
            </ElButton>
            <ElButton size="small" plain @click="emitTemplateAction('validate', 'external_completed')">
              校验系统外已完成模板
            </ElButton>
          </div>
        </section>
        <section>
          <span>现场必采清单</span>
          <div>
            <ElTag v-for="field in siteRequiredFields" :key="field" size="small" type="success" effect="plain">
              {{ field }}
            </ElTag>
            <ElTag v-if="!siteRequiredFields.length" size="small" type="info" effect="plain">
              暂无必采字段
            </ElTag>
          </div>
          <small>现场端需要扫码、拍照或录入的关键数据。</small>
        </section>
      </div>
      <div class="site-checklist-panel">
        <div>
          <strong>施工端必采</strong>
          <span>现场采集入口会按这些字段提醒施工人员补齐证据。</span>
        </div>
        <div>
          <ElTag v-for="field in siteChecklistFields" :key="field" size="small" type="success" effect="plain">
            {{ field }}
          </ElTag>
        </div>
        <small>平台仍会保留安装人员、安装时间、在线时间、照片数量、旧设备回收等 KPI 字段。</small>
      </div>
      <span class="template-binding-hint">模板下载和校验使用当前字段结构；保存配置后会成为项目正式模板规则。</span>
    </div>
  </section>
</template>

<style scoped>
.field-graph-designer {
  display: grid;
  gap: 14px;
  padding: 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.field-graph-header,
.field-graph-layout,
.field-graph-side,
.field-hierarchy-readiness-panel,
.field-backend-readiness-panel,
.field-smart-drop-panel,
.field-smart-drop-zones,
.field-group-list,
.selected-field-panel,
.template-binding-preview,
.template-binding-grid,
.field-tree,
.field-branch {
  min-width: 0;
}

.field-graph-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.field-graph-header > div,
.field-hierarchy-readiness-card,
.selected-field-panel,
.field-detail-form,
.field-detail-form label,
.template-binding-preview,
.template-binding-grid section,
.field-tree {
  display: grid;
  gap: 8px;
}

.field-graph-header strong,
.field-hierarchy-readiness-card strong,
.field-node strong,
.field-chip strong,
.selected-field-panel strong,
.template-binding-heading strong {
  color: var(--el-text-color-primary);
}

.field-graph-header span,
.field-hierarchy-readiness-card small,
.field-node span,
.field-node small,
.field-chip span,
.field-chip small,
.selected-field-panel span,
.selected-field-panel p,
.field-group-list span,
.template-binding-heading span,
.template-binding-grid span,
.template-binding-grid small,
.template-binding-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.field-graph-mode {
  flex: 0 0 auto;
  padding: 4px 8px;
  border: 1px solid var(--el-border-color);
  border-radius: 999px;
  background: #fff;
}

.field-hierarchy-readiness-panel {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.field-dashboard-metric-editor {
  display: grid;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.field-replacement-template-panel {
  display: grid;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.field-replacement-template-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.field-replacement-template-head > div {
  display: grid;
  gap: 3px;
}

.field-replacement-template-head strong {
  color: var(--v2-text-strong, #0f172a);
  font-size: 14px;
}

.field-replacement-template-head span {
  color: var(--v2-text-muted, #64748b);
  font-size: 12px;
}

.field-replacement-template-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.field-replacement-template-card {
  display: grid;
  gap: 5px;
  min-height: 118px;
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #f8fafc;
  color: inherit;
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.field-replacement-template-card:hover:not(:disabled) {
  border-color: rgba(10, 114, 216, 0.32);
  box-shadow: var(--v2-shadow-raised, 0 1px 2px rgba(15, 26, 36, 0.05));
  transform: translateY(-1px);
}

.field-replacement-template-card span {
  color: var(--el-text-color-primary);
  font-size: 13px;
  font-weight: 700;
}

.field-replacement-template-card strong {
  color: var(--el-text-color-primary);
  font-size: 16px;
  line-height: 1.25;
}

.field-replacement-template-card small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.field-replacement-template-card.template-module {
  border-color: var(--el-color-success-light-7);
  background: var(--el-color-success-light-9);
}

.field-replacement-template-card.template-terminal {
  border-color: var(--el-color-danger-light-7);
  background: var(--el-color-danger-light-9);
}

.field-replacement-template-card.disabled {
  cursor: not-allowed;
  opacity: 0.62;
}

.field-dashboard-metric-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.field-dashboard-metric-head > div {
  display: grid;
  gap: 3px;
}

.field-dashboard-metric-head strong {
  color: var(--v2-text-strong, #0f172a);
  font-size: 14px;
}

.field-dashboard-metric-head span {
  color: var(--v2-text-muted, #64748b);
  font-size: 12px;
}

.field-dashboard-metric-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.dashboard-metric-editor-card {
  display: grid;
  gap: 5px;
  min-height: 112px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #f8fafc;
  color: inherit;
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.dashboard-metric-editor-card:hover:not(:disabled) {
  border-color: rgba(10, 114, 216, 0.32);
  box-shadow: var(--v2-shadow-raised, 0 1px 2px rgba(15, 26, 36, 0.05));
  transform: translateY(-1px);
}

.dashboard-metric-editor-card.selected {
  border-color: rgba(22, 163, 74, 0.32);
  background: var(--el-color-success-light-9);
}

.dashboard-metric-editor-card.disabled {
  cursor: default;
  opacity: 0.76;
}

.dashboard-metric-editor-card span {
  color: var(--v2-text-strong, #0f172a);
  font-size: 13px;
  font-weight: 760;
}

.dashboard-metric-editor-card strong {
  color: #0369a1;
  font-size: 18px;
  line-height: 1.1;
}

.dashboard-metric-editor-card small {
  color: var(--v2-text-muted, #64748b);
  font-size: 12px;
  line-height: 1.45;
}

.dashboard-metric-editor-card em {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  font-style: normal;
}

.dashboard-metric-editor-card i {
  padding: 2px 5px;
  border-radius: 999px;
  background: rgba(14, 165, 233, 0.1);
  color: #075985;
  font-size: 11px;
  font-style: normal;
  font-weight: 700;
}

.field-hierarchy-readiness-card {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.field-hierarchy-readiness-card > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.field-hierarchy-readiness-card strong {
  font-size: 13px;
}

.field-hierarchy-readiness-card small {
  overflow-wrap: anywhere;
}

.field-hierarchy-readiness-card.hierarchy-readiness-ready {
  border-color: var(--el-color-success-light-7);
  background: var(--el-color-success-light-9);
}

.field-hierarchy-readiness-card.hierarchy-readiness-blocked {
  border-color: var(--el-color-warning-light-5);
  background: var(--el-color-warning-light-9);
}

.field-backend-readiness-panel {
  display: grid;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.field-backend-readiness-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.field-backend-readiness-head > div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.field-backend-readiness-head strong,
.field-backend-readiness-issue strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
}

.field-backend-readiness-head span,
.field-backend-readiness-panel small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.field-backend-hierarchy-contract {
  display: grid;
  gap: 6px;
  padding: 9px;
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 8px;
  background: var(--el-color-primary-light-9);
}

.field-backend-hierarchy-contract strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
}

.field-backend-hierarchy-contract span {
  color: var(--el-text-color-regular);
  font-size: 12px;
  line-height: 1.45;
}

.field-backend-readiness-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.field-backend-readiness-issue {
  display: grid;
  gap: 8px;
  min-width: 0;
  padding: 9px;
  border: 1px solid var(--el-color-warning-light-5);
  border-radius: 8px;
  background: var(--el-color-warning-light-9);
}

.field-backend-readiness-issue > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.field-backend-readiness-issue > span {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.field-map-node.backend-issue-node {
  border-color: var(--el-color-danger);
  box-shadow: 0 0 0 2px var(--el-color-danger-light-8);
}

.field-graph-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(220px, 0.7fr);
  gap: 14px;
}

.field-mind-map {
  position: relative;
  display: grid;
  grid-template-columns: minmax(180px, 0.9fr) minmax(220px, 1fr) minmax(220px, 1fr);
  gap: 34px;
  min-height: 300px;
  overflow: hidden;
  padding: 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.field-map-connector {
  position: absolute;
  inset: 0;
  z-index: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.field-map-connector path {
  fill: none;
  stroke: var(--el-border-color);
  stroke-width: 2.4;
}

.field-map-connector-label {
  fill: var(--el-text-color-secondary);
  font-size: 13px;
  font-weight: 700;
  paint-order: stroke;
  pointer-events: none;
  stroke: #fff;
  stroke-width: 4px;
  text-anchor: middle;
}

.field-map-connector .aggregate-to-core {
  stroke: var(--el-color-primary-light-5);
}

.field-map-connector .core-to-device {
  stroke: var(--el-color-success-light-5);
}

.field-map-connector .main-replacement-link {
  stroke: var(--el-color-danger-light-5);
}

.field-map-connector .main-old-device-link {
  stroke: var(--el-color-danger-light-4);
}

.field-map-connector .accessory-confirm-link {
  stroke: var(--el-color-warning-light-5);
}

.field-map-connector .accessory-new-link {
  stroke: var(--el-color-success-light-5);
}

.field-map-connector .old-device-link {
  stroke: var(--el-color-info-light-5);
}

.field-map-connector .evidence-link {
  stroke: var(--el-color-success-light-7);
}

.field-map-connector .device-dependency {
  stroke: var(--el-color-warning-light-5);
  stroke-dasharray: 5 5;
}

.field-map-connector .conditional-link {
  stroke-width: 2;
}

.connector-label-core-parallel {
  fill: var(--el-color-primary);
}

.connector-label-task-device,
.main-replacement-link,
.main-old-device-link,
.accessory-confirm-link,
.accessory-new-link,
.old-device-link,
.evidence-link {
  fill: var(--el-text-color-primary);
}

.conditional-link-label {
  fill: var(--el-color-warning-dark-2);
}

.field-map-connector-label.main-replacement-link,
.field-map-connector-label.main-old-device-link,
.field-map-connector-label.accessory-confirm-link,
.field-map-connector-label.accessory-new-link,
.field-map-connector-label.old-device-link,
.field-map-connector-label.evidence-link {
  stroke: #fff;
}

.field-map-legend {
  position: absolute;
  top: 10px;
  right: 12px;
  z-index: 2;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
  max-width: min(480px, calc(100% - 24px));
  pointer-events: none;
}

.field-map-legend span,
.field-map-relation-summary span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.94);
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 700;
  line-height: 1.3;
  white-space: nowrap;
}

.field-map-legend span {
  padding: 5px 8px;
}

.field-map-legend i {
  display: inline-block;
  width: 22px;
  height: 0;
  border-top: 2px solid var(--el-border-color);
}

.field-map-legend .legend-core-parallel i {
  border-color: var(--el-color-primary-light-5);
}

.field-map-legend .legend-task-device i {
  border-color: var(--el-color-success-light-5);
}

.field-map-legend .legend-conditional i {
  border-color: var(--el-color-warning-light-5);
  border-top-style: dashed;
}

.field-replacement-mode-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  padding: 0 2px;
}

.field-replacement-mode-eyebrow {
  grid-column: 1 / -1;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 700;
}

.field-replacement-mode-cards article {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.94);
}

.field-replacement-mode-cards strong {
  color: var(--el-text-color-primary);
  font-size: 16px;
  line-height: 1.25;
}

.field-replacement-mode-cards span {
  color: var(--el-text-color-primary);
  font-size: 13px;
  font-weight: 700;
  line-height: 1.35;
}

.field-replacement-mode-cards small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.field-replacement-mode-cards .replacement-mode-main {
  border-color: var(--el-color-danger-light-7);
  background: var(--el-color-danger-light-9);
}

.field-replacement-mode-cards .replacement-mode-accessory {
  border-color: var(--el-color-success-light-7);
  background: var(--el-color-success-light-9);
}

.field-replacement-mode-cards .replacement-mode-confirm,
.field-replacement-mode-cards .replacement-mode-conditional {
  border-color: var(--el-color-warning-light-7);
  background: var(--el-color-warning-light-9);
}

.field-map-relation-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 0 2px;
}

.field-map-relation-summary span {
  padding: 7px 10px;
}

.field-map-relation-summary strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
}

.field-map-relation-summary .summary-main-device {
  border-color: var(--el-color-danger-light-7);
  background: var(--el-color-danger-light-9);
}

.field-map-relation-summary .summary-accessory-confirm,
.field-map-relation-summary .summary-conditional {
  border-color: var(--el-color-warning-light-7);
  background: var(--el-color-warning-light-9);
}

.field-smart-drop-panel {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.field-smart-drop-guide,
.field-smart-drop-zones {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.field-smart-drop-guide span {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 3px 8px;
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 999px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary-dark-2);
  font-size: 12px;
  font-weight: 700;
  line-height: 1.35;
}

.field-device-hierarchy-guide {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 8px 14px;
}

.field-device-hierarchy-guide article {
  display: grid;
  min-width: 0;
  gap: 4px;
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.field-device-hierarchy-guide strong {
  color: var(--el-text-color-primary);
  font-size: 12px;
  line-height: 1.35;
}

.field-device-hierarchy-guide span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.field-smart-drop-zone {
  display: grid;
  align-content: start;
  gap: 4px;
  flex: 1 1 180px;
  min-width: 0;
  min-height: 76px;
  padding: 10px;
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

button.field-smart-drop-zone {
  font: inherit;
  text-align: left;
}

.field-smart-drop-zone.tap-enabled {
  cursor: pointer;
  box-shadow: inset 0 0 0 1px var(--el-color-primary-light-6);
}

.field-smart-drop-zone.tap-disabled {
  cursor: default;
  opacity: 0.82;
}

.field-smart-drop-zone:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}

.field-smart-drop-zone strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
  line-height: 1.35;
}

.field-smart-drop-zone small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.4;
}

.main-device-drop {
  border-color: var(--el-color-danger-light-5);
  background: var(--el-color-danger-light-9);
}

.accessory-confirm-drop,
.conditional-accessory-drop {
  border-color: var(--el-color-warning-light-5);
  background: var(--el-color-warning-light-9);
}

.task-core-drop {
  border-color: var(--el-color-primary-light-6);
  background: var(--el-color-primary-light-9);
}

.field-map-layer {
  position: relative;
  z-index: 1;
  display: grid;
  align-content: center;
  gap: 8px;
  min-width: 0;
}

.field-map-layer > span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 700;
}

.field-map-node {
  display: grid;
  gap: 4px;
  min-width: 0;
  min-height: 72px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
  cursor: pointer;
  text-align: left;
}

.field-map-node strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.field-map-node small,
.field-map-node em {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-style: normal;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.aggregate-node {
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
}

.core-parallel {
  border-color: var(--el-color-warning-light-6);
}

.device-child {
  border-color: var(--el-color-success-light-6);
}

.main-replacement-child {
  border-color: var(--el-color-danger-light-5);
  background: var(--el-color-danger-light-9);
}

.accessory-confirm-child {
  border-color: var(--el-color-warning-light-5);
  background: var(--el-color-warning-light-9);
}

.accessory-new-child {
  border-color: var(--el-color-success-light-5);
  background: var(--el-color-success-light-9);
}

.old-device-child {
  border-color: var(--el-color-info-light-5);
  background: var(--el-color-info-light-9);
}

.main-old-device-child {
  border-color: var(--el-color-danger-light-5);
  background: var(--el-color-danger-light-9);
}

.evidence-child {
  background: var(--el-color-success-light-9);
}

.conditional-child {
  box-shadow: inset 3px 0 0 var(--el-color-warning-light-4);
}

.field-map-node.selected {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 2px var(--el-color-primary-light-8);
}

.field-tree {
  position: relative;
}

.field-node,
.field-chip,
.selected-field-panel,
.field-group-list section {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.field-node {
  display: grid;
  gap: 4px;
  padding: 12px;
}

.field-node-root {
  border-color: var(--el-color-primary-light-5);
}

.field-node-primary {
  margin-top: 12px;
  border-color: var(--el-color-success-light-5);
}

.drop-enabled {
  outline: 1px dashed transparent;
}

.drop-enabled:hover {
  outline-color: var(--el-color-primary);
}

.field-branch {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 0 0 18px;
}

.primary-branch {
  padding-bottom: 2px;
}

.field-chip {
  display: grid;
  gap: 3px;
  width: min(210px, 100%);
  padding: 10px;
  cursor: pointer;
}

.field-chip[draggable='true'] {
  cursor: grab;
}

.field-chip.required {
  border-color: var(--el-color-warning-light-5);
}

.field-graph-side {
  display: grid;
  align-content: start;
  gap: 12px;
}

.field-group-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.field-group-list section {
  display: grid;
  gap: 4px;
  padding: 10px;
}

.field-group-list strong {
  color: var(--el-text-color-primary);
  font-size: 18px;
}

.selected-field-panel {
  padding: 12px;
}

.field-node.selected,
.field-chip.selected {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 2px var(--el-color-primary-light-8);
}

.selected-field-panel p {
  margin: 0;
}

.field-detail-form {
  padding-top: 4px;
}

.field-detail-form label > span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.conditional-required-row small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.condition-summary-card {
  display: grid;
  gap: 4px;
  padding: 8px 10px;
  border: 1px solid var(--el-color-warning-light-6);
  border-radius: 8px;
  background: var(--el-color-warning-light-9);
}

.condition-summary-card strong,
.condition-summary-card span {
  color: var(--el-text-color-primary);
  font-size: 12px;
  line-height: 1.45;
}

.field-hierarchy-hint-card {
  display: grid;
  gap: 4px;
  padding: 9px 10px;
  border: 1px solid var(--el-color-warning-light-6);
  border-radius: 8px;
  background: var(--el-color-warning-light-9);
}

.field-hierarchy-hint-card strong {
  color: var(--el-text-color-primary);
  font-size: 12px;
  line-height: 1.35;
}

.field-hierarchy-hint-card span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.field-detail-switch {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.field-drop-zone {
  display: grid;
  align-content: center;
  gap: 3px;
  width: min(210px, 100%);
  min-height: 68px;
  padding: 10px;
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  background: var(--el-fill-color);
}

.field-drop-zone span {
  color: var(--el-text-color-primary);
  font-size: 13px;
  font-weight: 700;
}

.field-drop-zone small,
.field-role-row small,
.field-role-heading span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.field-role-buckets {
  display: grid;
  gap: 8px;
}

.field-role-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.field-role-heading strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
}

.field-role-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 2px 8px;
  width: 100%;
  padding: 9px 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  text-align: left;
}

.field-role-row span,
.field-role-row strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
}

.field-role-row small {
  grid-column: 1 / -1;
}

.template-binding-preview {
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.template-binding-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.template-impact-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.template-impact-summary article {
  display: grid;
  gap: 4px;
  min-width: 0;
  min-height: 92px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.template-impact-summary span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 700;
}

.template-impact-summary strong {
  color: var(--el-text-color-primary);
  font-size: 18px;
  line-height: 1.2;
}

.template-impact-summary small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.4;
}

.template-impact-summary .impact-initial {
  border-color: var(--el-color-primary-light-7);
  background: var(--el-color-primary-light-9);
}

.template-impact-summary .impact-completed {
  border-color: var(--el-color-warning-light-7);
  background: var(--el-color-warning-light-9);
}

.template-impact-summary .impact-platform {
  border-color: var(--el-color-success-light-7);
  background: var(--el-color-success-light-9);
}

.template-download-guide {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.template-download-guide article {
  display: grid;
  gap: 4px;
  min-width: 0;
  min-height: 96px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.template-download-guide span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 700;
}

.template-download-guide strong {
  color: var(--el-text-color-primary);
  font-size: 14px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.template-download-guide small,
.template-download-guide em {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-style: normal;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.template-download-guide .download-guide-workbook {
  border-color: var(--el-color-info-light-6);
  background: var(--el-color-info-light-9);
}

.template-download-guide .download-guide-hierarchy {
  border-color: var(--el-color-warning-light-6);
  background: var(--el-color-warning-light-9);
}

.template-binding-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.template-binding-grid section {
  align-content: start;
  min-height: 116px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.template-binding-grid section > div {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.template-preview-field-list {
  display: grid !important;
  gap: 6px;
}

.template-preview-field-list article {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 8px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.template-preview-field-list strong {
  color: var(--el-text-color-primary);
  font-size: 12px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.template-preview-field-list span {
  width: fit-content;
  max-width: 100%;
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary-dark-2);
  font-size: 11px;
  font-weight: 700;
  line-height: 1.35;
}

.template-preview-field-list small {
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.platform-generated-template-list {
  display: grid !important;
  gap: 6px;
  width: 100%;
  padding: 8px;
  border: 1px solid var(--el-color-success-light-7);
  border-radius: 8px;
  background: var(--el-color-success-light-9);
}

.platform-generated-template-list strong {
  color: var(--el-color-success-dark-2);
  font-size: 12px;
}

.platform-generated-template-list article {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.platform-generated-template-list span {
  padding: 0;
  background: transparent;
  color: var(--el-text-color-primary);
  font-size: 12px;
  font-weight: 700;
}

.platform-generated-template-list small {
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 1.35;
}

.template-action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.site-checklist-panel {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--el-color-success-light-5);
  border-radius: 8px;
  background: var(--el-color-success-light-9);
}

.site-checklist-panel > div:first-child {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.site-checklist-panel strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
}

.site-checklist-panel span,
.site-checklist-panel small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.site-checklist-panel > div:last-of-type {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

@media (max-width: 760px) {
  .field-mind-map {
    grid-template-columns: 1fr;
    min-height: 0;
  }

  .field-map-connector {
    display: none;
  }

  .field-graph-layout,
  .field-group-list,
  .field-replacement-template-grid,
  .field-dashboard-metric-grid,
  .field-hierarchy-readiness-panel,
  .field-backend-readiness-list,
  .template-impact-summary,
  .template-download-guide,
  .template-binding-grid {
    grid-template-columns: 1fr;
  }

  .field-chip {
    width: 100%;
  }
}
</style>
