<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import {
  confirmProjectTemplateImportBatch,
  createImportBatchWorkOrderTask,
  createProjectTemplateImportDraft,
  downloadProjectTemplate,
  executeImportWorkOrderTask,
  fetchPlatformHandoffReadiness,
  fetchPlatformMigrationReadiness,
  fetchPlatformPersistenceStatus,
  fetchProjectConfigPersistenceContract,
  fetchProjectConfigPreflight,
  fetchProjectReadiness,
  fetchProjectReadinessSummary,
  fetchProjectWorkflow,
  previewProjectTemplateFields,
  rollbackImportWorkOrderTask,
  resetProjectWorkflow,
  saveProjectWorkflow,
  validateProjectTemplate,
} from '@/api/services'
import FieldGraphDesigner from '@/components/project-fields/FieldGraphDesigner.vue'
import WorkflowEditor from '@/components/project-workflow/WorkflowEditor.vue'
import { useWorkspaceStore } from '@/stores/workspace'
import type {
  Project,
  ProjectCaptureMethod,
  PlatformConfigPreflight,
  ProjectConfigPersistenceContract,
  ProjectFieldDataType,
  ProjectFieldDefinition,
  ProjectFieldSource,
  PlatformMigrationReadiness,
  PlatformPersistenceStatus,
  ProjectReadiness,
  ProjectReadinessCheck,
  ProjectReadinessSummaryItem,
  ProjectReadinessSummaryList,
  ProjectDashboardMetric,
  ImportJob,
  ProjectModule,
  ProjectTemplateFieldPreview,
  ProjectTemplatePreviewField,
  ProjectTemplateValidationItem,
  ProjectTemplateValidationReport,
  ProjectTemplateType,
  ProjectWorkflow,
  ProjectWorkItemSchema,
  PlatformHandoffReadiness,
} from '@/api/types'

type CreateFieldForm = {
  key: string
  label: string
  dataType: ProjectFieldDataType
  source: ProjectFieldSource
  captureMethod: ProjectCaptureMethod
  required: boolean
  parentKey: string
  kpiEnabled: boolean
  showInConstructionPanel: boolean
  options?: string[]
  requiredWhen?: ProjectFieldDefinition['requiredWhen']
  relationRole?: ProjectFieldDefinition['relationRole']
}

type WorkItemSchemaForm = {
  primaryField: CreateFieldForm
  aggregateField: CreateFieldForm
  customFields: CreateFieldForm[]
  dashboardMetrics: ProjectDashboardMetric[]
}

type CreateProjectForm = WorkItemSchemaForm & {
  name: string
  description: string
  moduleIds: string[]
}

type FieldPreset = {
  key: string
  label: string
  dataType: ProjectFieldDataType
  source: ProjectFieldSource
  captureMethod: ProjectCaptureMethod
  group?: 'primary' | 'aggregate' | 'shared'
  options?: string[]
  relationRole?: ProjectFieldDefinition['relationRole']
}

type SchemaReadinessCard = {
  title: string
  value: string
  note: string
  type: 'success' | 'warning' | 'info'
}

type TemplateActionOption = {
  command: string
  label: string
  divided?: boolean
}

type TemplateUsageCard = {
  type: ProjectTemplateType
  title: string
  badge: string
  description: string
  route: string
}

type ImportDraftHierarchyGapItem = {
  row: number | null
  fieldKey: string
  fieldLabel: string
  message: string
  value: string
}

type ImportWizardStepCard = {
  title: string
  description: string
  state: 'done' | 'active' | 'pending'
}

type ProjectTypePreset = {
  id: string
  name: string
  description: string
  primaryField: CreateFieldForm
  aggregateField: CreateFieldForm
  customFields: CreateFieldForm[]
}

type ProjectTypePresetGuidance = {
  title: string
  badge: string
  primary: string
  aggregate: string
  hierarchy: string
  aggregateRule: string
  helper: string
}

type ReplacementHierarchyTemplateId = 'module-replacement' | 'terminal-replacement'

const workspace = useWorkspaceStore()
const route = useRoute()
const router = useRouter()
const fallbackModules: ProjectModule[] = [
  { id: 'progress', name: '项目进度', priority: 10, endpoint: '', routePath: '/project-board' },
  { id: 'delivery', name: '项目交付能力', priority: 20, endpoint: '', routePath: '/project-board' },
  { id: 'field', name: '现场采集', priority: 30, endpoint: '', routePath: '/construction' },
  { id: 'review', name: '审阅功能', priority: 40, endpoint: '', routePath: '/task-hall' },
]
const defaultModuleIds = ['progress', 'delivery', 'field', 'review']
const replacementConfirmOptions = ['更换', '不更换', '待确认']
const commonFieldPresets: FieldPreset[] = [
  { key: 'meter_no', label: '电能表', dataType: 'text', source: 'import', captureMethod: 'manual', relationRole: 'task_object' },
  { key: 'terminal_no', label: '终端', dataType: 'text', source: 'import', captureMethod: 'manual', relationRole: 'task_object' },
  { key: 'area_no', label: '台区', dataType: 'text', source: 'import', captureMethod: 'manual', relationRole: 'aggregate' },
  { key: 'station_area', label: '台区', dataType: 'text', source: 'import', captureMethod: 'manual', relationRole: 'aggregate' },
  { key: 'master_meter_no', label: '总表', dataType: 'text', source: 'import', captureMethod: 'manual', relationRole: 'task_detail' },
  { key: 'user_no', label: '用户', dataType: 'text', source: 'import', captureMethod: 'manual', relationRole: 'task_detail' },
  { key: 'address', label: '地址', dataType: 'text', source: 'import', captureMethod: 'manual', relationRole: 'task_detail' },
  { key: 'line_no', label: '线路', dataType: 'text', source: 'import', captureMethod: 'manual', relationRole: 'aggregate' },
  { key: 'power_supply_unit', label: '供电所', dataType: 'text', source: 'import', captureMethod: 'manual', relationRole: 'aggregate' },
]
const terminalAggregateFieldPresetOptions: FieldPreset[] = [
  { key: 'area_no', label: '台区', dataType: 'text', source: 'import', captureMethod: 'manual', group: 'aggregate', relationRole: 'aggregate' },
  { key: 'region_name', label: '地区', dataType: 'text', source: 'import', captureMethod: 'manual', group: 'aggregate', relationRole: 'aggregate' },
  { key: 'manufacturer_name', label: '厂家', dataType: 'text', source: 'import', captureMethod: 'manual', group: 'aggregate', relationRole: 'aggregate' },
]
const terminalTaskCoreFieldPresetOptions: FieldPreset[] = [
  { key: 'terminal_address', label: '终端地址', dataType: 'text', source: 'import', captureMethod: 'manual', group: 'primary', relationRole: 'task_detail' },
]
const terminalDeviceHierarchyFieldDefaults: CreateFieldForm[] = [
  {
    key: 'old_device_no',
    label: '旧终端/旧设备（拆回）',
    dataType: 'text',
    source: 'field_collection',
    captureMethod: 'scan',
    required: true,
    parentKey: 'terminal_no',
    kpiEnabled: false,
    showInConstructionPanel: true,
    relationRole: 'old_device',
  },
  {
    key: 'new_terminal_no',
    label: '新终端号（安装后扫码）',
    dataType: 'text',
    source: 'field_collection',
    captureMethod: 'scan',
    required: true,
    parentKey: 'terminal_no',
    kpiEnabled: false,
    showInConstructionPanel: true,
    relationRole: 'replacement_device',
  },
  {
    key: 'communication_module_replace_confirm',
    label: '通讯模块是否更换',
    dataType: 'enum',
    source: 'field_collection',
    captureMethod: 'select',
    required: true,
    parentKey: 'terminal_no',
    kpiEnabled: false,
    showInConstructionPanel: true,
    options: replacementConfirmOptions,
    relationRole: 'accessory_replace_confirm',
  },
  {
    key: 'old_communication_module_no',
    label: '旧通讯模块号（更换时扫码）',
    dataType: 'text',
    source: 'field_collection',
    captureMethod: 'scan',
    required: false,
    parentKey: 'terminal_no',
    kpiEnabled: false,
    showInConstructionPanel: true,
    relationRole: 'old_device',
    requiredWhen: { fieldKey: 'communication_module_replace_confirm', equals: '更换' },
  },
  {
    key: 'communication_module_no',
    label: '新通讯模块号（更换时扫码）',
    dataType: 'text',
    source: 'field_collection',
    captureMethod: 'scan',
    required: false,
    parentKey: 'terminal_no',
    kpiEnabled: false,
    showInConstructionPanel: true,
    relationRole: 'accessory_new_device',
    requiredWhen: { fieldKey: 'communication_module_replace_confirm', equals: '更换' },
  },
  {
    key: 'sim_card_replace_confirm',
    label: 'SIM卡是否更换',
    dataType: 'enum',
    source: 'field_collection',
    captureMethod: 'select',
    required: true,
    parentKey: 'terminal_no',
    kpiEnabled: false,
    showInConstructionPanel: true,
    options: replacementConfirmOptions,
    relationRole: 'accessory_replace_confirm',
  },
  {
    key: 'old_sim_card_no',
    label: '旧SIM卡号（更换时录入）',
    dataType: 'text',
    source: 'field_collection',
    captureMethod: 'manual',
    required: false,
    parentKey: 'terminal_no',
    kpiEnabled: false,
    showInConstructionPanel: true,
    relationRole: 'old_device',
    requiredWhen: { fieldKey: 'sim_card_replace_confirm', equals: '更换' },
  },
  {
    key: 'new_sim_card_no',
    label: '新SIM卡号（更换时录入）',
    dataType: 'text',
    source: 'field_collection',
    captureMethod: 'manual',
    required: false,
    parentKey: 'terminal_no',
    kpiEnabled: false,
    showInConstructionPanel: true,
    relationRole: 'accessory_new_device',
    requiredWhen: { fieldKey: 'sim_card_replace_confirm', equals: '更换' },
  },
  {
    key: 'before_reform_photo',
    label: '改造前照片',
    dataType: 'image',
    source: 'field_collection',
    captureMethod: 'photo',
    required: true,
    parentKey: 'terminal_no',
    kpiEnabled: false,
    showInConstructionPanel: true,
    relationRole: 'evidence_photo',
  },
  {
    key: 'old_device_recovery_photo',
    label: '旧设备回收照片',
    dataType: 'image',
    source: 'field_collection',
    captureMethod: 'photo',
    required: true,
    parentKey: 'terminal_no',
    kpiEnabled: false,
    showInConstructionPanel: true,
    relationRole: 'evidence_photo',
  },
  {
    key: 'old_new_module_photo',
    label: '新旧模块照片',
    dataType: 'image',
    source: 'field_collection',
    captureMethod: 'photo',
    required: true,
    parentKey: 'terminal_no',
    kpiEnabled: false,
    showInConstructionPanel: true,
    relationRole: 'evidence_photo',
    requiredWhen: { fieldKey: 'communication_module_replace_confirm', equals: '更换' },
  },
  {
    key: 'after_reform_photo',
    label: '改造后照片',
    dataType: 'image',
    source: 'field_collection',
    captureMethod: 'photo',
    required: true,
    parentKey: 'terminal_no',
    kpiEnabled: false,
    showInConstructionPanel: true,
    relationRole: 'evidence_photo',
  },
]
const projectTypePresets: ProjectTypePreset[] = [
  {
    id: 'module-replacement',
    name: '更换模块',
    description: '适用于以电能表为任务对象，在任务对象下更换模块并确认采集器等附属设备状态。',
    primaryField: {
      key: 'meter_no',
      label: '电能表',
      dataType: 'text',
      source: 'import',
      captureMethod: 'manual',
      required: true,
      parentKey: '',
      kpiEnabled: false,
      showInConstructionPanel: true,
      relationRole: 'task_object',
    },
    aggregateField: {
      key: 'area_no',
      label: '台区',
      dataType: 'text',
      source: 'import',
      captureMethod: 'manual',
      required: true,
      parentKey: '',
      kpiEnabled: false,
      showInConstructionPanel: true,
      relationRole: 'aggregate',
    },
    customFields: [
      {
        key: 'old_module_no',
        label: '旧模块号（拆回扫码）',
        dataType: 'text',
        source: 'field_collection',
        captureMethod: 'scan',
        required: true,
        parentKey: 'meter_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        relationRole: 'old_device',
      },
      {
        key: 'module_asset_no',
        label: '模块（需更换）',
        dataType: 'text',
        source: 'field_collection',
        captureMethod: 'scan',
        required: true,
        parentKey: 'meter_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        relationRole: 'accessory_new_device',
      },
      {
        key: 'collector_replace_confirm',
        label: '采集器（确认是否更换）',
        dataType: 'enum',
        source: 'field_collection',
        captureMethod: 'select',
        required: true,
        parentKey: 'meter_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        options: replacementConfirmOptions,
        relationRole: 'accessory_replace_confirm',
      },
      {
        key: 'old_collector_no',
        label: '旧采集器号（更换时扫码）',
        dataType: 'text',
        source: 'field_collection',
        captureMethod: 'scan',
        required: false,
        parentKey: 'meter_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        relationRole: 'old_device',
        requiredWhen: { fieldKey: 'collector_replace_confirm', equals: '更换' },
      },
      {
        key: 'collector_no',
        label: '新采集器号（更换时扫码）',
        dataType: 'text',
        source: 'field_collection',
        captureMethod: 'scan',
        required: false,
        parentKey: 'meter_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        relationRole: 'accessory_new_device',
        requiredWhen: { fieldKey: 'collector_replace_confirm', equals: '更换' },
      },
    ],
  },
  {
    id: 'terminal-replacement',
    name: '更换终端',
    description: '适用于以终端为主对象，现场更换终端并确认通讯模块、SIM 卡等附属设备是否同步更换。',
    primaryField: {
      key: 'terminal_no',
      label: '终端（需更换）',
      dataType: 'text',
      source: 'import',
      captureMethod: 'manual',
      required: true,
      parentKey: '',
      kpiEnabled: false,
      showInConstructionPanel: true,
      relationRole: 'task_object',
    },
    aggregateField: {
      key: 'area_no',
      label: '台区',
      dataType: 'text',
      source: 'import',
      captureMethod: 'manual',
      required: true,
      parentKey: '',
      kpiEnabled: false,
      showInConstructionPanel: true,
      relationRole: 'aggregate',
    },
    customFields: [
      {
        key: 'terminal_address',
        label: '终端地址',
        dataType: 'text',
        source: 'import',
        captureMethod: 'manual',
        required: true,
        parentKey: 'terminal_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        relationRole: 'task_detail',
      },
      {
        key: 'region_name',
        label: '地区',
        dataType: 'text',
        source: 'import',
        captureMethod: 'manual',
        required: false,
        parentKey: 'terminal_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        relationRole: 'task_detail',
      },
      {
        key: 'manufacturer_name',
        label: '厂家',
        dataType: 'text',
        source: 'import',
        captureMethod: 'manual',
        required: false,
        parentKey: 'terminal_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        relationRole: 'task_detail',
      },
      {
        key: 'old_device_no',
        label: '旧终端/旧设备（拆回）',
        dataType: 'text',
        source: 'field_collection',
        captureMethod: 'scan',
        required: true,
        parentKey: 'terminal_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        relationRole: 'old_device',
      },
      {
        key: 'new_terminal_no',
        label: '新终端号（安装后扫码）',
        dataType: 'text',
        source: 'field_collection',
        captureMethod: 'scan',
        required: true,
        parentKey: 'terminal_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        relationRole: 'replacement_device',
      },
      {
        key: 'communication_module_replace_confirm',
        label: '通讯模块是否更换',
        dataType: 'enum',
        source: 'field_collection',
        captureMethod: 'select',
        required: true,
        parentKey: 'terminal_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        options: replacementConfirmOptions,
        relationRole: 'accessory_replace_confirm',
      },
      {
        key: 'old_communication_module_no',
        label: '旧通讯模块号（更换时扫码）',
        dataType: 'text',
        source: 'field_collection',
        captureMethod: 'scan',
        required: false,
        parentKey: 'terminal_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        relationRole: 'old_device',
        requiredWhen: { fieldKey: 'communication_module_replace_confirm', equals: '更换' },
      },
      {
        key: 'communication_module_no',
        label: '新通讯模块号（更换时扫码）',
        dataType: 'text',
        source: 'field_collection',
        captureMethod: 'scan',
        required: false,
        parentKey: 'terminal_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        relationRole: 'accessory_new_device',
        requiredWhen: { fieldKey: 'communication_module_replace_confirm', equals: '更换' },
      },
      {
        key: 'sim_card_replace_confirm',
        label: 'SIM卡是否更换',
        dataType: 'enum',
        source: 'field_collection',
        captureMethod: 'select',
        required: true,
        parentKey: 'terminal_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        options: replacementConfirmOptions,
        relationRole: 'accessory_replace_confirm',
      },
      {
        key: 'old_sim_card_no',
        label: '旧SIM卡号（更换时录入）',
        dataType: 'text',
        source: 'field_collection',
        captureMethod: 'manual',
        required: false,
        parentKey: 'terminal_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        relationRole: 'old_device',
        requiredWhen: { fieldKey: 'sim_card_replace_confirm', equals: '更换' },
      },
      {
        key: 'new_sim_card_no',
        label: '新SIM卡号（更换时录入）',
        dataType: 'text',
        source: 'field_collection',
        captureMethod: 'manual',
        required: false,
        parentKey: 'terminal_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        relationRole: 'accessory_new_device',
        requiredWhen: { fieldKey: 'sim_card_replace_confirm', equals: '更换' },
      },
      {
        key: 'before_reform_photo',
        label: '改造前照片',
        dataType: 'image',
        source: 'field_collection',
        captureMethod: 'photo',
        required: true,
        parentKey: 'terminal_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        relationRole: 'evidence_photo',
      },
      {
        key: 'old_device_recovery_photo',
        label: '旧设备回收照片',
        dataType: 'image',
        source: 'field_collection',
        captureMethod: 'photo',
        required: true,
        parentKey: 'terminal_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        relationRole: 'evidence_photo',
      },
      {
        key: 'old_new_module_photo',
        label: '新旧模块照片',
        dataType: 'image',
        source: 'field_collection',
        captureMethod: 'photo',
        required: true,
        parentKey: 'terminal_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        relationRole: 'evidence_photo',
        requiredWhen: { fieldKey: 'communication_module_replace_confirm', equals: '更换' },
      },
      {
        key: 'after_reform_photo',
        label: '改造后照片',
        dataType: 'image',
        source: 'field_collection',
        captureMethod: 'photo',
        required: true,
        parentKey: 'terminal_no',
        kpiEnabled: false,
        showInConstructionPanel: true,
        relationRole: 'evidence_photo',
      },
    ],
  },
]
projectTypePresets.push({
  id: 'line-loss-investigation',
  name: '台区线损排查',
  description: '适用于以台区为任务对象，按供电所或线路汇总，现场核查总表、用户和线损异常证据。',
  primaryField: {
    key: 'station_area_no',
    label: '台区',
    dataType: 'text',
    source: 'import',
    captureMethod: 'manual',
    required: true,
    parentKey: '',
    kpiEnabled: false,
    showInConstructionPanel: true,
    relationRole: 'task_object',
  },
  aggregateField: {
    key: 'power_supply_unit',
    label: '供电所',
    dataType: 'text',
    source: 'import',
    captureMethod: 'manual',
    required: true,
    parentKey: '',
    kpiEnabled: false,
    showInConstructionPanel: true,
    relationRole: 'aggregate',
  },
  customFields: [
    {
      key: 'master_meter_no',
      label: '总表',
      dataType: 'text',
      source: 'import',
      captureMethod: 'manual',
      required: true,
      parentKey: 'station_area_no',
      kpiEnabled: false,
      showInConstructionPanel: true,
      relationRole: 'task_detail',
    },
    {
      key: 'user_no',
      label: '用户',
      dataType: 'text',
      source: 'import',
      captureMethod: 'manual',
      required: true,
      parentKey: 'station_area_no',
      kpiEnabled: false,
      showInConstructionPanel: true,
      relationRole: 'task_detail',
    },
    {
      key: 'line_loss_issue_type',
      label: '线损异常类型',
      dataType: 'enum',
      source: 'field_collection',
      captureMethod: 'select',
      required: true,
      parentKey: 'station_area_no',
      kpiEnabled: false,
      showInConstructionPanel: true,
      options: ['表档不一致', '接线异常', '疑似窃电', '其他'],
      relationRole: 'supporting_field',
    },
    {
      key: 'master_meter_photo',
      label: '总表照片',
      dataType: 'image',
      source: 'field_collection',
      captureMethod: 'photo',
      required: true,
      parentKey: 'station_area_no',
      kpiEnabled: false,
      showInConstructionPanel: true,
      relationRole: 'evidence_photo',
    },
    {
      key: 'user_meter_sample_photo',
      label: '用户表抽查照片',
      dataType: 'image',
      source: 'field_collection',
      captureMethod: 'photo',
      required: true,
      parentKey: 'station_area_no',
      kpiEnabled: false,
      showInConstructionPanel: true,
      relationRole: 'evidence_photo',
    },
    {
      key: 'site_check_note',
      label: '现场核查说明',
      dataType: 'text',
      source: 'field_collection',
      captureMethod: 'manual',
      required: false,
      parentKey: 'station_area_no',
      kpiEnabled: false,
      showInConstructionPanel: true,
      relationRole: 'supporting_field',
    },
  ],
})

const templateDownloadOptions: Array<{ type: ProjectTemplateType; label: string }> = [
  { type: 'initial_work_orders', label: '初始接入模板' },
  { type: 'external_completed', label: '系统外已完成模板' },
]
const templateUsageCards: TemplateUsageCard[] = [
  {
    type: 'initial_work_orders',
    title: '初始接入模板',
    badge: '待施工',
    description: '用于运行到一半的项目接入平台，导入后继续派工、施工采集和审阅。',
    route: '导入字段 -> 施工采集 -> 审阅归档',
  },
  {
    type: 'external_completed',
    title: '系统外已完成模板',
    badge: '待审阅',
    description: '用于系统外已经完成，只需要接入审阅和归档；缺失的平台字段按上传时生成。',
    route: '已有结果 -> 审阅工作台 -> 交付归档',
  },
]
const templateActionOptions: TemplateActionOption[] = templateDownloadOptions.flatMap((option) => [
  { command: `download:${option.type}`, label: `下载${option.label}` },
  { command: `validate:${option.type}`, label: `校验${option.label}`, divided: true },
])
const sourceOptions: Array<{ value: ProjectFieldSource; label: string }> = [
  { value: 'import', label: '初始导入' },
  { value: 'field_collection', label: '现场采集' },
  { value: 'review', label: '审阅补录' },
]
const captureMethodOptions: Array<{ value: ProjectCaptureMethod; label: string }> = [
  { value: 'manual', label: '录入' },
  { value: 'scan', label: '扫码' },
  { value: 'photo', label: '拍照' },
  { value: 'select', label: '选择' },
  { value: 'datetime', label: '时间' },
  { value: 'location', label: '定位' },
]
const dataTypeOptions: Array<{ value: ProjectFieldDataType; label: string }> = [
  { value: 'text', label: '文本' },
  { value: 'number', label: '数字' },
  { value: 'datetime', label: '时间' },
  { value: 'image', label: '图片' },
  { value: 'enum', label: '选项' },
  { value: 'duration', label: '时长' },
  { value: 'location', label: '位置' },
]
const platformRequiredFields = [
  '工单编号',
  '安装人员',
  '安装时间',
  '完成时间',
  '在线时间',
  '在线时长',
  '照片数量',
  '扫码次数',
  '异常状态',
  '审阅人员',
]
const createDialogVisible = ref(false)
const creatingProject = ref(false)
const selectedProjectTypePresetId = ref('')
const schemaDialogVisible = ref(false)
const savingSchema = ref(false)
const schemaProject = ref<Project | null>(null)
const schemaTemplatePreview = ref<ProjectTemplateFieldPreview | null>(null)
const loadingSchemaTemplatePreview = ref(false)
const projectReadinessById = ref<Record<string, ProjectReadiness>>({})
const projectReadinessSummary = ref<ProjectReadinessSummaryList | null>(null)
const loadingProjectReadinessSummary = ref(false)
const selectedReadinessAction = ref('')
const platformHandoffReadiness = ref<PlatformHandoffReadiness | null>(null)
const loadingPlatformHandoffReadiness = ref(false)
const loadingReadinessProjectId = ref('')
const projectPersistenceStatus = ref<PlatformPersistenceStatus | null>(null)
const projectMigrationReadiness = ref<PlatformMigrationReadiness | null>(null)
const projectPersistenceContractsById = ref<Record<string, ProjectConfigPersistenceContract>>({})
const loadingPersistenceReadinessProjectId = ref('')
const projectConfigPreflight = ref<PlatformConfigPreflight | null>(null)
const loadingProjectConfigPreflight = ref(false)
const workflowDialogVisible = ref(false)
const workflowProject = ref<Project | null>(null)
const projectWorkflow = ref<ProjectWorkflow | null>(null)
const loadingWorkflow = ref(false)
const savingWorkflow = ref(false)
const resettingWorkflow = ref(false)
const templateFileInput = ref<HTMLInputElement | null>(null)
const pendingValidationProject = ref<Project | null>(null)
const pendingValidationTemplateType = ref<ProjectTemplateType>('external_completed')
const validatingTemplate = ref(false)
const validationDialogVisible = ref(false)
const templateValidationReport = ref<ProjectTemplateValidationReport | null>(null)
const validatedTemplateFile = ref<File | null>(null)
const creatingImportDraft = ref(false)
const importDraftJob = ref<ImportJob | null>(null)
const confirmingImportBatch = ref(false)
const importBatchJob = ref<ImportJob | null>(null)
const creatingWorkOrderTask = ref(false)
const executingWorkOrderTask = ref(false)
const rollingBackWorkOrderTask = ref(false)
const workOrderTaskJob = ref<ImportJob | null>(null)
const validationProjectName = ref('')
const validationTemplateType = ref<ProjectTemplateType>('external_completed')
const createForm = reactive<CreateProjectForm>({
  name: '',
  description: '',
  moduleIds: [...defaultModuleIds],
  primaryField: defaultPrimaryField(),
  aggregateField: defaultAggregateField(),
  customFields: [
    {
      ...defaultCustomField('module_asset_no', '模块（需更换）', 'scan'),
      required: true,
      relationRole: 'accessory_new_device',
    },
    {
      ...defaultCustomField('collector_replace_confirm', '采集器（确认是否更换）', 'select'),
      required: true,
      options: replacementConfirmOptions,
      relationRole: 'accessory_replace_confirm',
    },
  ],
  dashboardMetrics: [],
})
const schemaForm = reactive<WorkItemSchemaForm>({
  primaryField: defaultPrimaryField(),
  aggregateField: defaultAggregateField(),
  customFields: [
    {
      ...defaultCustomField('module_asset_no', '模块（需更换）', 'scan'),
      required: true,
      relationRole: 'accessory_new_device',
    },
  ],
  dashboardMetrics: [],
})

const moduleOptions = computed(() => {
  const knownModules = workspace.projects.flatMap((project) => project.modules)
  const modules = knownModules.length ? knownModules : fallbackModules
  const uniqueModules = new Map(modules.map((module) => [module.id, module]))
  return Array.from(uniqueModules.values()).sort((left, right) => left.priority - right.priority)
})
const createSchemaReadinessCards = computed(() => schemaReadinessCards(createForm))
const schemaReadinessPreviewCards = computed(() => schemaReadinessCards(schemaForm))
const schemaProjectReadiness = computed(() => schemaProject.value ? projectReadinessById.value[schemaProject.value.id] : null)
const schemaDeviceHierarchyReadinessCheck = computed(() =>
  schemaProjectReadiness.value?.checks.find((check) => check.id === 'device_hierarchy') || null,
)
const schemaProjectPersistenceContract = computed(() =>
  schemaProject.value ? projectPersistenceContractsById.value[schemaProject.value.id] : null,
)
const projectConfigPersistenceStore = computed(() =>
  projectPersistenceStatus.value?.stores.find((store) => store.id === 'project_drafts') || null,
)
const projectPersistenceSafetyItems = computed(() =>
  Array.from(new Set([
    ...(projectPersistenceStatus.value?.safety || []),
    ...(schemaProjectPersistenceContract.value?.safety || []),
  ])).slice(0, 6),
)
const configPreflightBlockedProjects = computed(() =>
  (projectConfigPreflight.value?.projects || []).filter((project) => project.status === 'blocked').slice(0, 4),
)
const configPreflightSafetyItems = computed(() => (projectConfigPreflight.value?.safety || []).slice(0, 6))
const projectReadinessSummaryById = computed<Record<string, ProjectReadinessSummaryItem>>(() => {
  const entries = projectReadinessSummary.value?.items || []
  return Object.fromEntries(entries.map((item) => [item.projectId, item]))
})
const readinessSummaryBandText = computed(() => {
  if (loadingProjectReadinessSummary.value) return '检查中'
  const summary = projectReadinessSummary.value
  if (!summary) return '未检查'
  return `可接入 ${summary.ready} 个 · 需补齐 ${summary.notReady} 个`
})
const topReadinessActionCounts = computed(() =>
  (projectReadinessSummary.value?.actionCounts || []).slice(0, 4),
)
const filteredProjects = computed(() => {
  const action = selectedReadinessAction.value
  if (!action) return workspace.projects
  return workspace.projects.filter((project) =>
    (projectReadinessSummaryById.value[project.id]?.nextActions || []).includes(action),
  )
})
const readinessActionFilterText = computed(() => {
  const action = selectedReadinessAction.value
  if (!action) return ''
  return readinessActionCountText(action)
})
const handoffReviewStatusText = computed(() => {
  if (loadingPlatformHandoffReadiness.value) return '读取中'
  if (!platformHandoffReadiness.value) return '待读取'
  return platformHandoffReadiness.value.readyForReviewPackage ? '可评审包' : '待补齐评审材料'
})
const handoffMigrationStatusText = computed(() => {
  if (loadingPlatformHandoffReadiness.value) return '检查中'
  if (!platformHandoffReadiness.value) return '待检查'
  return platformHandoffReadiness.value.readyForProductionMigration ? '生产迁移可申请' : '生产迁移未放行'
})
const handoffConfigPreflight = computed(() => platformHandoffReadiness.value?.configPreflight || null)
const handoffConfigPreflightText = computed(() => {
  if (loadingPlatformHandoffReadiness.value) return '检查中'
  const preflight = handoffConfigPreflight.value
  if (!preflight) return '待读取'
  if (!preflight.store.exists) return '无历史草稿'
  const blockers = preflight.summary.blockedProjects + preflight.summary.storeIssues
  if (preflight.readyForConfigLoad) return `通过 · ${preflight.summary.totalProjects} 个草稿`
  return `阻断 ${blockers || 1} 项`
})
const projectListConfigPreflight = computed(() => workspace.projectListConfigPreflight)
const projectListConfigPreflightText = computed(() => {
  const preflight = projectListConfigPreflight.value
  if (!preflight) return '待读取'
  if (!preflight.store.exists) return '无历史草稿'
  const blockers = preflight.summary.blockedProjects + preflight.summary.storeIssues
  if (preflight.readyForConfigLoad) return `通过 · ${preflight.summary.totalProjects} 个草稿`
  return `阻断 ${blockers || 1} 项`
})
const projectListConfigPreflightStoreIssues = computed(() =>
  (projectListConfigPreflight.value?.issues || []).slice(0, 3),
)
const projectListConfigPreflightBlockedProjects = computed(() =>
  (projectListConfigPreflight.value?.projects || [])
    .filter((project) => project.status === 'blocked')
    .slice(0, 4),
)
const showProjectListConfigPreflightDetails = computed(() =>
  projectListConfigPreflightStoreIssues.value.length > 0 ||
  projectListConfigPreflightBlockedProjects.value.length > 0,
)
const handoffNextActionText = computed(() => {
  const action = platformHandoffReadiness.value?.nextActions[0] || ''
  const labels: Record<string, string> = {
    fix_config_preflight_blockers: '修复配置预检阻断',
    prepare_pr_or_patch_handoff: '准备 PR 或 patch 交付',
    review_against_production_baseline: '按生产基线复核',
    keep_migration_blocked_until_user_approval: '等待迁移审批',
    run_browser_smoke_before_handoff: '完成页面冒烟',
  }
  return labels[action] || '等待交付检查'
})
const selectedProjectTypePresetGuidance = computed<ProjectTypePresetGuidance | null>(() => {
  const preset = projectTypePresets.find((item) => item.id === selectedProjectTypePresetId.value)
  if (!preset) return null
  if (preset.id === 'terminal-replacement') {
    return {
      title: '当前项目类型预设：更换终端',
      badge: '终端聚合口径',
      primary: '主字段：终端（需更换）',
      aggregate: '聚合字段：台区、地区或厂家',
      hierarchy: '主设备更换后确认附属设备',
      aggregateRule: '同一项目同时仅保留一种聚合字段',
      helper: '终端作为任务对象，先记录旧终端和新终端，再确认通讯模块、SIM卡等附属设备是否更换。',
    }
  }
  if (preset.id === 'module-replacement') {
    return {
      title: '当前项目类型预设：更换模块',
      badge: '电表任务对象',
      primary: '主字段：电能表',
      aggregate: '聚合字段：台区',
      hierarchy: '任务对象下更换附属设备',
      aggregateRule: '模块、采集器和照片证据都挂在同一任务对象下',
      helper: '电能表保持为任务对象，旧模块、新模块、采集器确认和照片证据围绕电能表展开。',
    }
  }
  return {
    title: `当前项目类型预设：${preset.name}`,
    badge: '通用项目',
    primary: `主字段：${preset.primaryField.label}`,
    aggregate: `聚合字段：${preset.aggregateField.label}`,
    hierarchy: '按任务对象组织字段',
    aggregateRule: '同一项目同时仅保留一种聚合字段',
    helper: preset.description,
  }
})
const createImportFieldLabels = computed(() => importFieldLabels(createForm))
const hierarchyValidationItems = computed(() =>
  (templateValidationReport.value?.items || []).filter((item) => item.code === 'missing_conditional_field'),
)
const schemaImportFieldLabels = computed(() => importFieldLabels(schemaForm))
const createFieldCollectionLabels = computed(() => fieldCollectionLabels(createForm))
const schemaFieldCollectionLabels = computed(() => fieldCollectionLabels(schemaForm))
const createRequiredFieldCollectionLabels = computed(() => requiredFieldCollectionLabels(createForm))
const schemaRequiredFieldCollectionLabels = computed(() => requiredFieldCollectionLabels(schemaForm))
const createRequiredPhotoLabels = computed(() => requiredPhotoLabels(createForm))
const schemaRequiredPhotoLabels = computed(() => requiredPhotoLabels(schemaForm))
const createExternalCompletedLabels = computed(() => externalCompletedFieldLabels(createForm))
const schemaExternalCompletedLabels = computed(() => externalCompletedFieldLabels(schemaForm))
const createTemplateBindingPreview = computed(() => ({
  initialWorkOrders: createImportFieldLabels.value,
  externalCompleted: createExternalCompletedLabels.value,
  siteRequiredFields: [...createRequiredFieldCollectionLabels.value, ...createRequiredPhotoLabels.value],
  initialWorkOrderFields: [] as ProjectTemplatePreviewField[],
  externalCompletedFields: [] as ProjectTemplatePreviewField[],
}))
const schemaTemplateBindingPreview = computed(() => {
  const preview = schemaTemplatePreview.value
  if (!preview) return null
  return {
    initialWorkOrders: templatePreviewHeaders(preview, 'initial_work_orders'),
    externalCompleted: templatePreviewHeaders(preview, 'external_completed'),
    siteRequiredFields: preview.siteRequiredFields,
    initialWorkOrderFields: templatePreviewFieldRows(preview, 'initial_work_orders'),
    externalCompletedFields: templatePreviewFieldRows(preview, 'external_completed'),
  }
})
const schemaInitialTemplatePreviewLabels = computed(
  () => schemaTemplateBindingPreview.value?.initialWorkOrders.length ? schemaTemplateBindingPreview.value.initialWorkOrders : schemaImportFieldLabels.value,
)
const schemaExternalCompletedPreviewLabels = computed(
  () => schemaTemplateBindingPreview.value?.externalCompleted.length ? schemaTemplateBindingPreview.value.externalCompleted : schemaExternalCompletedLabels.value,
)
const schemaSiteRequiredPreviewLabels = computed(() =>
  schemaTemplateBindingPreview.value?.siteRequiredFields.length
    ? schemaTemplateBindingPreview.value.siteRequiredFields
    : [...schemaRequiredFieldCollectionLabels.value, ...schemaRequiredPhotoLabels.value],
)

let schemaTemplatePreviewRequestId = 0
let schemaTemplatePreviewTimer: number | null = null

onMounted(() => {
  void loadProjectsFromRoute()
})

watch(schemaForm, () => {
  scheduleSchemaTemplatePreviewRefresh()
}, { deep: true })

async function refreshProjects() {
  await Promise.all([workspace.loadProjects(), loadPlatformHandoffReadiness()])
  selectRouteProject()
  await loadProjectReadinessSummary()
  ElMessage.success('项目状态已更新')
}

async function loadProjectsFromRoute() {
  await Promise.all([workspace.loadProjects(), loadPlatformHandoffReadiness()])
  selectRouteProject()
  await loadProjectReadinessSummary()
}

function selectRouteProject() {
  workspace.selectRouteProject(route.query.project_id)
}

function openCreateDialog() {
  createDialogVisible.value = true
}

function defaultPrimaryField(): CreateFieldForm {
  return {
    key: 'meter_no',
    label: '电能表',
    dataType: 'text',
    source: 'import',
    captureMethod: 'manual',
    required: true,
    parentKey: '',
    kpiEnabled: false,
    showInConstructionPanel: true,
    options: [],
    relationRole: 'task_object',
  }
}

function defaultAggregateField(): CreateFieldForm {
  return {
    key: 'area_no',
    label: '台区',
    dataType: 'text',
    source: 'import',
    captureMethod: 'manual',
    required: true,
    parentKey: '',
    kpiEnabled: false,
    showInConstructionPanel: true,
    options: [],
    relationRole: 'aggregate',
  }
}

function applyFieldPreset(field: CreateFieldForm, presetKey: string) {
  const preset = [...terminalAggregateFieldPresetOptions, ...commonFieldPresets].find((item) => item.key === presetKey)
  if (!preset) return
  field.key = preset.key
  field.label = preset.label
  field.dataType = preset.dataType
  field.source = preset.source
  field.captureMethod = preset.captureMethod
  field.required = true
  field.options = preset.options ? [...preset.options] : []
  field.relationRole = preset.relationRole
}

function primaryFieldPresetOptions() {
  return commonFieldPresets.filter((preset) => preset.group !== 'aggregate')
}

function aggregateFieldPresetOptions(form: WorkItemSchemaForm) {
  if (form.primaryField.key === 'terminal_no') {
    return terminalAggregateFieldPresetOptions
  }
  return commonFieldPresets.map((preset) => ({
    ...preset,
    group: preset.group || 'aggregate',
  }))
}

function terminalCoreFieldPresetOptions(form: WorkItemSchemaForm) {
  if (form.primaryField.key !== 'terminal_no') return []
  return [
    ...terminalTaskCoreFieldPresetOptions,
    ...terminalAggregateFieldPresetOptions.filter((preset) => preset.key !== form.aggregateField.key),
  ]
}

function syncTerminalCoreFields(form: WorkItemSchemaForm) {
  if (form.primaryField.key !== 'terminal_no') return
  const aggregateCandidateKeys = new Set(terminalAggregateFieldPresetOptions.map((preset) => preset.key))
  form.customFields = form.customFields.filter((field) => field.key !== form.aggregateField.key)
  for (const preset of terminalCoreFieldPresetOptions(form)) {
    if (form.customFields.some((field) => field.key === preset.key)) continue
    form.customFields.push({
      key: preset.key,
      label: preset.label,
      dataType: preset.dataType,
      source: preset.source,
      captureMethod: preset.captureMethod,
      required: false,
      parentKey: form.primaryField.key,
      kpiEnabled: false,
      showInConstructionPanel: true,
      options: preset.options ? [...preset.options] : [],
      relationRole: preset.relationRole || 'task_detail',
    })
  }
  for (const field of form.customFields) {
    if (aggregateCandidateKeys.has(field.key)) {
      field.source = 'import'
      field.captureMethod = 'manual'
      field.parentKey = form.primaryField.key
      field.relationRole = 'task_detail'
    }
  }
  syncTerminalDeviceHierarchyFields(form)
}

function syncTerminalDeviceHierarchyFields(form: WorkItemSchemaForm) {
  if (form.primaryField.key !== 'terminal_no') return
  const existingByKey = new Map(form.customFields.map((field) => [field.key, field]))
  for (const fieldDefault of terminalDeviceHierarchyFieldDefaults) {
    const existing = existingByKey.get(fieldDefault.key)
    if (!existing) {
      form.customFields.push(cloneFieldForm({ ...fieldDefault, parentKey: form.primaryField.key }))
      continue
    }
    existing.parentKey = form.primaryField.key
    existing.showInConstructionPanel = existing.showInConstructionPanel ?? fieldDefault.showInConstructionPanel
    if (fieldDefault.options?.length && !existing.options?.length) {
      existing.options = [...fieldDefault.options]
    }
    if (fieldDefault.requiredWhen && !existing.requiredWhen) {
      existing.requiredWhen = cloneRequiredWhen(fieldDefault.requiredWhen)
    }
    if (fieldDefault.relationRole && !existing.relationRole) {
      existing.relationRole = fieldDefault.relationRole
    }
    if (existing.key === 'old_device_no' && existing.label === '旧设备（拆回）') {
      existing.label = fieldDefault.label
    }
    if (existing.key === 'communication_module_no' && existing.label === '通讯模块（需更换）') {
      existing.label = fieldDefault.label
      existing.required = fieldDefault.required
    }
    if (existing.key === 'new_sim_card_no' && existing.label === '新SIM卡') {
      existing.label = fieldDefault.label
      existing.required = fieldDefault.required
    }
  }
}

function setExclusiveAggregateField(form: WorkItemSchemaForm, value: string | number | boolean) {
  applyFieldPreset(form.aggregateField, String(value))
  syncTerminalCoreFields(form)
}

function cloneFieldForm(field: CreateFieldForm): CreateFieldForm {
  return {
    key: field.key,
    label: field.label,
    dataType: field.dataType,
    source: field.source,
    captureMethod: field.captureMethod,
    required: field.required,
    parentKey: field.parentKey,
    kpiEnabled: field.kpiEnabled,
    showInConstructionPanel: field.showInConstructionPanel,
    options: field.options ? [...field.options] : [],
    requiredWhen: cloneRequiredWhen(field.requiredWhen),
    relationRole: field.relationRole,
  }
}

function cloneRequiredWhen(requiredWhen: ProjectFieldDefinition['requiredWhen'] | undefined): ProjectFieldDefinition['requiredWhen'] | undefined {
  if (!requiredWhen?.fieldKey) return undefined
  return {
    fieldKey: requiredWhen.fieldKey,
    equals: Array.isArray(requiredWhen.equals) ? [...requiredWhen.equals] : requiredWhen.equals,
  }
}

const replacementHierarchyTemplateIds: ReplacementHierarchyTemplateId[] = ['module-replacement', 'terminal-replacement']

function replacementHierarchyPreset(templateId: ReplacementHierarchyTemplateId) {
  return projectTypePresets.find((item) => item.id === templateId)
}

function knownReplacementTemplateFieldKeys() {
  const keys = new Set<string>()
  for (const templateId of replacementHierarchyTemplateIds) {
    const preset = replacementHierarchyPreset(templateId)
    for (const field of preset?.customFields || []) {
      keys.add(field.key)
    }
  }
  return keys
}

function applyReplacementHierarchyTemplate(form: WorkItemSchemaForm, templateId: ReplacementHierarchyTemplateId) {
  const preset = replacementHierarchyPreset(templateId)
  if (!preset) return
  const templateFieldKeys = knownReplacementTemplateFieldKeys()
  const preservedFields = form.customFields
    .filter((field) => !templateFieldKeys.has(field.key))
    .map(cloneFieldForm)

  form.primaryField = cloneFieldForm(preset.primaryField)
  form.aggregateField = cloneFieldForm(preset.aggregateField)
  form.customFields = [
    ...preset.customFields.map((field) => cloneFieldForm({ ...field, parentKey: preset.primaryField.key })),
    ...preservedFields.map((field) => {
      if (!field.parentKey) {
        field.parentKey = preset.primaryField.key
      }
      return field
    }),
  ]
  syncTerminalCoreFields(form)
}

function applyCreateProjectTypePreset(value: string | number | boolean) {
  const preset = projectTypePresets.find((item) => item.id === String(value))
  if (!preset) return
  if (!createForm.name.trim()) {
    createForm.name = preset.name
  }
  if (!createForm.description.trim()) {
    createForm.description = preset.description
  }
  createForm.primaryField = cloneFieldForm(preset.primaryField)
  createForm.aggregateField = cloneFieldForm(preset.aggregateField)
  createForm.customFields = preset.customFields.map(cloneFieldForm)
  syncTerminalCoreFields(createForm)
}

function applyCreatePrimaryFieldPreset(value: string | number | boolean) {
  applyFieldPreset(createForm.primaryField, String(value))
  syncTerminalCoreFields(createForm)
}

function applyCreateAggregateFieldPreset(value: string | number | boolean) {
  setExclusiveAggregateField(createForm, value)
}

function applySchemaPrimaryFieldPreset(value: string | number | boolean) {
  applyFieldPreset(schemaForm.primaryField, String(value))
  syncTerminalCoreFields(schemaForm)
}

function applySchemaAggregateFieldPreset(value: string | number | boolean) {
  setExclusiveAggregateField(schemaForm, value)
}

function defaultCustomField(
  key = '',
  label = '',
  captureMethod: ProjectCaptureMethod = 'manual',
): CreateFieldForm {
  return {
    key,
    label,
    dataType: captureMethod === 'photo' ? 'image' : captureMethod === 'select' ? 'enum' : 'text',
    source: 'field_collection',
    captureMethod,
    required: false,
    parentKey: 'meter_no',
    kpiEnabled: false,
    showInConstructionPanel: true,
    options: [],
    relationRole: captureMethod === 'photo' ? 'evidence_photo' : 'supporting_field',
  }
}

function resetCreateForm() {
  selectedProjectTypePresetId.value = ''
  createForm.name = ''
  createForm.description = ''
  createForm.moduleIds = [...defaultModuleIds]
  createForm.primaryField = defaultPrimaryField()
  createForm.aggregateField = defaultAggregateField()
  createForm.customFields = [
    {
      ...defaultCustomField('module_asset_no', '模块（需更换）', 'scan'),
      required: true,
      relationRole: 'accessory_new_device',
    },
    {
      ...defaultCustomField('collector_replace_confirm', '采集器（确认是否更换）', 'select'),
      required: true,
      options: replacementConfirmOptions,
      relationRole: 'accessory_replace_confirm',
    },
  ]
  createForm.dashboardMetrics = []
}

function fieldDefinitionToForm(field: ProjectFieldDefinition | undefined, fallback: CreateFieldForm): CreateFieldForm {
  return {
    key: field?.key || fallback.key,
    label: field?.label || fallback.label,
    dataType: field?.dataType || fallback.dataType,
    source: field?.source || fallback.source,
    captureMethod: field?.captureMethod || fallback.captureMethod,
    required: field?.required ?? fallback.required,
    parentKey: field?.parentKey || fallback.parentKey,
    kpiEnabled: field?.kpiEnabled ?? fallback.kpiEnabled,
    showInConstructionPanel: field?.showInConstructionPanel ?? fallback.showInConstructionPanel,
    options: field?.options?.length ? [...field.options] : [...(fallback.options || [])],
    requiredWhen: cloneRequiredWhen(field?.requiredWhen || fallback.requiredWhen),
    relationRole: field?.relationRole || fallback.relationRole,
  }
}

function fieldLabel(field: Pick<CreateFieldForm, 'label' | 'key'> | undefined, fallback = '未配置') {
  const label = String(field?.label || '').trim()
  return label || String(field?.key || '').trim() || fallback
}

function uniqueLabels(labels: string[]) {
  return Array.from(new Set(labels.map((label) => label.trim()).filter(Boolean)))
}

function customFieldsBySource(form: WorkItemSchemaForm, source: ProjectFieldSource) {
  return form.customFields.filter((field) => field.source === source && field.label.trim())
}

function importFieldLabels(form: WorkItemSchemaForm) {
  return uniqueLabels([
    fieldLabel(form.primaryField),
    fieldLabel(form.aggregateField),
    ...customFieldsBySource(form, 'import').map((field) => fieldLabel(field)),
  ])
}

function fieldCollectionLabels(form: WorkItemSchemaForm) {
  return uniqueLabels(
    customFieldsBySource(form, 'field_collection')
      .filter((field) => field.dataType !== 'image')
      .map((field) => fieldLabel(field)),
  )
}

function requiredFieldCollectionLabels(form: WorkItemSchemaForm) {
  return uniqueLabels(
    customFieldsBySource(form, 'field_collection')
      .filter((field) => field.dataType !== 'image' && field.required)
      .map((field) => fieldLabel(field)),
  )
}

function requiredPhotoLabels(form: WorkItemSchemaForm) {
  return uniqueLabels(
    form.customFields
      .filter((field) => field.source === 'field_collection' && field.dataType === 'image' && field.required)
      .map((field) => fieldLabel(field)),
  )
}

function externalCompletedFieldLabels(form: WorkItemSchemaForm) {
  return uniqueLabels([...importFieldLabels(form), ...fieldCollectionLabels(form), ...requiredPhotoLabels(form)])
}

function templatePreviewHeaders(preview: ProjectTemplateFieldPreview, templateType: ProjectTemplateType) {
  return preview.templates.find((template) => template.templateType === templateType)?.headers || []
}

function templatePreviewFieldRows(preview: ProjectTemplateFieldPreview, templateType: ProjectTemplateType) {
  return preview.templates.find((template) => template.templateType === templateType)?.fieldRows || []
}

function schemaReadinessCards(form: WorkItemSchemaForm): SchemaReadinessCard[] {
  const importLabels = importFieldLabels(form)
  const collectionLabels = requiredFieldCollectionLabels(form)
  const photoLabels = requiredPhotoLabels(form)
  return [
    {
      title: '主字段',
      value: fieldLabel(form.primaryField),
      note: `按 ${fieldLabel(form.aggregateField)} 汇总`,
      type: form.primaryField.label.trim() && form.aggregateField.label.trim() ? 'success' : 'warning',
    },
    {
      title: '初始导入',
      value: `${importLabels.length} 项`,
      note: importLabels.join('、') || '至少需要主字段和聚合字段',
      type: importLabels.length >= 2 ? 'success' : 'warning',
    },
    {
      title: '现场必采',
      value: `${collectionLabels.length} 项`,
      note: collectionLabels.join('、') || '尚未配置现场采集字段',
      type: collectionLabels.length ? 'success' : 'warning',
    },
    {
      title: '照片要求',
      value: `${photoLabels.length} 张`,
      note: photoLabels.join('、') || '未设置必拍照片',
      type: photoLabels.length ? 'success' : 'info',
    },
  ]
}

function readinessStatusType(readiness: ProjectReadiness | null | undefined): 'success' | 'warning' | 'danger' | 'info' {
  if (!readiness) return 'info'
  if (readiness.ready) return 'success'
  return readiness.summary.blockers ? 'danger' : 'warning'
}

function readinessSummaryText(readiness: ProjectReadiness | null | undefined) {
  if (!readiness) return '尚未读取后端上线检查'
  const { total, passed, failed, blockers } = readiness.summary
  const blockerText = blockers ? `，阻断 ${blockers} 项` : ''
  return `通过 ${passed}/${total} 项，缺项 ${failed} 项${blockerText}`
}

function readinessCheckLabel(check: ProjectReadinessCheck) {
  const labels: Record<string, string> = {
    primary_field: '主字段',
    aggregate_field: '聚合字段',
    single_aggregate_field: '聚合口径唯一',
    custom_site_fields: '现场采集字段',
    photo_evidence: '照片证据字段',
    required_kpi_fields: '平台 KPI 必备字段',
    device_hierarchy: '设备更换层级',
    core_modules: '核心模块',
    template_import_workflow: '模板接入流程',
    construction_workflow: '现场施工流程',
    review_workflow: '审阅流程',
    delivery_workflow: '交付归档流程',
  }
  return labels[check.id] || check.label
}

function readinessGroupLabel(group: string) {
  const labels: Record<string, string> = {
    field_schema: '字段配置',
    construction_evidence: '现场证据',
    kpi: 'KPI',
    workflow: '流程',
  }
  return labels[group] || group || '检查项'
}

function readinessActionText(action: string) {
  const actions: Record<string, string> = {
    fix_config_preflight_blockers: '请修复配置预检阻断',
    set_primary_field: '请先设置主字段',
    set_aggregate_field: '请先设置聚合字段',
    fix_aggregate_field: '请只保留一个聚合字段，台区、地区或厂家三选一，其余字段放入任务核心',
    complete_field_schema: '请补齐至少两个现场采集字段',
    add_photo_evidence_fields: '请补齐现场照片证据字段',
    confirm_required_kpi_fields: '请确认安装人员、完成时间、照片数量等 KPI 字段',
    complete_device_hierarchy: '请补齐主设备、附属设备确认和条件采集层级',
    enable_required_modules: '请启用现场、审阅、工单和交付模块',
    enable_template_import_workflow: '请启用模板接入流程',
    enable_construction_workflow: '请启用现场施工流程',
    enable_review_workflow: '请启用审阅流程',
    enable_delivery_workflow: '请启用交付归档流程',
    ready_for_template_import: '可以下载模板并接入项目数据',
    ready_for_construction_collection: '可以进入现场施工采集',
    ready_for_review_archive: '可以进入审阅和交付归档',
  }
  return actions[action] || action || '无需处理'
}

function readinessActionCountText(action: string) {
  return readinessActionText(action).replace(/^请/, '')
}

function persistenceBackendText(backend: string | undefined) {
  const labels: Record<string, string> = {
    local_json: '本地草稿文件',
    local_files: '本地文件',
    postgres_after_approved_migration: 'PostgreSQL（审批后）',
    local_json_project_draft_store: '本地项目草稿',
  }
  return labels[backend || ''] || backend || '未读取'
}

function persistenceDatabaseText(status: PlatformPersistenceStatus | null) {
  if (!status) return '未读取'
  if (!status.database.configured) return '未配置数据库'
  return status.database.usedForPlatformProjectConfig ? '已用于项目配置' : '已配置但未用于项目配置'
}

function persistenceRoundtripText(contract: ProjectConfigPersistenceContract | null) {
  if (!contract) return '未读取'
  if (contract.roundtrip.canRestore) return '字段和流程可完整还原'
  return `缺少 ${contract.roundtrip.missingPreservedKeys.length} 项`
}

function migrationGateStatusText(status: string) {
  const labels: Record<string, string> = {
    blocked: '待审批',
    passed: '已满足',
    warning: '需复核',
  }
  return labels[status] || status || '未读取'
}

function persistenceSafetyText(item: string) {
  const labels: Record<string, string> = {
    status_only_no_write: '只读状态',
    database_url_redacted: '数据库地址已脱敏',
    no_oss_mutation: '不改 OSS',
    no_postgres_schema_change: '不改 PostgreSQL 结构',
    no_production_data_edit: '不改生产数据',
    read_only_no_write: '只读契约',
    no_project_draft_load: '不加载草稿',
    no_database_connection: '不连接数据库',
    no_migration_execution: '不执行迁移',
    json_source_only: '仅以草稿文件为来源',
    requires_user_approval_before_migration: '迁移前必须审批',
  }
  return labels[item] || item
}

function configPreflightStatusText(preflight: PlatformConfigPreflight | null) {
  if (!preflight) return '未读取'
  if (!preflight.store.exists) return '暂无历史草稿'
  if (!preflight.store.readable) return '草稿不可读'
  if (preflight.readyForConfigLoad) return '可安全加载'
  return `需补齐 ${preflight.summary.blockedProjects} 个项目`
}

function configPreflightIssueText(issue: { action: string; message: string }) {
  const actions: Record<string, string> = {
    fix_field_schema_before_import: '先修字段层级',
    fix_workflow_before_import: '先修流程配置',
    fix_module_selection_before_import: '先修模块选择',
    fix_project_record_before_import: '先修项目记录',
    fix_project_draft_store_before_import: '先修草稿文件',
  }
  const action = actions[issue.action] || '接入前处理'
  return `${action}：${issue.message}`
}

function resetSchemaForm(project: Project | null) {
  const schema = project?.workItemSchema
  schemaForm.primaryField = fieldDefinitionToForm(schema?.primaryField, defaultPrimaryField())
  schemaForm.aggregateField = fieldDefinitionToForm(schema?.aggregateField, defaultAggregateField())
  schemaForm.customFields = schema?.customFields.length
    ? schema.customFields.map((field) => fieldDefinitionToForm(field, defaultCustomField()))
    : [
        {
          ...defaultCustomField('module_asset_no', '模块', 'scan'),
          required: true,
          relationRole: 'accessory_new_device',
        },
      ]
  schemaForm.dashboardMetrics = schema?.dashboardMetrics?.length
    ? schema.dashboardMetrics.map((metric) => ({ ...metric }))
    : []
  if (project?.status === 'draft') {
    syncTerminalCoreFields(schemaForm)
    syncTerminalDeviceHierarchyFields(schemaForm)
  }
}

function fieldParentOptions() {
  return [
    { value: createForm.primaryField.key || 'primary', label: createForm.primaryField.label || '主字段' },
    { value: createForm.aggregateField.key || 'aggregate', label: createForm.aggregateField.label || '聚合字段' },
  ]
}

function schemaFieldParentOptions() {
  return [
    { value: schemaForm.primaryField.key || 'primary', label: schemaForm.primaryField.label || '主字段' },
    { value: schemaForm.aggregateField.key || 'aggregate', label: schemaForm.aggregateField.label || '聚合字段' },
  ]
}

function addCustomField() {
  createForm.customFields.push(defaultCustomField())
}

function removeCustomField(index: number) {
  createForm.customFields.splice(index, 1)
}

function addSchemaCustomField() {
  schemaForm.customFields.push(defaultCustomField())
}

function removeSchemaCustomField(index: number) {
  schemaForm.customFields.splice(index, 1)
}

function handleCreateFieldParentUpdate(payload: { fieldIndex: number; parentKey: string }) {
  const field = createForm.customFields[payload.fieldIndex]
  if (!field) return
  field.parentKey = payload.parentKey
}

function handleCreateFieldUpdate(payload: {
  type: 'aggregate' | 'primary' | 'custom'
  fieldIndex?: number
  updates: Partial<CreateFieldForm>
}) {
  if (payload.type === 'aggregate') {
    Object.assign(createForm.aggregateField, payload.updates)
    return
  }
  if (payload.type === 'primary') {
    Object.assign(createForm.primaryField, payload.updates)
    return
  }
  const fieldIndex = Number(payload.fieldIndex)
  if (!Number.isInteger(fieldIndex) || !createForm.customFields[fieldIndex]) return
  Object.assign(createForm.customFields[fieldIndex], payload.updates)
}

function handleCreateDashboardMetricsUpdate(metrics: ProjectDashboardMetric[]) {
  createForm.dashboardMetrics = metrics.map((metric) => ({ ...metric }))
}

function handleCreateReplacementTemplateApply(payload: { templateId: ReplacementHierarchyTemplateId }) {
  applyReplacementHierarchyTemplate(createForm, payload.templateId)
  selectedProjectTypePresetId.value = payload.templateId
  const preset = replacementHierarchyPreset(payload.templateId)
  if (preset && !createForm.name.trim()) {
    createForm.name = preset.name
  }
  if (preset && !createForm.description.trim()) {
    createForm.description = preset.description
  }
  ElMessage.success('已套用设备更换层级模板')
}

function handleSchemaFieldParentUpdate(payload: { fieldIndex: number; parentKey: string }) {
  const field = schemaForm.customFields[payload.fieldIndex]
  if (!field || schemaProject.value?.status !== 'draft') return
  field.parentKey = payload.parentKey
}

function handleSchemaFieldUpdate(payload: {
  type: 'aggregate' | 'primary' | 'custom'
  fieldIndex?: number
  updates: Partial<CreateFieldForm>
}) {
  if (schemaProject.value?.status !== 'draft') return
  if (payload.type === 'aggregate') {
    Object.assign(schemaForm.aggregateField, payload.updates)
    return
  }
  if (payload.type === 'primary') {
    Object.assign(schemaForm.primaryField, payload.updates)
    return
  }
  const fieldIndex = Number(payload.fieldIndex)
  if (!Number.isInteger(fieldIndex) || !schemaForm.customFields[fieldIndex]) return
  Object.assign(schemaForm.customFields[fieldIndex], payload.updates)
}

function handleSchemaDashboardMetricsUpdate(metrics: ProjectDashboardMetric[]) {
  if (schemaProject.value?.status !== 'draft') return
  schemaForm.dashboardMetrics = metrics.map((metric) => ({ ...metric }))
}

function handleSchemaReplacementTemplateApply(payload: { templateId: ReplacementHierarchyTemplateId }) {
  if (schemaProject.value?.status !== 'draft') return
  applyReplacementHierarchyTemplate(schemaForm, payload.templateId)
  ElMessage.success('已更新设备更换层级模板')
}

function toFieldDefinition(field: CreateFieldForm, fallbackKey: string): ProjectFieldDefinition {
  return {
    key: field.key.trim() || fallbackKey,
    label: field.label.trim(),
    dataType: field.dataType,
    source: field.source,
    captureMethod: field.captureMethod,
    required: field.required,
    parentKey: field.parentKey || undefined,
    kpiEnabled: field.kpiEnabled,
    showInConstructionPanel: field.showInConstructionPanel,
    options: fieldOptionsForPayload(field),
    requiredWhen: cloneRequiredWhen(field.requiredWhen),
    relationRole: field.relationRole,
  }
}

function fieldOptionsForPayload(field: CreateFieldForm) {
  if (field.options?.length) return field.options
  if (field.captureMethod === 'select' || field.dataType === 'enum') return ['是', '否']
  return []
}

function buildWorkItemSchemaPayload(form: WorkItemSchemaForm = createForm): ProjectWorkItemSchema {
  return {
    primaryField: toFieldDefinition(form.primaryField, 'primary_object'),
    aggregateField: toFieldDefinition(form.aggregateField, 'aggregate_object'),
    platformRequiredFields: [],
    customFields: form.customFields
      .filter((field) => field.label.trim())
      .map((field, index) => toFieldDefinition(field, `custom_field_${index + 1}`)),
    dashboardMetrics: [...form.dashboardMetrics],
  }
}

function validateFieldForm(form: WorkItemSchemaForm) {
  if (!form.primaryField.label.trim() || !form.aggregateField.label.trim()) {
    ElMessage.warning('请填写主字段和聚合字段')
    return false
  }
  if (form.customFields.some((field) => !field.label.trim())) {
    ElMessage.warning('请补全子字段名称，或删除空字段')
    return false
  }
  return true
}

function normalizedSaveFieldKey(field: CreateFieldForm) {
  return String(field.key || '').trim().toLowerCase()
}

function normalizedSaveFieldLabel(field: CreateFieldForm) {
  return String(field.label || '').trim().toLowerCase()
}

function isSaveReplacementConfirmationField(field: CreateFieldForm) {
  const text = `${normalizedSaveFieldKey(field)} ${normalizedSaveFieldLabel(field)}`
  return field.relationRole === 'accessory_replace_confirm'
    || text.includes('replace_confirm')
    || text.includes('replacement_confirm')
    || text.includes('是否更换')
    || text.includes('确认是否更换')
}

function isSaveRecoveredDeviceField(field: CreateFieldForm) {
  const text = `${normalizedSaveFieldKey(field)} ${normalizedSaveFieldLabel(field)}`
  return text.includes('旧设备') || text.includes('旧终端') || text.includes('拆回') || text.includes('回收')
}

function aggregateFieldSaveIssues(form: WorkItemSchemaForm) {
  const issues: string[] = []
  if (form.primaryField.relationRole === 'aggregate') {
    issues.push('Only one aggregate field is allowed：主字段不能设为聚合口径，请把聚合字段放在第一层聚合字段。')
  }
  if (form.aggregateField.relationRole && form.aggregateField.relationRole !== 'aggregate') {
    issues.push('Only one aggregate field is allowed：聚合字段必须保留为聚合口径。')
  }
  const extraAggregateFields = form.customFields.filter((field) => field.label.trim() && field.relationRole === 'aggregate')
  if (extraAggregateFields.length) {
    const labels = extraAggregateFields.map((field) => field.label.trim() || field.key.trim()).filter(Boolean).join('、')
    issues.push(`Only one aggregate field is allowed：${labels} 应改为任务核心字段或施工展示字段。`)
  }
  return issues
}

function fieldHierarchySaveIssues(form: WorkItemSchemaForm) {
  const fields = form.customFields.filter((field) => field.label.trim())
  const issues: string[] = [
    ...aggregateFieldSaveIssues(form),
  ]
  const hasDeviceReplacement = fields.some((field) =>
    field.relationRole === 'replacement_device'
    || field.relationRole === 'old_device'
    || field.relationRole === 'accessory_replace_confirm'
    || field.relationRole === 'accessory_new_device'
    || isSaveReplacementConfirmationField(field),
  )
  if (!hasDeviceReplacement) return issues

  const hasMainReplacement = fields.some((field) => field.relationRole === 'replacement_device')
  const directAccessoryNewDevices = fields.filter((field) =>
    field.relationRole === 'accessory_new_device' && !field.requiredWhen?.fieldKey,
  )
  const directOldDeviceOrEvidenceFields = fields.filter((field) =>
    !field.requiredWhen?.fieldKey
    && (
      field.relationRole === 'old_device'
      || field.relationRole === 'evidence_photo'
      || field.captureMethod === 'photo'
      || field.dataType === 'image'
      || isSaveRecoveredDeviceField(field)
    ),
  )
  const mainOldDeviceFields = fields.filter((field) => field.relationRole === 'old_device' && !field.requiredWhen?.fieldKey)
  const accessoryConfirmFields = fields.filter((field) => isSaveReplacementConfirmationField(field))
  const accessoryConfirmKeys = new Set(accessoryConfirmFields.map((field) => field.key).filter(Boolean))
  const conditionalChildFields = fields.filter((field) =>
    Boolean(field.requiredWhen?.fieldKey && accessoryConfirmKeys.has(field.requiredWhen.fieldKey)),
  )
  const unconditionalMainAccessoryFields = hasMainReplacement
    ? directAccessoryNewDevices
    : []
  if (!hasMainReplacement) {
    if (!directAccessoryNewDevices.length || !directOldDeviceOrEvidenceFields.length) {
      issues.push('换模块需要在任务对象下保留新附属设备和旧设备/回收证据')
    }
    return issues
  }

  if (!mainOldDeviceFields.length || !accessoryConfirmFields.length || !conditionalChildFields.length) {
    issues.push('换终端需要主设备更换、旧设备、附属设备确认和条件采集')
  }
  if (unconditionalMainAccessoryFields.length) {
    const labels = unconditionalMainAccessoryFields
      .map((field) => field.label.trim() || field.key.trim())
      .filter(Boolean)
      .join('、')
    issues.push(`换终端的附属设备不能直接平铺：${labels} 需要先通过“是否更换”确认项触发`)
  }
  return issues
}

function validateFieldHierarchyBeforeSave(form: WorkItemSchemaForm) {
  const issues = fieldHierarchySaveIssues(form)
  if (!issues.length) return true
  ElMessage.warning(issues[0])
  return false
}

function openSchemaDialog(project: Project) {
  schemaProject.value = project
  schemaTemplatePreview.value = null
  resetSchemaForm(project)
  schemaDialogVisible.value = true
  void loadProjectReadiness(project)
  void loadProjectPersistenceReadiness(project)
  void loadProjectConfigPreflight()
  scheduleSchemaTemplatePreviewRefresh(0)
}

async function loadProjectReadiness(project: Project | null | undefined = schemaProject.value) {
  if (!project) return
  const projectId = project.id
  loadingReadinessProjectId.value = projectId
  try {
    const readiness = await fetchProjectReadiness(projectId)
    projectReadinessById.value = {
      ...projectReadinessById.value,
      [projectId]: readiness,
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '上线检查读取失败')
  } finally {
    if (loadingReadinessProjectId.value === projectId) {
      loadingReadinessProjectId.value = ''
    }
  }
}

async function loadProjectReadinessSummary() {
  loadingProjectReadinessSummary.value = true
  try {
    projectReadinessSummary.value = await fetchProjectReadinessSummary()
    if (
      selectedReadinessAction.value
      && !projectReadinessSummary.value.actionCounts.some((item) => item.action === selectedReadinessAction.value)
    ) {
      selectedReadinessAction.value = ''
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '上线状态汇总读取失败')
  } finally {
    loadingProjectReadinessSummary.value = false
  }
}

async function loadPlatformHandoffReadiness() {
  loadingPlatformHandoffReadiness.value = true
  try {
    platformHandoffReadiness.value = await fetchPlatformHandoffReadiness()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '交付就绪读取失败')
  } finally {
    loadingPlatformHandoffReadiness.value = false
  }
}

async function loadProjectPersistenceReadiness(project: Project | null | undefined = schemaProject.value) {
  if (!project) return
  const projectId = project.id
  loadingPersistenceReadinessProjectId.value = projectId
  try {
    const [status, migrationReadiness, contract] = await Promise.all([
      fetchPlatformPersistenceStatus(),
      fetchPlatformMigrationReadiness(),
      fetchProjectConfigPersistenceContract(projectId),
    ])
    projectPersistenceStatus.value = status
    projectMigrationReadiness.value = migrationReadiness
    projectPersistenceContractsById.value = {
      ...projectPersistenceContractsById.value,
      [projectId]: contract,
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '持久化准备读取失败')
  } finally {
    if (loadingPersistenceReadinessProjectId.value === projectId) {
      loadingPersistenceReadinessProjectId.value = ''
    }
  }
}

async function loadProjectConfigPreflight() {
  loadingProjectConfigPreflight.value = true
  try {
    projectConfigPreflight.value = await fetchProjectConfigPreflight()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '配置预检读取失败')
  } finally {
    loadingProjectConfigPreflight.value = false
  }
}

function scheduleSchemaTemplatePreviewRefresh(delay = 250) {
  if (!schemaDialogVisible.value || !schemaProject.value) return
  if (schemaTemplatePreviewTimer) {
    window.clearTimeout(schemaTemplatePreviewTimer)
  }
  schemaTemplatePreviewTimer = window.setTimeout(() => {
    schemaTemplatePreviewTimer = null
    void refreshSchemaTemplatePreview()
  }, delay)
}

async function refreshSchemaTemplatePreview() {
  const project = schemaProject.value
  if (!project || !schemaDialogVisible.value) return
  const requestId = ++schemaTemplatePreviewRequestId
  loadingSchemaTemplatePreview.value = true
  try {
    const preview = await previewProjectTemplateFields(project.id, buildWorkItemSchemaPayload(schemaForm))
    if (requestId === schemaTemplatePreviewRequestId) {
      schemaTemplatePreview.value = preview
    }
  } catch {
    if (requestId === schemaTemplatePreviewRequestId) {
      schemaTemplatePreview.value = null
    }
  } finally {
    if (requestId === schemaTemplatePreviewRequestId) {
      loadingSchemaTemplatePreview.value = false
    }
  }
}

async function openWorkflowDialog(project: Project) {
  workflowProject.value = project
  projectWorkflow.value = project.workflow || null
  workflowDialogVisible.value = true
  loadingWorkflow.value = true
  try {
    projectWorkflow.value = await fetchProjectWorkflow(project.id)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '流程配置读取失败')
  } finally {
    loadingWorkflow.value = false
  }
}

async function handleWorkflowSave(workflow: ProjectWorkflow) {
  const project = workflowProject.value
  if (!project) return
  savingWorkflow.value = true
  try {
    projectWorkflow.value = await saveProjectWorkflow(project.id, workflow)
    await workspace.loadProjects()
    ElMessage.success('流程配置已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '流程配置保存失败')
  } finally {
    savingWorkflow.value = false
  }
}

async function handleWorkflowReset() {
  const project = workflowProject.value
  if (!project) return
  resettingWorkflow.value = true
  try {
    projectWorkflow.value = await resetProjectWorkflow(project.id)
    await workspace.loadProjects()
    ElMessage.success('流程已恢复默认')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '流程重置失败')
  } finally {
    resettingWorkflow.value = false
  }
}

async function submitCreateProject() {
  const name = createForm.name.trim()
  if (!name) {
    ElMessage.warning('请填写项目名称')
    return
  }
  if (!createForm.moduleIds.length) {
    ElMessage.warning('请至少选择一个模块')
    return
  }
  if (!validateFieldForm(createForm)) return
  if (!validateFieldHierarchyBeforeSave(createForm)) return
  creatingProject.value = true
  try {
    const project = await workspace.createProjectDraft({
      name,
      description: createForm.description.trim(),
      moduleIds: createForm.moduleIds,
      workItemSchema: buildWorkItemSchemaPayload(),
    })
    createDialogVisible.value = false
    resetCreateForm()
    ElMessage.success(`已创建项目草稿：${project.name}`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '项目草稿创建失败')
  } finally {
    creatingProject.value = false
  }
}

async function submitSchemaUpdate() {
  const project = schemaProject.value
  if (!project) return
  if (project.status !== 'draft') {
    ElMessage.info('正式项目字段配置需要走变更评审，当前仅开放查看')
    return
  }
  if (!validateFieldForm(schemaForm)) return
  if (!validateFieldHierarchyBeforeSave(schemaForm)) return
  savingSchema.value = true
  try {
    const updatedProject = await workspace.updateProjectWorkItemSchema(project.id, buildWorkItemSchemaPayload(schemaForm))
    schemaProject.value = updatedProject
    await loadProjectReadiness(updatedProject)
    schemaDialogVisible.value = false
    ElMessage.success('字段配置已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '字段配置保存失败')
  } finally {
    savingSchema.value = false
  }
}

async function downloadTemplate(project: Project, templateType: ProjectTemplateType) {
  try {
    await downloadProjectTemplate(project.id, templateType, project.name)
    ElMessage.success('模板已开始下载')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '模板下载失败')
  }
}

function handleTemplateCommand(project: Project, command: string | number | object) {
  const [action, rawTemplateType] = String(command).split(':')
  const templateType = (rawTemplateType || action) as ProjectTemplateType
  if (action === 'validate') {
    requestTemplateValidation(project, templateType)
    return
  }
  void downloadTemplate(project, templateType)
}

function requestTemplateValidation(project: Project, templateType: ProjectTemplateType) {
  pendingValidationProject.value = project
  pendingValidationTemplateType.value = templateType
  templateFileInput.value?.click()
}

function handleCreateTemplateAction(payload: { action: 'download' | 'validate'; templateType: ProjectTemplateType }) {
  const actionText = payload.action === 'validate' ? '校验模板' : '下载模板'
  ElMessage.info(`请先创建项目草稿，再${actionText}`)
}

function handleSchemaTemplateAction(payload: { action: 'download' | 'validate'; templateType: ProjectTemplateType }) {
  const project = schemaProject.value
  if (!project) return
  if (payload.action === 'validate') {
    requestTemplateValidation(project, payload.templateType)
    return
  }
  void downloadTemplate(project, payload.templateType)
}

async function handleTemplateFileSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  const project = pendingValidationProject.value
  const templateType = pendingValidationTemplateType.value
  if (!file || !project) return
  validatingTemplate.value = true
  try {
    const report = await validateProjectTemplate(project.id, templateType, file)
    templateValidationReport.value = report
    validatedTemplateFile.value = file
    importDraftJob.value = null
    importBatchJob.value = null
    workOrderTaskJob.value = null
    validationProjectName.value = project.name
    validationTemplateType.value = templateType
    validationDialogVisible.value = true
    if (report.status === 'failed') {
      ElMessage.error('模板校验发现错误，请先处理后再导入')
    } else if (report.status === 'warning') {
      ElMessage.warning('模板可以接入，但有建议补齐项')
    } else {
      ElMessage.success('模板校验通过')
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '模板校验失败')
  } finally {
    validatingTemplate.value = false
  }
}

function templateTypeLabel(templateType: ProjectTemplateType) {
  return templateDownloadOptions.find((option) => option.type === templateType)?.label || templateType
}

function validationStatusLabel(status: ProjectTemplateValidationReport['status'] | undefined) {
  if (status === 'passed') return '通过'
  if (status === 'warning') return '可接入，有建议'
  return '有错误'
}

function validationStatusType(status: ProjectTemplateValidationReport['status'] | undefined) {
  if (status === 'passed') return 'success'
  if (status === 'warning') return 'warning'
  return 'danger'
}

function validationSeverityLabel(severity: string) {
  return severity === 'error' ? '错误' : '建议'
}

function validationSeverityType(severity: string) {
  return severity === 'error' ? 'danger' : 'warning'
}

function validationIssueRowLabel(item: ProjectTemplateValidationItem) {
  return item.row ? `第 ${item.row} 行` : '整表'
}

function canCreateImportDraft() {
  return !!pendingValidationProject.value && !!validatedTemplateFile.value && !templateValidationReport.value?.summary.error_count
}

async function createImportDraftFromValidation() {
  const project = pendingValidationProject.value
  const file = validatedTemplateFile.value
  if (!project || !file || !canCreateImportDraft()) return
  creatingImportDraft.value = true
  try {
    const job = await createProjectTemplateImportDraft(project.id, validationTemplateType.value, file)
    importDraftJob.value = job
    importBatchJob.value = null
    workOrderTaskJob.value = null
    ElMessage.success('已生成导入草稿，可进入下一步预览接入')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '导入草稿生成失败')
  } finally {
    creatingImportDraft.value = false
  }
}

function canConfirmImportBatch() {
  return !!pendingValidationProject.value && !!validatedTemplateFile.value && !!importDraftJob.value && importDraftJob.value.status !== 'blocked'
}

async function confirmImportBatchFromDraft() {
  const project = pendingValidationProject.value
  const file = validatedTemplateFile.value
  if (!project || !file || !canConfirmImportBatch()) return
  confirmingImportBatch.value = true
  try {
    const job = await confirmProjectTemplateImportBatch(project.id, validationTemplateType.value, file)
    importBatchJob.value = job
    workOrderTaskJob.value = null
    ElMessage.success('已记录导入批次，下一步可创建工单')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '导入批次确认失败')
  } finally {
    confirmingImportBatch.value = false
  }
}

function canCreateWorkOrderTask() {
  return !!pendingValidationProject.value && !!importBatchJob.value && importBatchJob.value.status === 'confirmed'
}

async function createWorkOrderTaskFromBatch() {
  const project = pendingValidationProject.value
  const batch = importBatchJob.value
  if (!project || !batch || !canCreateWorkOrderTask()) return
  creatingWorkOrderTask.value = true
  try {
    const job = await createImportBatchWorkOrderTask(project.id, batch.jobId)
    workOrderTaskJob.value = job
    ElMessage.success('已生成安全工单任务，当前未创建真实工单')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '工单任务生成失败')
  } finally {
    creatingWorkOrderTask.value = false
  }
}

function canExecuteWorkOrderTask() {
  return !!pendingValidationProject.value && !!workOrderTaskJob.value && workOrderTaskJob.value.status === 'planned'
}

async function executeWorkOrderTaskFromPlan() {
  const project = pendingValidationProject.value
  const task = workOrderTaskJob.value
  if (!project || !task || !canExecuteWorkOrderTask()) return
  executingWorkOrderTask.value = true
  try {
    const job = await executeImportWorkOrderTask(project.id, task.jobId)
    workOrderTaskJob.value = job
    ElMessage.success('已在本地平台存储创建工单')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '执行创建工单失败')
  } finally {
    executingWorkOrderTask.value = false
  }
}

function canRollbackWorkOrderTask() {
  return !!pendingValidationProject.value && !!workOrderTaskJob.value && workOrderTaskJob.value.status === 'completed'
}

const importWizardPrimaryLabel = computed(() => {
  if (templateValidationReport.value?.summary.error_count) return '修正模板后重新上传'
  if (!importDraftJob.value) return '生成接入预览'
  if (!importBatchJob.value) return '确认接入批次'
  if (!workOrderTaskJob.value) return '生成工单计划'
  if (workOrderTaskJob.value.status === 'planned') return '接入平台'
  if (workOrderTaskJob.value.status === 'completed') return '已接入平台'
  if (workOrderTaskJob.value.status === 'rolled_back') return '已回滚'
  return '继续'
})

const importWizardPrimaryType = computed(() => {
  if (templateValidationReport.value?.summary.error_count) return 'danger'
  if (workOrderTaskJob.value?.status === 'completed') return 'success'
  if (workOrderTaskJob.value?.status === 'planned') return 'warning'
  return 'primary'
})

const importWizardPrimaryLoading = computed(
  () =>
    creatingImportDraft.value ||
    confirmingImportBatch.value ||
    creatingWorkOrderTask.value ||
    executingWorkOrderTask.value,
)

const canRunImportWizardPrimaryAction = computed(() => {
  if (!importDraftJob.value) return canCreateImportDraft()
  if (!importBatchJob.value) return canConfirmImportBatch()
  if (!workOrderTaskJob.value) return canCreateWorkOrderTask()
  return canExecuteWorkOrderTask()
})

const canOpenImportWizardNextActions = computed(
  () => !!pendingValidationProject.value && workOrderTaskJob.value?.status === 'completed',
)

const importWizardStepCards = computed<ImportWizardStepCard[]>(() => {
  const completed = workOrderTaskJob.value?.status === 'completed'
  const planned = workOrderTaskJob.value?.status === 'planned'
  return [
    {
      title: '校验模板',
      description: '先确认字段、格式和必填项能被平台识别。',
      state: templateValidationReport.value ? 'done' : 'active',
    },
    {
      title: '生成预览',
      description: '只生成接入草稿，不创建真实工单。',
      state: importDraftJob.value ? 'done' : 'active',
    },
    {
      title: '确认批次',
      description: '记录本次导入批次，便于追溯和回滚。',
      state: importBatchJob.value ? 'done' : importDraftJob.value ? 'active' : 'pending',
    },
    {
      title: '生成工单',
      description: '生成安全工单计划，仍未写入正式平台工单。',
      state: workOrderTaskJob.value ? 'done' : importBatchJob.value ? 'active' : 'pending',
    },
    {
      title: '接入平台',
      description: '写入本地平台工单，后续可以施工或审阅。',
      state: completed ? 'done' : planned ? 'active' : 'pending',
    },
  ]
})

const importWizardNextActionHint = computed(() => {
  if (templateValidationReport.value?.summary.error_count) return '下一步建议：修正模板错误后重新上传。'
  if (!importDraftJob.value) return '下一步建议：生成接入预览，先看可接入行和问题行。'
  if (!importBatchJob.value) return '下一步建议：确认接入批次，平台会保留本次导入记录。'
  if (!workOrderTaskJob.value) return '下一步建议：生成工单计划，确认会创建多少平台工单。'
  if (workOrderTaskJob.value.status === 'planned') return '下一步建议：接入平台；执行后仍可以回滚本次本地接入。'
  if (workOrderTaskJob.value.status === 'completed') {
    return validationTemplateType.value === 'external_completed'
      ? '下一步建议：去审阅工作台处理系统外已完成数据。'
      : '下一步建议：去施工采集继续现场数据补齐。'
  }
  if (workOrderTaskJob.value.status === 'rolled_back') return '下一步建议：已回滚，可重新校验并接入。'
  return '下一步建议：按主按钮继续。'
})

async function runImportWizardPrimaryAction() {
  if (!canRunImportWizardPrimaryAction.value) return
  if (!importDraftJob.value) {
    await createImportDraftFromValidation()
    return
  }
  if (!importBatchJob.value) {
    await confirmImportBatchFromDraft()
    return
  }
  if (!workOrderTaskJob.value) {
    await createWorkOrderTaskFromBatch()
    return
  }
  await executeWorkOrderTaskFromPlan()
}

function openImportWizardNextAction(path: '/construction' | '/task-hall') {
  const project = pendingValidationProject.value
  if (!project || !canOpenImportWizardNextActions.value) return
  validationDialogVisible.value = false
  openRoute(path, project)
}

async function rollbackWorkOrderTaskFromExecution() {
  const project = pendingValidationProject.value
  const task = workOrderTaskJob.value
  if (!project || !task || !canRollbackWorkOrderTask()) return
  rollingBackWorkOrderTask.value = true
  try {
    const job = await rollbackImportWorkOrderTask(project.id, task.jobId)
    workOrderTaskJob.value = job
    ElMessage.success('已回滚本地平台工单')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '工单任务回滚失败')
  } finally {
    rollingBackWorkOrderTask.value = false
  }
}

function importDraftSummary(job: ImportJob | null) {
  const result = (job?.result || {}) as { summary?: Record<string, unknown>; hierarchy_gap_items?: unknown }
  const summary = result.summary || {}
  const hierarchyGapItems = importDraftHierarchyGapItems(result.hierarchy_gap_items)
  return {
    totalRows: Number(summary.total_rows || 0),
    readyRows: Number(summary.ready_rows || 0),
    previewRows: Number(summary.preview_rows || 0),
    hierarchyGapCount: Number(summary.hierarchy_gap_count || hierarchyGapItems.length || 0),
    hierarchyGapItems,
  }
}

function importDraftHierarchyGapItems(rawItems: unknown): ImportDraftHierarchyGapItem[] {
  if (!Array.isArray(rawItems)) return []
  return rawItems.slice(0, 5).map((item) => {
    const record = (item || {}) as Record<string, unknown>
    const rowNumber = record.row === null || record.row === undefined ? Number.NaN : Number(record.row)
    return {
      row: Number.isFinite(rowNumber) ? rowNumber : null,
      fieldKey: String(record.field_key || record.fieldKey || ''),
      fieldLabel: String(record.field_label || record.fieldLabel || ''),
      message: String(record.message || ''),
      value: String(record.value || ''),
    }
  })
}

function workOrderTaskSummary(job: ImportJob | null) {
  const result = (job?.result || {}) as { summary?: Record<string, unknown> }
  const summary = result.summary || {}
  return {
    plannedWorkOrders: Number(summary.planned_work_orders || 0),
    createdWorkOrders: Number(summary.created_work_orders || 0),
  }
}

function workOrderTaskStatusLabel(job: ImportJob | null) {
  if (job?.status === 'completed') return 'completed'
  if (job?.status === 'rolled_back') return 'rolled back'
  return 'planned'
}

function workOrderTaskStatusType(job: ImportJob | null) {
  if (job?.status === 'completed') return 'success'
  if (job?.status === 'rolled_back') return 'danger'
  return 'info'
}

function handleModuleCommand(project: Project, command: string | number | object) {
  openRoute(String(command), project)
}

function openRoute(path: string, project: Project) {
  workspace.selectProject(project.id)
  void router.push({ path, query: { project_id: project.id } })
}

function projectActionModules(project: Project) {
  const modules = project.modules.length ? project.modules : fallbackModules
  return modules.filter((module) => module.routePath)
}

function projectRowClass({ row }: { row: Project }) {
  return row.id === workspace.activeProjectId ? 'active-project-row' : ''
}

function workflowStatusText(project: Project) {
  const status = project.workflowStatus
  if (!status) return '当前流程：未配置'
  const current = status.currentNodeLabel || '未开始'
  const nodeCount = status.totalNodes || status.enabledNodeIds.length
  const syncLabel = status.moduleSyncEnabled ? '同步模块' : '默认模块'
  return `当前流程：${current} · ${nodeCount} 节点 · ${syncLabel}`
}

function projectReadinessListItem(project: Project) {
  return projectReadinessSummaryById.value[project.id]
}

function projectReadinessListType(project: Project): 'success' | 'warning' | 'danger' | 'info' {
  const item = projectReadinessListItem(project)
  if (!item) return 'info'
  if (item.ready) return 'success'
  return item.summary.blockers ? 'danger' : 'warning'
}

function projectReadinessListLabel(project: Project) {
  const item = projectReadinessListItem(project)
  if (!item) return loadingProjectReadinessSummary.value ? '检查中' : '未检查'
  return item.ready ? '可接入' : '需补齐'
}

function projectReadinessListText(project: Project) {
  const item = projectReadinessListItem(project)
  if (!item) return loadingProjectReadinessSummary.value ? '正在读取' : '待检查'
  return `通过 ${item.summary.passed}/${item.summary.total} 项`
}

function applyReadinessActionFilter(action: string) {
  selectedReadinessAction.value = selectedReadinessAction.value === action ? '' : action
}

function clearReadinessActionFilter() {
  selectedReadinessAction.value = ''
}

function formatUpdatedAt(value: string) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function deliveryLabel(status = '') {
  return status === 'ready' ? '可交付' : '准备中'
}

function deliveryType(status = '') {
  return status === 'ready' ? 'success' : 'warning'
}

function statusLabel(status: Project['status']) {
  if (status === 'draft') return '草稿'
  return status === 'active' ? '进行中' : '已归档'
}

function statusType(status: Project['status']) {
  if (status === 'active') return 'success'
  if (status === 'draft') return 'warning'
  return 'info'
}

function progressStatus(value = 0, riskTotal = 0) {
  if (riskTotal > 0) return 'exception'
  return value >= 100 ? 'success' : undefined
}
</script>

<template>
  <div class="page-stack">
    <input
      ref="templateFileInput"
      class="hidden-file-input"
      type="file"
      accept=".xlsx,.xls"
      @change="handleTemplateFileSelected"
    />
    <div class="toolbar">
      <div>
        <h2>项目管理</h2>
        <p>进度、交付、现场采集、审阅与风险统一视图。</p>
      </div>
      <div class="toolbar-actions">
        <ElButton :icon="Refresh" @click="refreshProjects">刷新</ElButton>
        <ElButton type="primary" :icon="Plus" @click="openCreateDialog">新建项目</ElButton>
      </div>
    </div>

    <section class="template-usage-grid" aria-label="项目接入模板选择">
      <article v-for="card in templateUsageCards" :key="card.type" class="template-usage-card">
        <div>
          <span>{{ card.title }}</span>
          <ElTag size="small" effect="plain">{{ card.badge }}</ElTag>
        </div>
        <p>{{ card.description }}</p>
        <small>{{ card.route }}</small>
      </article>
    </section>

    <section class="panel">
      <div class="panel-body">
        <div class="handoff-readiness-band">
          <div>
            <span>交付就绪</span>
            <strong>{{ handoffReviewStatusText }}</strong>
          </div>
          <div>
            <span>目标基线</span>
            <strong>{{ platformHandoffReadiness?.productionBaseline.branch || 'production/V3/3.0.77' }}</strong>
          </div>
          <div>
            <span>迁移状态</span>
            <strong>{{ handoffMigrationStatusText }}</strong>
          </div>
          <div class="config-preflight-handoff-status">
            <span>配置预检</span>
            <strong>{{ handoffConfigPreflightText }}</strong>
          </div>
          <div>
            <span>下一步</span>
            <strong>{{ handoffNextActionText }}</strong>
          </div>
          <ElButton
            size="small"
            :icon="Refresh"
            :loading="loadingPlatformHandoffReadiness"
            @click="loadPlatformHandoffReadiness"
          >
            刷新交付
          </ElButton>
        </div>
        <div class="readiness-summary-band">
          <div class="project-list-config-preflight">
            <span>项目列表预检</span>
            <strong>{{ projectListConfigPreflightText }}</strong>
          </div>
          <div>
            <span>上线检查</span>
            <strong>{{ readinessSummaryBandText }}</strong>
          </div>
          <div class="readiness-action-todos">
            <span>接入待办</span>
            <div v-if="topReadinessActionCounts.length">
              <ElTag
                v-for="item in topReadinessActionCounts"
                :key="item.action"
                type="warning"
                :effect="selectedReadinessAction === item.action ? 'dark' : 'plain'"
                class="readiness-action-tag"
                @click="applyReadinessActionFilter(item.action)"
              >
                {{ readinessActionCountText(item.action) }} {{ item.count }} 个
              </ElTag>
            </div>
            <strong v-else>{{ loadingProjectReadinessSummary ? '检查中' : '暂无待办' }}</strong>
          </div>
          <div v-if="selectedReadinessAction" class="readiness-filter-state">
            <span>筛选中</span>
            <strong>{{ readinessActionFilterText }} · {{ filteredProjects.length }} 个项目</strong>
            <ElButton link size="small" @click="clearReadinessActionFilter">清除筛选</ElButton>
          </div>
          <ElButton
            size="small"
            :icon="Refresh"
            :loading="loadingProjectReadinessSummary"
            @click="loadProjectReadinessSummary"
          >
            刷新检查
          </ElButton>
        </div>
        <div v-if="showProjectListConfigPreflightDetails" class="project-list-config-preflight-details">
          <div class="project-list-config-preflight-detail-head">
            <span>项目列表预检阻断</span>
            <strong>{{ projectListConfigPreflightText }}</strong>
            <small>先修复这些历史草稿，再恢复完整项目列表加载。</small>
          </div>
          <div class="project-list-config-preflight-detail-grid">
            <article
              v-for="issue in projectListConfigPreflightStoreIssues"
              :key="`${issue.scope}-${issue.code}-${issue.message}`"
              class="status-failed"
            >
              <ElTag type="danger" size="small" effect="light">草稿文件</ElTag>
              <div>
                <strong>{{ issue.scope }}</strong>
                <span>{{ configPreflightIssueText(issue) }}</span>
              </div>
            </article>
            <article
              v-for="project in projectListConfigPreflightBlockedProjects"
              :key="project.projectId"
              class="status-failed"
            >
              <ElTag type="danger" size="small" effect="light">阻断项目</ElTag>
              <div>
                <strong>{{ project.name }}</strong>
                <span v-if="project.issues[0]">{{ configPreflightIssueText(project.issues[0]) }}</span>
                <span v-else>配置结构需人工检查</span>
                <small>{{ project.projectId }} · {{ project.issueCount }} 个问题</small>
              </div>
            </article>
          </div>
        </div>
        <ElTable :data="filteredProjects" stripe :row-class-name="projectRowClass">
          <ElTableColumn label="项目" min-width="220" fixed>
            <template #default="{ row }">
              <div class="project-cell">
                <strong>{{ row.name }}</strong>
                <span>{{ row.stage || '准备中' }}</span>
                <span v-if="row.workflowStatus">{{ workflowStatusText(row) }}</span>
              </div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="状态" width="110">
            <template #default="{ row }">
              <ElTag :type="statusType(row.status)">{{ statusLabel(row.status) }}</ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="上线状态" min-width="140">
            <template #default="{ row }">
              <div class="project-list-readiness-cell">
                <ElTag :type="projectReadinessListType(row)" effect="light">
                  {{ projectReadinessListLabel(row) }}
                </ElTag>
                <span>{{ projectReadinessListText(row) }}</span>
              </div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="项目进度" min-width="180">
            <template #default="{ row }">
              <ElProgress
                :percentage="row.managementProgress || 0"
                :status="progressStatus(row.managementProgress, row.risks?.total)"
              />
              <div class="subline">{{ row.completedGroups }} / {{ row.totalGroups }} 组</div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="交付能力" min-width="150">
            <template #default="{ row }">
              <ElTag :type="deliveryType(row.delivery?.status)">
                {{ deliveryLabel(row.delivery?.status) }}
              </ElTag>
              <div class="subline">{{ row.delivery?.completedItems || 0 }} / {{ row.delivery?.totalItems || 0 }} 项</div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="现场采集" min-width="150">
            <template #default="{ row }">
              <div class="metric-pair">
                <span>照片 {{ row.field?.photoRowsLinked || 0 }}</span>
                <span>未施工 {{ row.field?.unconstructedGroups || 0 }}</span>
              </div>
              <ElTag v-if="row.field?.exceptionCount" type="danger" size="small">
                异常 {{ row.field.exceptionCount }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="审阅" min-width="150">
            <template #default="{ row }">
              <ElProgress :percentage="row.review?.reviewRate || 0" />
              <div class="subline">待审 {{ row.review?.pendingGroups || 0 }} 组</div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="任务中心" min-width="150">
            <template #default="{ row }">
              <div class="metric-pair">
                <span>上传 {{ row.tasks?.uploaded || 0 }}</span>
                <span>审阅中 {{ row.tasks?.reviewing || 0 }}</span>
              </div>
              <div class="subline">归档 {{ row.tasks?.archived || 0 }} / {{ row.tasks?.total || 0 }}</div>
              <div class="subline platform-kpi-line">
                <span>初始 {{ row.tasks?.initialWorkOrders || 0 }}</span>
                <span>接入 {{ row.tasks?.externalCompleted || 0 }}</span>
                <span>返工 {{ row.tasks?.returnedRework || 0 }}</span>
                <span>通过 {{ row.tasks?.approvedArchive || 0 }}</span>
                <span>未就绪 {{ row.tasks?.notReady || 0 }}</span>
              </div>
              <div class="subline platform-delivery-kpi-line">
                <span>KPI {{ row.tasks?.kpiReady || 0 }}</span>
                <span>旧设备 {{ row.tasks?.oldDeviceRecovered || 0 }}</span>
                <span>在线 {{ row.tasks?.averageOnlineDurationMinutes || 0 }}分</span>
                <span>人员 {{ row.tasks?.installerCount || 0 }}</span>
              </div>
              <div class="subline platform-review-quality-line">
                <span>审阅质量</span>
                <span>通过 {{ row.tasks?.approvedArchive || row.tasks?.archived || 0 }}</span>
                <span>返工 {{ row.tasks?.returnedRework || 0 }}</span>
                <span>待审 {{ row.tasks?.pendingReview || row.tasks?.reviewing || 0 }}</span>
                <span>通过率 {{ row.tasks?.reviewRate || 0 }}%</span>
              </div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="风险" width="110">
            <template #default="{ row }">
              <ElTag :type="row.risks?.total ? 'danger' : 'success'">
                {{ row.risks?.total || 0 }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="更新时间" width="130">
            <template #default="{ row }">
              {{ formatUpdatedAt(row.updatedAt) }}
            </template>
          </ElTableColumn>
          <ElTableColumn label="操作" width="300" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <ElButton size="small" type="primary" plain @click="openSchemaDialog(row)">
                  字段配置
                </ElButton>
                <ElButton size="small" plain @click="openWorkflowDialog(row)">
                  流程配置
                </ElButton>
                <ElDropdown trigger="click" @command="handleTemplateCommand(row, $event)">
                  <ElButton size="small" plain :loading="validatingTemplate">模板</ElButton>
                  <template #dropdown>
                    <ElDropdownMenu>
                      <ElDropdownItem
                        v-for="option in templateActionOptions"
                        :key="option.command"
                        :command="option.command"
                        :divided="option.divided"
                      >
                        {{ option.label }}
                      </ElDropdownItem>
                    </ElDropdownMenu>
                  </template>
                </ElDropdown>
                <ElDropdown trigger="click" @command="handleModuleCommand(row, $event)">
                  <ElButton
                    size="small"
                    :disabled="!projectActionModules(row).length"
                  >
                    进入模块
                  </ElButton>
                  <template #dropdown>
                    <ElDropdownMenu>
                      <ElDropdownItem
                        v-for="module in projectActionModules(row)"
                        :key="module.id"
                        :command="module.routePath"
                      >
                        {{ module.name }}
                      </ElDropdownItem>
                    </ElDropdownMenu>
                  </template>
                </ElDropdown>
              </div>
            </template>
          </ElTableColumn>
        </ElTable>
      </div>
    </section>

    <ElDialog v-model="createDialogVisible" title="新建项目草稿" width="860px" @closed="resetCreateForm">
      <ElForm label-position="top">
        <ElFormItem label="项目名称" required>
          <ElInput v-model="createForm.name" maxlength="40" show-word-limit placeholder="例如：线路巡检项目" />
        </ElFormItem>
        <ElFormItem label="项目说明">
          <ElInput
            v-model="createForm.description"
            type="textarea"
            :rows="3"
            maxlength="160"
            show-word-limit
            placeholder="说明这个项目的现场范围、交付目标或接入计划"
          />
        </ElFormItem>
        <ElFormItem label="项目类型预设">
          <ElSelect
            v-model="selectedProjectTypePresetId"
            clearable
            placeholder="可选：套用常见项目字段"
            @change="applyCreateProjectTypePreset"
          >
            <ElOption
              v-for="preset in projectTypePresets"
              :key="preset.id"
              :label="preset.name"
              :value="preset.id"
            />
          </ElSelect>
        </ElFormItem>
        <div v-if="selectedProjectTypePresetGuidance" class="preset-hierarchy-guidance">
          <div class="preset-hierarchy-guidance__head">
            <div>
              <span>{{ selectedProjectTypePresetGuidance.title }}</span>
              <strong>{{ selectedProjectTypePresetGuidance.hierarchy }}</strong>
            </div>
            <ElTag effect="light">{{ selectedProjectTypePresetGuidance.badge }}</ElTag>
          </div>
          <div class="preset-hierarchy-guidance__facts">
            <small>{{ selectedProjectTypePresetGuidance.primary }}</small>
            <small>{{ selectedProjectTypePresetGuidance.aggregate }}</small>
            <small>{{ selectedProjectTypePresetGuidance.aggregateRule }}</small>
          </div>
          <p>{{ selectedProjectTypePresetGuidance.helper }}</p>
        </div>
        <ElFormItem label="启用模块" required>
          <ElCheckboxGroup v-model="createForm.moduleIds" class="module-checkboxes">
            <ElCheckbox v-for="module in moduleOptions" :key="module.id" :label="module.id">
              {{ module.name }}
            </ElCheckbox>
          </ElCheckboxGroup>
        </ElFormItem>

        <div class="schema-section first-section">
          <div class="schema-heading">
            <strong>配置体检</strong>
            <span>先看这个项目是否具备可导入、可采集、可审阅的基础。</span>
          </div>
          <div class="readiness-grid">
            <div v-for="card in createSchemaReadinessCards" :key="card.title" class="readiness-card">
              <div>
                <span>{{ card.title }}</span>
                <strong>{{ card.note }}</strong>
              </div>
              <ElTag :type="card.type" effect="light">{{ card.value }}</ElTag>
            </div>
          </div>
          <div class="template-preview">
            <div>
              <strong>模板字段预览</strong>
              <span>下载模板前先确认字段范围，避免导入时再返工。</span>
            </div>
            <div class="template-preview-grid">
              <section>
                <span>初始接入</span>
                <div>
                  <ElTag v-for="field in createImportFieldLabels" :key="field" type="info" effect="plain">
                    {{ field }}
                  </ElTag>
                </div>
              </section>
              <section>
                <span>系统外已完成</span>
                <div>
                  <ElTag v-for="field in createExternalCompletedLabels" :key="field" type="warning" effect="plain">
                    {{ field }}
                  </ElTag>
                </div>
              </section>
              <section>
                <span>现场必采</span>
                <div>
                  <ElTag v-for="field in createRequiredFieldCollectionLabels" :key="field" type="success" effect="plain">
                    {{ field }}
                  </ElTag>
                  <ElTag v-for="field in createRequiredPhotoLabels" :key="`photo-${field}`" type="danger" effect="plain">
                    {{ field }}
                  </ElTag>
                </div>
              </section>
            </div>
          </div>
        </div>

        <div class="schema-section">
          <FieldGraphDesigner
            :primary-field="createForm.primaryField"
            :aggregate-field="createForm.aggregateField"
            :custom-fields="createForm.customFields"
            :dashboard-metrics="createForm.dashboardMetrics"
            :template-preview="createTemplateBindingPreview"
            :editable="true"
            @update-parent="handleCreateFieldParentUpdate"
            @update-field="handleCreateFieldUpdate"
            @update-dashboard-metrics="handleCreateDashboardMetricsUpdate"
            @apply-replacement-template="handleCreateReplacementTemplateApply"
            @template-action="handleCreateTemplateAction"
          />
        </div>

        <div class="schema-section">
          <div class="schema-heading">
            <strong>工单关键字段</strong>
            <span>定义每个工单围绕什么对象管理，以及如何按现场维度汇总。</span>
          </div>
          <div class="field-grid two-columns">
            <div class="field-block">
              <span class="field-block-title">主字段</span>
              <ElSelect
                :model-value="createForm.primaryField.key"
                filterable
                placeholder="选择常见主字段"
                @change="applyCreatePrimaryFieldPreset"
              >
                <ElOption
                  v-for="preset in primaryFieldPresetOptions()"
                  :key="preset.key"
                  :label="preset.label"
                  :value="preset.key"
                />
              </ElSelect>
              <ElInput v-model="createForm.primaryField.label" placeholder="显示名称，例如电能表" />
              <ElInput v-model="createForm.primaryField.key" placeholder="字段编码，例如 meter_no" />
            </div>
            <div class="field-block">
              <span class="field-block-title">聚合字段</span>
              <ElSelect
                :model-value="createForm.aggregateField.key"
                filterable
                placeholder="选择常见聚合字段"
                @change="applyCreateAggregateFieldPreset"
              >
                <ElOption
                  v-for="preset in aggregateFieldPresetOptions(createForm)"
                  :key="preset.key"
                  :label="preset.label"
                  :value="preset.key"
                  :disabled="preset.group === 'aggregate' && createForm.primaryField.key === preset.key"
                />
              </ElSelect>
              <ElInput v-model="createForm.aggregateField.label" placeholder="显示名称，例如台区" />
              <ElInput v-model="createForm.aggregateField.key" placeholder="字段编码，例如 area_no" />
            </div>
          </div>
        </div>

        <div class="schema-section">
          <div class="schema-heading">
            <strong>业务子字段</strong>
            <ElButton size="small" :icon="Plus" @click="addCustomField">添加字段</ElButton>
          </div>
          <div class="custom-field-list">
            <div v-for="(field, index) in createForm.customFields" :key="index" class="custom-field-row">
              <ElInput v-model="field.label" placeholder="字段名称，例如 模块 / 通讯模块 / 总表" />
              <ElInput v-model="field.key" placeholder="字段编码" />
              <ElSelect v-model="field.source" placeholder="来源">
                <ElOption
                  v-for="option in sourceOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </ElSelect>
              <ElSelect v-model="field.captureMethod" placeholder="采集方式">
                <ElOption
                  v-for="option in captureMethodOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </ElSelect>
              <ElSelect v-model="field.dataType" placeholder="格式">
                <ElOption
                  v-for="option in dataTypeOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </ElSelect>
              <ElSelect v-model="field.parentKey" placeholder="归属">
                <ElOption
                  v-for="option in fieldParentOptions()"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </ElSelect>
              <ElSwitch v-model="field.required" active-text="必填" inactive-text="可选" />
              <ElSwitch v-model="field.showInConstructionPanel" active-text="施工展示" inactive-text="施工隐藏" />
              <ElButton size="small" :disabled="createForm.customFields.length <= 1" @click="removeCustomField(index)">
                删除
              </ElButton>
            </div>
          </div>
        </div>

        <div class="schema-section">
          <div class="schema-heading">
            <strong>平台必备字段</strong>
            <span>用于 KPI、效率、审阅和追溯，创建后由系统保留。</span>
          </div>
          <div class="required-field-tags">
            <ElTag v-for="field in platformRequiredFields" :key="field" type="info">
              {{ field }}
            </ElTag>
          </div>
        </div>
      </ElForm>
      <template #footer>
        <ElButton @click="createDialogVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="creatingProject" @click="submitCreateProject">创建草稿</ElButton>
      </template>
    </ElDialog>

    <ElDialog
      v-model="schemaDialogVisible"
      :title="schemaProject ? `字段配置：${schemaProject.name}` : '字段配置'"
      width="860px"
    >
      <ElForm label-position="top">
        <div class="schema-section first-section">
          <div class="schema-heading">
            <strong>配置体检</strong>
            <span>用业务语言检查这个项目能否生成模板、指导现场采集并进入审阅。</span>
          </div>
          <div class="readiness-grid">
            <div v-for="card in schemaReadinessPreviewCards" :key="card.title" class="readiness-card">
              <div>
                <span>{{ card.title }}</span>
                <strong>{{ card.note }}</strong>
              </div>
              <ElTag :type="card.type" effect="light">{{ card.value }}</ElTag>
            </div>
          </div>
          <div v-if="schemaProject" class="readiness-server-panel">
            <div class="readiness-server-header">
              <div>
                <strong>上线检查</strong>
                <span>按已保存配置检查字段、证据、KPI 和流程是否可接入。</span>
              </div>
              <ElButton
                size="small"
                :loading="loadingReadinessProjectId === schemaProject.id"
                @click="loadProjectReadiness(schemaProject)"
              >
                重新检查
              </ElButton>
            </div>
            <template v-if="schemaProjectReadiness">
              <div class="readiness-server-summary">
                <ElTag :type="readinessStatusType(schemaProjectReadiness)" effect="dark">
                  {{ schemaProjectReadiness.ready ? '可接入' : '需补齐' }}
                </ElTag>
                <span>{{ readinessSummaryText(schemaProjectReadiness) }}</span>
              </div>
              <div class="readiness-check-list">
                <article
                  v-for="check in schemaProjectReadiness.checks"
                  :key="check.id"
                  :class="`status-${check.status}`"
                >
                  <ElTag :type="check.status === 'passed' ? 'success' : 'danger'" size="small" effect="light">
                    {{ check.status === 'passed' ? '通过' : '缺项' }}
                  </ElTag>
                  <div>
                    <span>{{ readinessGroupLabel(check.group) }}</span>
                    <strong>{{ readinessCheckLabel(check) }}</strong>
                    <small>{{ readinessActionText(check.action) }}</small>
                  </div>
                </article>
              </div>
              <div v-if="schemaProjectReadiness.nextActions.length" class="readiness-next-actions">
                <strong>下一步</strong>
                <ElTag
                  v-for="action in schemaProjectReadiness.nextActions"
                  :key="action"
                  :type="schemaProjectReadiness.ready ? 'success' : 'warning'"
                  effect="plain"
                >
                  {{ readinessActionText(action) }}
                </ElTag>
              </div>
            </template>
            <div v-else class="readiness-server-empty">
              {{ loadingReadinessProjectId === schemaProject.id ? '正在读取上线检查...' : '打开后会自动读取已保存配置的上线检查。' }}
            </div>
          </div>
          <div v-if="schemaProject" class="config-preflight-panel">
            <div class="readiness-server-header">
              <div>
                <strong>配置预检</strong>
                <span>只读检查历史草稿和运行到一半的项目接入风险，不加载、不保存、不迁移。</span>
              </div>
              <ElButton
                size="small"
                :loading="loadingProjectConfigPreflight"
                @click="loadProjectConfigPreflight"
              >
                刷新预检
              </ElButton>
            </div>
            <template v-if="projectConfigPreflight">
              <div class="config-preflight-grid">
                <section>
                  <span>历史草稿</span>
                  <strong>{{ configPreflightStatusText(projectConfigPreflight) }}</strong>
                  <small>{{ projectConfigPreflight.store.exists ? projectConfigPreflight.store.path : '暂无本地草稿文件' }}</small>
                </section>
                <section>
                  <span>阻断项目</span>
                  <strong>{{ projectConfigPreflight.summary.blockedProjects }}</strong>
                  <small>共 {{ projectConfigPreflight.summary.totalProjects }} 个草稿项目</small>
                </section>
                <section>
                  <span>只读预检</span>
                  <strong>{{ projectConfigPreflight.readyForConfigLoad ? '可继续配置' : '需先修配置' }}</strong>
                  <small>{{ projectConfigPreflight.summary.storeIssues }} 个草稿文件问题</small>
                </section>
              </div>
              <div class="persistence-tag-row">
                <strong>安全边界</strong>
                <ElTag
                  v-for="item in configPreflightSafetyItems"
                  :key="item"
                  type="warning"
                  effect="plain"
                >
                  {{ persistenceSafetyText(item) }}
                </ElTag>
              </div>
              <div v-if="projectConfigPreflight.issues.length || configPreflightBlockedProjects.length" class="config-preflight-issue-list">
                <article
                  v-for="issue in projectConfigPreflight.issues"
                  :key="`${issue.scope}-${issue.code}-${issue.message}`"
                  class="status-failed"
                >
                  <ElTag type="danger" size="small" effect="light">草稿文件</ElTag>
                  <div>
                    <strong>{{ issue.scope }}</strong>
                    <span>{{ configPreflightIssueText(issue) }}</span>
                  </div>
                </article>
                <article
                  v-for="project in configPreflightBlockedProjects"
                  :key="project.projectId"
                  class="status-failed"
                >
                  <ElTag type="danger" size="small" effect="light">阻断</ElTag>
                  <div>
                    <strong>{{ project.name }}</strong>
                    <span>{{ configPreflightIssueText(project.issues[0]) }}</span>
                    <small>{{ project.projectId }} · {{ project.issueCount }} 个问题</small>
                  </div>
                </article>
              </div>
            </template>
            <div v-else class="readiness-server-empty">
              {{ loadingProjectConfigPreflight ? '正在读取配置预检...' : '打开后会自动做一次历史草稿只读预检。' }}
            </div>
          </div>
          <div v-if="schemaProject" class="persistence-readiness-panel">
            <div class="readiness-server-header">
              <div>
                <strong>持久化准备</strong>
                <span>只读查看项目配置当前保存位置，以及迁移到 PostgreSQL 前的安全门槛。</span>
              </div>
              <ElButton
                size="small"
                :loading="loadingPersistenceReadinessProjectId === schemaProject.id"
                @click="loadProjectPersistenceReadiness(schemaProject)"
              >
                刷新准备状态
              </ElButton>
            </div>
            <template v-if="projectPersistenceStatus && schemaProjectPersistenceContract">
              <div class="persistence-status-grid">
                <section>
                  <span>当前存储</span>
                  <strong>{{ persistenceBackendText(projectConfigPersistenceStore?.backend) }}</strong>
                  <small>{{ projectConfigPersistenceStore?.exists ? '草稿文件已存在' : '等待首次保存配置' }}</small>
                </section>
                <section>
                  <span>数据库状态</span>
                  <strong>{{ persistenceDatabaseText(projectPersistenceStatus) }}</strong>
                  <small>{{ projectPersistenceStatus.database.urlRedacted || '没有数据库地址' }}</small>
                </section>
                <section>
                  <span>迁移审批</span>
                  <strong>{{ projectPersistenceStatus.database.migrationRequiredForPostgresPlatformConfig ? '需要审批后迁移' : '无需迁移' }}</strong>
                  <small>{{ persistenceBackendText(schemaProjectPersistenceContract.targetBackend) }}</small>
                </section>
                <section>
                  <span>还原检查</span>
                  <strong>{{ persistenceRoundtripText(schemaProjectPersistenceContract) }}</strong>
                  <small>{{ schemaProjectPersistenceContract.roundtrip.preservedKeys.length }} 项已保留</small>
                </section>
              </div>
              <div class="persistence-tag-row">
                <strong>目标表</strong>
                <ElTag
                  v-for="table in schemaProjectPersistenceContract.targetTables"
                  :key="table"
                  type="info"
                  effect="plain"
                >
                  {{ table }}
                </ElTag>
              </div>
              <div class="persistence-tag-row">
                <strong>安全门槛</strong>
                <ElTag
                  v-for="item in projectPersistenceSafetyItems"
                  :key="item"
                  type="warning"
                  effect="plain"
                >
                  {{ persistenceSafetyText(item) }}
                </ElTag>
              </div>
              <div v-if="projectMigrationReadiness" class="migration-gate-list">
                <div class="migration-gate-heading">
                  <strong>迁移门禁</strong>
                  <span>{{ projectMigrationReadiness.readyForMigration ? '已满足迁移条件' : '未放行，需先完成备份、dry-run、回滚和审批' }}</span>
                </div>
                <article
                  v-for="item in projectMigrationReadiness.gateItems"
                  :key="item.id"
                  :class="`status-${item.status}`"
                >
                  <ElTag :type="item.status === 'passed' ? 'success' : 'warning'" size="small" effect="light">
                    {{ migrationGateStatusText(item.status) }}
                  </ElTag>
                  <div>
                    <strong>{{ item.label }}</strong>
                    <span>{{ item.description }}</span>
                    <small>{{ item.evidence }}</small>
                  </div>
                </article>
              </div>
            </template>
            <div v-else class="readiness-server-empty">
              {{ loadingPersistenceReadinessProjectId === schemaProject.id ? '正在读取持久化准备...' : '打开后会自动读取持久化准备状态。' }}
            </div>
          </div>
          <div class="template-preview">
            <div>
              <strong>模板字段预览</strong>
              <span>{{ loadingSchemaTemplatePreview ? '正在按后端模板规则重新计算...' : '预览已与真实下载模板规则对齐。' }}</span>
            </div>
            <div class="template-preview-grid">
              <section>
                <span>初始接入</span>
                <div>
                  <ElTag v-for="field in schemaInitialTemplatePreviewLabels" :key="field" type="info" effect="plain">
                    {{ field }}
                  </ElTag>
                </div>
              </section>
              <section>
                <span>系统外已完成</span>
                <div>
                  <ElTag v-for="field in schemaExternalCompletedPreviewLabels" :key="field" type="warning" effect="plain">
                    {{ field }}
                  </ElTag>
                </div>
              </section>
              <section>
                <span>现场必采</span>
                <div>
                  <ElTag v-for="field in schemaSiteRequiredPreviewLabels" :key="field" type="success" effect="plain">
                    {{ field }}
                  </ElTag>
                </div>
              </section>
            </div>
          </div>
        </div>

        <div class="schema-section">
          <FieldGraphDesigner
            :primary-field="schemaForm.primaryField"
            :aggregate-field="schemaForm.aggregateField"
            :custom-fields="schemaForm.customFields"
            :platform-required-fields="schemaProject?.workItemSchema?.platformRequiredFields || []"
            :dashboard-metrics="schemaForm.dashboardMetrics"
            :template-preview="schemaTemplateBindingPreview"
            :backend-readiness-check="schemaDeviceHierarchyReadinessCheck"
            :editable="schemaProject?.status === 'draft'"
            @update-parent="handleSchemaFieldParentUpdate"
            @update-field="handleSchemaFieldUpdate"
            @update-dashboard-metrics="handleSchemaDashboardMetricsUpdate"
            @apply-replacement-template="handleSchemaReplacementTemplateApply"
            @template-action="handleSchemaTemplateAction"
          />
        </div>

        <div class="schema-section">
          <div class="schema-heading">
            <strong>工单关键字段</strong>
            <span>草稿项目可调整，正式项目需走变更评审。</span>
          </div>
          <div class="field-grid two-columns">
            <div class="field-block">
              <span class="field-block-title">主字段</span>
              <ElSelect
                :model-value="schemaForm.primaryField.key"
                filterable
                placeholder="选择常见主字段"
                :disabled="schemaProject?.status !== 'draft'"
                @change="applySchemaPrimaryFieldPreset"
              >
                <ElOption
                  v-for="preset in primaryFieldPresetOptions()"
                  :key="preset.key"
                  :label="preset.label"
                  :value="preset.key"
                />
              </ElSelect>
              <ElInput v-model="schemaForm.primaryField.label" :disabled="schemaProject?.status !== 'draft'" />
              <ElInput v-model="schemaForm.primaryField.key" :disabled="schemaProject?.status !== 'draft'" />
            </div>
            <div class="field-block">
              <span class="field-block-title">聚合字段</span>
              <ElSelect
                :model-value="schemaForm.aggregateField.key"
                filterable
                placeholder="选择常见聚合字段"
                :disabled="schemaProject?.status !== 'draft'"
                @change="applySchemaAggregateFieldPreset"
              >
                <ElOption
                  v-for="preset in aggregateFieldPresetOptions(schemaForm)"
                  :key="preset.key"
                  :label="preset.label"
                  :value="preset.key"
                  :disabled="preset.group === 'aggregate' && schemaForm.primaryField.key === preset.key"
                />
              </ElSelect>
              <ElInput v-model="schemaForm.aggregateField.label" :disabled="schemaProject?.status !== 'draft'" />
              <ElInput v-model="schemaForm.aggregateField.key" :disabled="schemaProject?.status !== 'draft'" />
            </div>
          </div>
        </div>

        <div class="schema-section">
          <div class="schema-heading">
            <strong>业务子字段</strong>
            <ElButton
              size="small"
              :icon="Plus"
              :disabled="schemaProject?.status !== 'draft'"
              @click="addSchemaCustomField"
            >
              添加字段
            </ElButton>
          </div>
          <div class="custom-field-list">
            <div v-for="(field, index) in schemaForm.customFields" :key="index" class="custom-field-row">
              <ElInput v-model="field.label" placeholder="字段名称" :disabled="schemaProject?.status !== 'draft'" />
              <ElInput v-model="field.key" placeholder="字段编码" :disabled="schemaProject?.status !== 'draft'" />
              <ElSelect v-model="field.source" placeholder="来源" :disabled="schemaProject?.status !== 'draft'">
                <ElOption
                  v-for="option in sourceOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </ElSelect>
              <ElSelect
                v-model="field.captureMethod"
                placeholder="采集方式"
                :disabled="schemaProject?.status !== 'draft'"
              >
                <ElOption
                  v-for="option in captureMethodOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </ElSelect>
              <ElSelect v-model="field.dataType" placeholder="格式" :disabled="schemaProject?.status !== 'draft'">
                <ElOption
                  v-for="option in dataTypeOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </ElSelect>
              <ElSelect v-model="field.parentKey" placeholder="归属" :disabled="schemaProject?.status !== 'draft'">
                <ElOption
                  v-for="option in schemaFieldParentOptions()"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </ElSelect>
              <ElSwitch
                v-model="field.required"
                active-text="必填"
                inactive-text="可选"
                :disabled="schemaProject?.status !== 'draft'"
              />
              <ElSwitch
                v-model="field.showInConstructionPanel"
                active-text="施工展示"
                inactive-text="施工隐藏"
                :disabled="schemaProject?.status !== 'draft'"
              />
              <ElButton
                size="small"
                :disabled="schemaProject?.status !== 'draft' || schemaForm.customFields.length <= 1"
                @click="removeSchemaCustomField(index)"
              >
                删除
              </ElButton>
            </div>
          </div>
        </div>

        <div class="schema-section">
          <div class="schema-heading">
            <strong>平台必备字段</strong>
            <span>用于 KPI、效率、审阅和追溯，系统保留。</span>
          </div>
          <div class="required-field-tags">
            <ElTag
              v-for="field in schemaProject?.workItemSchema?.platformRequiredFields || []"
              :key="field.key"
              type="info"
            >
              {{ field.label }}
            </ElTag>
          </div>
        </div>
      </ElForm>
      <template #footer>
        <ElButton @click="schemaDialogVisible = false">关闭</ElButton>
        <ElButton
          type="primary"
          :loading="savingSchema"
          :disabled="schemaProject?.status !== 'draft'"
          @click="submitSchemaUpdate"
        >
          保存配置
        </ElButton>
      </template>
    </ElDialog>

    <ElDialog
      v-model="workflowDialogVisible"
      :title="workflowProject ? `流程配置：${workflowProject.name}` : '流程配置'"
      width="min(980px, 94vw)"
    >
      <WorkflowEditor
        :project="workflowProject"
        :workflow="projectWorkflow"
        :loading="loadingWorkflow"
        :saving="savingWorkflow"
        :resetting="resettingWorkflow"
        @save="handleWorkflowSave"
        @reset="handleWorkflowReset"
        @close="workflowDialogVisible = false"
      />
    </ElDialog>

    <ElDialog
      v-model="validationDialogVisible"
      :title="`导入前校验报告：${validationProjectName || '项目模板'}`"
      width="820px"
    >
      <div v-if="templateValidationReport" class="validation-report">
        <div class="validation-summary">
          <div>
            <span>模板类型</span>
            <strong>{{ templateTypeLabel(validationTemplateType) }}</strong>
          </div>
          <div>
            <span>数据行</span>
            <strong>{{ templateValidationReport.summary.total_rows }}</strong>
          </div>
          <div>
            <span>错误</span>
            <strong>{{ templateValidationReport.summary.error_count }}</strong>
          </div>
          <div>
            <span>建议</span>
            <strong>{{ templateValidationReport.summary.warning_count }}</strong>
          </div>
          <ElTag :type="validationStatusType(templateValidationReport.status)" effect="dark">
            {{ validationStatusLabel(templateValidationReport.status) }}
          </ElTag>
        </div>
        <div class="import-wizard-steps" aria-label="导入接入步骤">
          <article
            v-for="step in importWizardStepCards"
            :key="step.title"
            :class="`state-${step.state}`"
          >
            <strong>{{ step.title }}</strong>
            <span>{{ step.description }}</span>
          </article>
        </div>
        <div class="import-wizard-next-hint">
          <strong>下一步建议</strong>
          <span>{{ importWizardNextActionHint }}</span>
        </div>
        <div class="expected-headers">
          <span>应包含字段</span>
          <div>
            <ElTag v-for="header in templateValidationReport.expected_headers" :key="header" effect="plain">
              {{ header }}
            </ElTag>
          </div>
        </div>
        <div
          v-if="hierarchyValidationItems.length"
          class="validation-hierarchy-panel"
          aria-label="层级证据缺口"
        >
          <div class="validation-hierarchy-heading">
            <strong>层级证据缺口</strong>
            <span>条件采集缺失</span>
          </div>
          <div class="validation-hierarchy-list">
            <article
              v-for="item in hierarchyValidationItems"
              :key="`${item.row || 'sheet'}-${item.field_key}-${item.message}`"
            >
              <ElTag type="warning" effect="light" size="small">{{ validationIssueRowLabel(item) }}</ElTag>
              <div>
                <strong>{{ item.field_label || item.field_key }}</strong>
                <span>{{ item.message }}</span>
              </div>
              <small v-if="item.value">当前值：{{ item.value }}</small>
            </article>
          </div>
        </div>
        <ElTable :data="templateValidationReport.items" border max-height="360" empty-text="没有发现问题">
          <ElTableColumn label="级别" width="90">
            <template #default="{ row }">
              <ElTag :type="validationSeverityType(row.severity)" effect="light">
                {{ validationSeverityLabel(row.severity) }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="row" label="行号" width="80" />
          <ElTableColumn prop="field_label" label="字段" width="160" />
          <ElTableColumn prop="message" label="说明" min-width="240" />
          <ElTableColumn prop="value" label="当前值" min-width="120" />
        </ElTable>
        <div v-if="importDraftJob" class="import-draft-summary">
          <div>
            <span>导入草稿</span>
            <strong>{{ importDraftJob.jobId }}</strong>
          </div>
          <div>
            <span>可接入行</span>
            <strong>{{ importDraftSummary(importDraftJob).readyRows }} / {{ importDraftSummary(importDraftJob).totalRows }}</strong>
          </div>
          <div>
            <span>预览行</span>
            <strong>{{ importDraftSummary(importDraftJob).previewRows }}</strong>
          </div>
          <div>
            <span>层级缺口</span>
            <strong>{{ importDraftSummary(importDraftJob).hierarchyGapCount }}</strong>
          </div>
          <ElTag :type="importDraftSummary(importDraftJob).hierarchyGapCount ? 'warning' : 'success'" effect="light">
            dry-run
          </ElTag>
          <div
            v-if="importDraftSummary(importDraftJob).hierarchyGapItems.length"
            class="import-draft-hierarchy-gaps"
          >
            <article
              v-for="item in importDraftSummary(importDraftJob).hierarchyGapItems"
              :key="`${item.row || 'sheet'}-${item.fieldKey}-${item.message}`"
            >
              <ElTag type="warning" effect="light" size="small">
                {{ item.row ? `第 ${item.row} 行` : '整表' }}
              </ElTag>
              <span>{{ item.fieldLabel || item.fieldKey }}</span>
              <small>{{ item.message }}</small>
            </article>
          </div>
        </div>
        <div v-if="importBatchJob" class="import-draft-summary">
          <div>
            <span>导入批次</span>
            <strong>{{ importBatchJob.jobId }}</strong>
          </div>
          <div>
            <span>记录行数</span>
            <strong>{{ importDraftSummary(importBatchJob).readyRows }} / {{ importDraftSummary(importBatchJob).totalRows }}</strong>
          </div>
          <div>
            <span>工单创建</span>
            <strong>0</strong>
          </div>
          <ElTag type="warning" effect="light">recorded</ElTag>
        </div>
        <div v-if="workOrderTaskJob" class="import-draft-summary">
          <div>
            <span>工单任务</span>
            <strong>{{ workOrderTaskJob.jobId }}</strong>
          </div>
          <div>
            <span>计划工单</span>
            <strong>{{ workOrderTaskSummary(workOrderTaskJob).plannedWorkOrders }}</strong>
          </div>
          <div>
            <span>已创建工单</span>
            <strong>{{ workOrderTaskSummary(workOrderTaskJob).createdWorkOrders }}</strong>
          </div>
          <ElTag :type="workOrderTaskStatusType(workOrderTaskJob)" effect="light">
            {{ workOrderTaskStatusLabel(workOrderTaskJob) }}
          </ElTag>
        </div>
      </div>
      <template #footer>
        <ElButton @click="validationDialogVisible = false">关闭</ElButton>
        <ElButton
          :type="importWizardPrimaryType"
          :loading="importWizardPrimaryLoading"
          :disabled="!canRunImportWizardPrimaryAction"
          @click="runImportWizardPrimaryAction"
        >
          {{ importWizardPrimaryLabel }}
        </ElButton>
        <ElButton
          v-if="canRollbackWorkOrderTask()"
          :loading="rollingBackWorkOrderTask"
          @click="rollbackWorkOrderTaskFromExecution"
        >
          回滚工单任务
        </ElButton>
        <ElButton
          v-if="canOpenImportWizardNextActions"
          type="success"
          plain
          @click="openImportWizardNextAction('/construction')"
        >
          去施工采集
        </ElButton>
        <ElButton
          v-if="canOpenImportWizardNextActions"
          type="primary"
          plain
          @click="openImportWizardNextAction('/task-hall')"
        >
          去审阅工作台
        </ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped>
.toolbar-actions,
.row-actions,
.metric-pair {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar-actions,
.row-actions {
  flex-wrap: wrap;
}

.project-cell {
  display: grid;
  gap: 4px;
}

.handoff-readiness-band,
.readiness-summary-band {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.handoff-readiness-band {
  border-color: var(--el-color-primary-light-7);
  background: var(--el-color-primary-light-9);
}

.handoff-readiness-band > div,
.readiness-summary-band > div,
.project-list-readiness-cell {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.readiness-action-todos {
  flex: 1 1 auto;
}

.readiness-action-todos > div {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.readiness-action-tag {
  cursor: pointer;
}

.readiness-filter-state {
  min-width: 160px;
}

.handoff-readiness-band span,
.readiness-summary-band span,
.project-list-readiness-cell span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.handoff-readiness-band strong,
.readiness-summary-band strong {
  color: var(--el-text-color-primary);
  font-size: 14px;
  overflow-wrap: anywhere;
}

.project-list-config-preflight-details {
  display: grid;
  gap: 10px;
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid var(--el-color-danger-light-7);
  border-radius: 8px;
  background: var(--el-color-danger-light-9);
}

.project-list-config-preflight-detail-head {
  display: grid;
  gap: 3px;
}

.project-list-config-preflight-detail-head span,
.project-list-config-preflight-detail-head small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.project-list-config-preflight-detail-head strong {
  color: var(--el-text-color-primary);
  font-size: 14px;
}

.project-list-config-preflight-detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.project-list-config-preflight-detail-grid article {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  min-width: 0;
  padding: 9px;
  border: 1px solid var(--el-color-danger-light-6);
  border-radius: 8px;
  background: #fff;
}

.project-list-config-preflight-detail-grid article > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.project-list-config-preflight-detail-grid strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.project-list-config-preflight-detail-grid span,
.project-list-config-preflight-detail-grid small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

@media (max-width: 720px) {
  .handoff-readiness-band {
    display: grid;
    grid-template-columns: 1fr;
    align-items: stretch;
  }

  .project-list-config-preflight-detail-grid {
    grid-template-columns: 1fr;
  }
}

.template-usage-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.template-usage-card {
  display: grid;
  gap: 8px;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.template-usage-card > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.template-usage-card span {
  color: var(--el-text-color-primary);
  font-weight: 700;
}

.template-usage-card p,
.template-usage-card small {
  margin: 0;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}

.template-usage-card small {
  color: var(--el-color-primary);
  font-weight: 600;
}

.project-cell strong {
  color: var(--el-text-color-primary);
}

.project-cell span,
.subline,
.metric-pair {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.metric-pair {
  justify-content: flex-start;
}

.platform-kpi-line {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
}

.platform-delivery-kpi-line {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  color: var(--el-color-primary);
  font-weight: 600;
}

.platform-review-quality-line {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  color: var(--el-color-warning-dark-2);
  font-weight: 600;
}

.module-checkboxes {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 12px;
}

.preset-hierarchy-guidance {
  display: grid;
  gap: 8px;
  margin: -4px 0 12px;
  padding: 12px;
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 8px;
  background: var(--el-color-primary-light-9);
}

.preset-hierarchy-guidance__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.preset-hierarchy-guidance__head > div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.preset-hierarchy-guidance span,
.preset-hierarchy-guidance small,
.preset-hierarchy-guidance p {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.preset-hierarchy-guidance strong {
  color: var(--el-text-color-primary);
  font-size: 15px;
  line-height: 1.35;
}

.preset-hierarchy-guidance__facts {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.preset-hierarchy-guidance__facts small {
  padding: 3px 7px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 999px;
  background: #fff;
  color: var(--el-text-color-primary);
}

.schema-section {
  display: grid;
  gap: 12px;
  padding: 14px 0;
  border-top: 1px solid var(--el-border-color-lighter);
}

.first-section {
  padding-top: 0;
  border-top: 0;
}

.schema-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.schema-heading strong,
.field-block-title {
  color: var(--el-text-color-primary);
  font-size: 14px;
}

.schema-heading span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.field-grid {
  display: grid;
  gap: 12px;
}

.two-columns {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.field-block {
  display: grid;
  gap: 8px;
}

.custom-field-list {
  display: grid;
  gap: 10px;
}

.custom-field-row {
  display: grid;
  grid-template-columns: minmax(112px, 1.2fr) minmax(110px, 1fr) repeat(4, minmax(96px, 0.9fr)) repeat(2, minmax(88px, auto)) auto;
  gap: 8px;
  align-items: center;
}

.required-field-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.readiness-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.readiness-card {
  display: flex;
  min-width: 0;
  min-height: 92px;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.readiness-card > div {
  display: grid;
  min-width: 0;
  gap: 6px;
}

.readiness-card span,
.template-preview span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.readiness-card strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.readiness-server-panel {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: #fff;
}

.readiness-server-header,
.readiness-server-summary,
.readiness-next-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.readiness-server-header {
  justify-content: space-between;
}

.readiness-server-header > div {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.readiness-server-header strong,
.readiness-next-actions strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
}

.readiness-server-header span,
.readiness-server-summary span,
.readiness-server-empty,
.readiness-check-list span,
.readiness-check-list small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.readiness-check-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.readiness-check-list article {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  min-width: 0;
  padding: 9px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.readiness-check-list article.status-failed {
  border-color: var(--el-color-danger-light-7);
  background: var(--el-color-danger-light-9);
}

.readiness-check-list article > div {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.readiness-check-list strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.readiness-next-actions {
  flex-wrap: wrap;
  padding-top: 2px;
}

.persistence-readiness-panel,
.config-preflight-panel {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: #fff;
}

.persistence-status-grid,
.config-preflight-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.config-preflight-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.persistence-status-grid section,
.config-preflight-grid section {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.persistence-status-grid span,
.persistence-status-grid small,
.config-preflight-grid span,
.config-preflight-grid small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.persistence-status-grid strong,
.config-preflight-grid strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.config-preflight-issue-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.config-preflight-issue-list article {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  min-width: 0;
  padding: 9px;
  border: 1px solid var(--el-color-danger-light-7);
  border-radius: 8px;
  background: var(--el-color-danger-light-9);
}

.config-preflight-issue-list article > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.config-preflight-issue-list strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.config-preflight-issue-list span,
.config-preflight-issue-list small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.persistence-tag-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.persistence-tag-row strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
}

.migration-gate-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.migration-gate-heading {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.migration-gate-heading strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
}

.migration-gate-heading span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.migration-gate-list article {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  min-width: 0;
  padding: 9px;
  border: 1px solid var(--el-color-warning-light-7);
  border-radius: 8px;
  background: var(--el-color-warning-light-9);
}

.migration-gate-list article > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.migration-gate-list strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
  line-height: 1.35;
}

.migration-gate-list span,
.migration-gate-list small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.template-preview {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.template-preview > div:first-child {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.template-preview > div:first-child strong {
  color: var(--el-text-color-primary);
}

.template-preview-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.template-preview-grid section {
  display: grid;
  align-content: start;
  gap: 8px;
  min-width: 0;
}

.template-preview-grid section > div {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.hidden-file-input {
  display: none;
}

.validation-report {
  display: grid;
  gap: 14px;
}

.validation-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr)) auto;
  gap: 10px;
  align-items: stretch;
}

.validation-summary > div {
  display: grid;
  gap: 4px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.validation-summary span,
.expected-headers > span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.validation-summary strong {
  color: var(--el-text-color-primary);
  font-size: 15px;
}

.import-wizard-steps {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.import-wizard-steps article {
  display: grid;
  align-content: start;
  gap: 6px;
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.import-wizard-steps article strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
}

.import-wizard-steps article span,
.import-wizard-next-hint span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.import-wizard-steps .state-done {
  border-color: var(--el-color-success-light-5);
  background: var(--el-color-success-light-9);
}

.import-wizard-steps .state-active {
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
}

.import-wizard-next-hint {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.import-wizard-next-hint strong {
  flex: 0 0 auto;
  color: var(--el-text-color-primary);
  font-size: 13px;
}

.expected-headers {
  display: grid;
  gap: 8px;
}

.expected-headers > div {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.validation-hierarchy-panel {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--el-color-warning-light-5);
  border-radius: 8px;
  background: var(--el-color-warning-light-9);
}

.validation-hierarchy-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}

.validation-hierarchy-heading strong {
  color: var(--el-text-color-primary);
  font-size: 14px;
}

.validation-hierarchy-heading span {
  color: var(--el-color-warning-dark-2);
  font-size: 12px;
}

.validation-hierarchy-list {
  display: grid;
  gap: 8px;
}

.validation-hierarchy-list article {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  min-width: 0;
  padding: 10px;
  border-radius: 8px;
  background: #fff;
}

.validation-hierarchy-list article > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.validation-hierarchy-list article strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
}

.validation-hierarchy-list article span,
.validation-hierarchy-list article small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.import-draft-summary {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) repeat(3, minmax(0, 1fr)) auto;
  gap: 10px;
  align-items: stretch;
  padding: 10px;
  border: 1px solid var(--el-color-success-light-5);
  border-radius: 8px;
  background: var(--el-color-success-light-9);
}

.import-draft-summary > div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.import-draft-hierarchy-gaps {
  grid-column: 1 / -1;
  display: grid;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--el-color-warning-light-5);
}

.import-draft-hierarchy-gaps article {
  display: grid;
  grid-template-columns: auto minmax(0, 0.8fr) minmax(0, 1.6fr);
  gap: 8px;
  align-items: center;
  min-width: 0;
}

.import-draft-hierarchy-gaps span {
  overflow: hidden;
  color: var(--el-text-color-primary);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.import-draft-hierarchy-gaps small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.import-draft-summary span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.import-draft-summary strong {
  overflow-wrap: anywhere;
  color: var(--el-text-color-primary);
  font-size: 14px;
}

@media (max-width: 860px) {
  :deep(.el-dialog) {
    width: calc(100vw - 20px) !important;
    max-width: calc(100vw - 20px);
    margin: 10px auto;
  }

  .two-columns,
  .custom-field-row,
  .readiness-grid,
  .readiness-check-list,
  .config-preflight-grid,
  .config-preflight-issue-list,
  .persistence-status-grid,
  .migration-gate-list,
  .template-preview-grid,
  .template-usage-grid,
  .import-wizard-steps,
  .validation-summary,
  .import-draft-summary {
    grid-template-columns: 1fr;
  }

  .import-wizard-next-hint {
    align-items: flex-start;
    flex-direction: column;
  }

  .validation-hierarchy-list article {
    grid-template-columns: 1fr;
    justify-items: start;
  }

  .import-draft-hierarchy-gaps article {
    grid-template-columns: 1fr;
    justify-items: start;
  }
}

:deep(.active-project-row td) {
  background: rgba(37, 99, 235, 0.06) !important;
}
</style>
