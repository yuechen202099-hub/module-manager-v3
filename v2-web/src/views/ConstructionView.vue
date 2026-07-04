<script setup lang="ts">
import {
  Camera,
  Close,
  Connection,
  FolderOpened,
  Picture,
  Refresh,
  Search,
  UploadFilled,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  currentActor,
  currentTeamId,
  fetchProjectConstructionWorkOrders,
  fetchProjectsWithModules,
  fetchConstructionExceptionOrders,
  fetchConstructionTaskGroups,
  fetchConstructionTasks,
  fetchGroup,
  fetchUnmatchedRecords,
  fetchUserAccounts,
  recordConstructionHeartbeat,
  recordConstructionNonIdleEvent,
  releaseConstructionTask,
  saveProjectConstructionWorkOrderCollection,
  submitConstructionExceptionOrder,
  uploadProjectConstructionWorkOrderPhoto,
  uploadConstructionBatch,
} from '@/api/services'
import type {
  ConstructionExceptionOrder,
  ConstructionPhotoSlot,
  MaterialGroup,
  PlatformConstructionFieldSchema,
  PlatformConstructionWorkOrder,
  Project,
  ProjectFieldDefinition,
  ReviewPhoto,
  ReviewTask,
  UnmatchedRecord,
  UserAccount,
} from '@/api/types'
import { APP_VERSION } from '@/constants/releaseNotes'
import { useAuthStore } from '@/stores/auth'
import {
  constructionDraftUploadBlockReason,
  constructionGroupOpenBlockReason,
  isCollectableConstructionGroup,
  isEmptyPlaceholderConstructionDraft,
  isPlaceholderConstructionDraft,
} from '@/utils/constructionDraftGuards'

type GroupFilter = 'unbuilt' | 'cached' | 'exception' | 'all'
type PhotoSource = 'camera' | 'album'
type ScannerTarget = 'quickMeter' | 'collector' | 'module' | 'dynamic'
type TaskPickerMode = 'terminal' | 'exception' | 'unmatched'

type DraftPhoto = {
  slot: string
  file?: Blob
  blob?: Blob
  filename?: string
  name?: string
  client_photo_id?: string
}

type CacheDraft = {
  client_batch_id: string
  teamId?: string
  actor?: string
  taskId?: string | number
  groupId?: string
  group_id?: string
  terminal?: string
  meter_no?: string
  address?: string
  collector?: string
  module_asset_no?: string
  work_order_id?: string
  exception_category?: string
  exception_note?: string
  covered_slots?: string[]
  field_values?: Record<string, string>
  photos?: DraftPhoto[]
  status?: string
  created_at?: string
  updated_at?: string
  client_completed_at?: string
}

type PhotoRequirementSource = {
  work_order_id?: string
  exception_order_id?: string
  exception_category?: string
  exception_note?: string
  category?: string
  note?: string
}

type TerminalSnapshot = {
  id: string
  actor: string
  taskId: string
  terminal: string
  task: ReviewTask
  groups: MaterialGroup[]
  exceptionOrders: ConstructionExceptionOrder[]
  updated_at: string
}

type WorkItem = {
  key: string
  kind: 'group' | 'cached' | 'exception' | 'platform'
  group: MaterialGroup
  order?: ConstructionExceptionOrder
  draft?: CacheDraft
  platformWorkOrder?: PlatformConstructionWorkOrder
}

type SiteChecklistItem = {
  key: string
  label: string
  group: 'field' | 'photo' | 'kpi'
  method: string
  intentLabel: string
  intentType: '' | 'success' | 'warning' | 'danger' | 'info'
  required: boolean
  done: boolean
  value: string
}

type ConstructionFieldSection = {
  id:
    | 'task-core'
    | 'main-device-replacement'
    | 'device-replacement'
    | 'accessory-confirmation'
    | 'conditional-accessory-fields'
    | 'supporting-fields'
  title: string
  helper: string
  fields: ProjectFieldDefinition[]
}

type ConstructionPhotoSection = {
  id: string
  title: string
  helper: string
  slots: ConstructionPhotoSlot[]
}

const defaultPhotoSlots: ConstructionPhotoSlot[] = [
  { key: 'before_box', label: '改造前照片', required: true },
  { key: 'collector_barcode', label: '采集器照片', required: false },
  { key: 'module_meter', label: '模块与电表照片', required: true },
  { key: 'after_box', label: '改造后照片', required: true },
]

const slotAliases: Record<string, string[]> = {
  before_box: ['before_box', '改造前', '表箱整体改造前'],
  collector_barcode: ['collector_barcode', '采集器', '条形码', '条码'],
  module_meter: ['module_meter', '模块与电表', '模块', '电能表', '电表'],
  after_box: ['after_box', '改造后', '表箱整体改造后'],
}

const DB_NAME = 'module-manager-construction-v1'
const DRAFT_STORE = 'drafts'
const SNAPSHOT_STORE = 'terminal_snapshots'
const SCANNER_START_TIMEOUT_MS = 7000
const HEARTBEAT_INTERVAL_MS = 60_000
const collator = new Intl.Collator('zh-Hans-CN', { numeric: true, sensitivity: 'base' })

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const actor = computed(() => auth.user?.username || auth.user?.id || currentActor())
const teamId = computed(() => auth.user?.teamId || currentTeamId())
const isAdmin = computed(() => auth.user?.role === 'admin' || auth.user?.roles?.includes('admin'))

const loadingTasks = ref(false)
const loadingGroups = ref(false)
const uploading = ref(false)
const cacheBusy = ref(false)
const submittingTask = ref(false)
const loadingPlatformWorkOrders = ref(false)
const offlineMode = ref(false)
const tasks = ref<ReviewTask[]>([])
const groups = ref<MaterialGroup[]>([])
const exceptionOrders = ref<ConstructionExceptionOrder[]>([])
const fieldExceptionOrders = ref<ConstructionExceptionOrder[]>([])
const unmatchedRecords = ref<UnmatchedRecord[]>([])
const drafts = ref<CacheDraft[]>([])
const accountUsers = ref<UserAccount[]>([])
const platformProjects = ref<Project[]>([])
const platformConstructionWorkOrders = ref<PlatformConstructionWorkOrder[]>([])
const platformConstructionSchema = ref<PlatformConstructionFieldSchema | null>(null)
const platformConstructionTotal = ref(0)
const platformReworkOnly = ref(false)
const activePlatformWorkOrder = ref<PlatformConstructionWorkOrder | null>(null)
const taskPickerMode = ref<TaskPickerMode>('terminal')
const selectedTaskId = ref('')
const selectedItemKey = ref('')
const taskPickerOpen = ref(false)
const groupFilter = ref<GroupFilter>('all')
const groupQuery = ref('')
const taskQuery = ref('')
const submittedTaskQuery = ref('')
const quickMeter = ref('')
const errorMessage = ref('')
const collectOpen = ref(false)
const scannerOpen = ref(false)
const unbuiltDialogOpen = ref(false)
const unbuiltDialogLoading = ref(false)
const scannerTarget = ref<ScannerTarget>('quickMeter')
const scannerFieldKey = ref('')
const scannerStatus = ref('优先使用 QuaggaJS 识别一维条形码。')
const scannerHint = ref('将条形码横向放入框内，保持稳定')
const activeGroup = ref<MaterialGroup | null>(null)
const activeOrder = ref<ConstructionExceptionOrder | null>(null)
const selectedFiles = ref<Record<string, File | null>>({})
const previewUrls = ref<Record<string, string>>({})
const slotBusy = ref<Record<string, boolean>>({})
const scannerFileInput = ref<HTMLInputElement | null>(null)
const scannerCamera = ref<HTMLElement | null>(null)
const scannerVideo = ref<HTMLVideoElement | null>(null)
const fileInputs = new Map<string, HTMLInputElement>()
let scannerStream: MediaStream | null = null
let scannerTimer = 0
let quaggaActive = false
let quaggaDetectedHandler: ((result: unknown) => void) | null = null
let scanCandidate = ''
let scanCandidateHits = 0
let scanLocked = false
let draftPersistTimer = 0
let heartbeatTimer = 0
let suspendDraftAutoPersist = false

const form = reactive({
  collector: '',
  moduleAssetNo: '',
  dynamicFields: {} as Record<string, string>,
  note: '',
})
const platformKpiInputFields: ProjectFieldDefinition[] = [
  {
    key: 'started_at',
    label: '安装时间',
    dataType: 'datetime',
    source: 'field_collection',
    captureMethod: 'datetime',
    required: false,
    kpiEnabled: true,
    options: [],
  },
  {
    key: 'completed_at',
    label: '完成时间',
    dataType: 'datetime',
    source: 'field_collection',
    captureMethod: 'datetime',
    required: true,
    kpiEnabled: true,
    options: [],
  },
  {
    key: 'online_duration_minutes',
    label: '在线时长（分钟）',
    dataType: 'duration',
    source: 'system',
    captureMethod: 'manual',
    required: false,
    kpiEnabled: true,
    options: [],
  },
]
const unbuiltDialogTask = ref<ReviewTask | null>(null)
const unbuiltDialogGroups = ref<MaterialGroup[]>([])
const unbuiltDialogQuery = ref('')
const unbuiltDialogError = ref('')

const QUAGGA_READERS = [
  'code_128_reader',
  'code_39_reader',
  'code_93_reader',
  'i2of5_reader',
  'ean_reader',
  'ean_8_reader',
  'codabar_reader',
]

const userByUsername = computed(() => {
  const map = new Map<string, UserAccount>()
  for (const user of accountUsers.value) {
    if (user.username && (!user.teamId || user.teamId === teamId.value)) map.set(user.username, user)
  }
  return map
})

const activeProjectId = computed(() => String(route.query.project_id || 'replacement-project').trim() || 'replacement-project')
const activeProject = computed(() => platformProjects.value.find((project) => project.id === activeProjectId.value) || null)
const constructionFields = computed(() => {
  const fields = activeProject.value?.workItemSchema?.customFields || []
  return fields.filter((field) => field.showInConstructionPanel !== false && field.source === 'field_collection' && field.dataType !== 'image')
})
const schemaPhotoSlots = computed<ConstructionPhotoSlot[]>(() => {
  const fields = activeProject.value?.workItemSchema?.customFields || []
  return fields
    .filter((field) => field.showInConstructionPanel !== false && field.source === 'field_collection' && field.dataType === 'image')
    .map((field) => ({
      key: field.key,
      label: field.label,
      required: field.required,
      requiredWhen: field.requiredWhen,
      relationRole: field.relationRole,
    }))
})
const photoSlots = computed(() => (schemaPhotoSlots.value.length ? schemaPhotoSlots.value : defaultPhotoSlots))
const hasConfiguredConstructionFields = computed(() => constructionFields.value.length > 0)
const activeConstructionFields = computed(() => constructionFields.value.filter((field) => isFieldConditionActive(field)))
const activePhotoSlots = computed(() => photoSlots.value.filter((slot) => isPhotoSlotConditionActive(slot)))
const activePhotoSlotKeys = computed(() => new Set(activePhotoSlots.value.map((slot) => slot.key)))
const constructionFieldSections = computed<ConstructionFieldSection[]>(() => {
  const sections = constructionFieldSectionsBase()
  const sectionById = new Map(sections.map((section) => [section.id, section]))
  for (const field of constructionFields.value) {
    sectionById.get(constructionFieldSectionId(field))?.fields.push(field)
  }
  return sections.filter((section) => section.fields.length)
})
const activeConstructionFieldSections = computed<ConstructionFieldSection[]>(() => {
  const sections = constructionFieldSectionsBase()
  const sectionById = new Map(sections.map((section) => [section.id, section]))
  for (const field of activeConstructionFields.value) {
    sectionById.get(constructionFieldSectionId(field))?.fields.push(field)
  }
  return sections.filter((section) => section.fields.length)
})
const constructionPhotoSections = computed<ConstructionPhotoSection[]>(() => {
  if (!photoSlots.value.length) return []
  const evidenceSlots = photoSlots.value.filter((slot) => slot.relationRole === 'evidence_photo')
  const otherSlots = photoSlots.value.filter((slot) => slot.relationRole !== 'evidence_photo')
  return [
    {
      id: 'evidence-photo',
      title: '照片证据',
      helper: '按项目模板补齐改造前、旧设备、新旧模块和改造后等影像资料。',
      slots: evidenceSlots.length ? evidenceSlots : photoSlots.value,
    },
    {
      id: 'other-photo',
      title: '补充照片',
      helper: '项目额外要求的照片资料。',
      slots: evidenceSlots.length ? otherSlots : [],
    },
  ].filter((section) => section.slots.length)
})
const activeConstructionPhotoSections = computed<ConstructionPhotoSection[]>(() => {
  if (!activePhotoSlots.value.length) return []
  const evidenceSlots = activePhotoSlots.value.filter((slot) => slot.relationRole === 'evidence_photo')
  const otherSlots = activePhotoSlots.value.filter((slot) => slot.relationRole !== 'evidence_photo')
  return [
    {
      id: 'evidence-photo',
      title: '照片证据',
      helper: '按项目模板补齐改造前、旧设备、新旧模块和改造后等影像资料。',
      slots: evidenceSlots.length ? evidenceSlots : activePhotoSlots.value,
    },
    {
      id: 'other-photo',
      title: '补充照片',
      helper: '项目额外要求的照片资料。',
      slots: evidenceSlots.length ? otherSlots : [],
    },
  ].filter((section) => section.slots.length)
})
const platformConstructionReworkOrders = computed(() =>
  platformConstructionWorkOrders.value.filter((order) => platformWorkOrderNeedsRework(order)),
)
const platformConstructionDisplayOrders = computed(() => {
  const source = platformReworkOnly.value ? platformConstructionReworkOrders.value : platformConstructionWorkOrders.value
  return [...source].sort((left, right) => {
    const leftRework = platformWorkOrderNeedsRework(left) ? 1 : 0
    const rightRework = platformWorkOrderNeedsRework(right) ? 1 : 0
    if (leftRework !== rightRework) return rightRework - leftRework
    return String(left.primaryValue || left.id).localeCompare(String(right.primaryValue || right.id), 'zh-Hans-CN', { numeric: true })
  })
})
const platformConstructionPreview = computed(() => platformConstructionDisplayOrders.value.slice(0, 5))
const platformConstructionDisplayFields = computed(() => platformConstructionSchema.value?.displayFields || [])
const platformConstructionFields = computed(() => platformConstructionSchema.value?.constructionFields || [])
const platformConstructionFieldSections = computed<ConstructionFieldSection[]>(() => {
  const sections = constructionFieldSectionsBase()
  const sectionById = new Map(sections.map((section) => [section.id, section]))
  for (const field of platformConstructionFields.value) {
    sectionById.get(constructionFieldSectionId(field))?.fields.push(field)
  }
  return sections.filter((section) => section.fields.length)
})
const platformConstructionPhotoSlots = computed(() => platformConstructionSchema.value?.photoSlots || [])
const platformPrimaryLabel = computed(() => platformConstructionSchema.value?.primaryField?.label || activeProject.value?.workItemSchema?.primaryField?.label || '主字段')
const platformAggregateLabel = computed(
  () => platformConstructionSchema.value?.aggregateField?.label || activeProject.value?.workItemSchema?.aggregateField?.label || '聚合字段',
)
const hasPlatformConstructionEntry = computed(
  () =>
    loadingPlatformWorkOrders.value ||
    platformConstructionTotal.value > 0 ||
    platformConstructionDisplayFields.value.length > 0 ||
    platformConstructionFields.value.length > 0 ||
    platformConstructionPhotoSlots.value.length > 0,
)
const activePlatformKpiItems = computed(() => {
  const order = activePlatformWorkOrder.value
  if (!order) return []
  return [
    { key: 'installer', label: '安装人员', value: order.kpiValues.installer || actor.value || '-' },
    { key: 'photo_count', label: '照片数量', value: order.kpiValues.photo_count || String(order.coveredPhotoSlots.length || order.collectionPhotos.length || 0) },
    { key: 'old_device_recovered', label: '旧设备回收', value: order.kpiValues.old_device_recovered === '1' ? '已记录' : '待记录' },
  ]
})
const fieldChecklistItems = computed<SiteChecklistItem[]>(() =>
  activeConstructionFields.value.map((field) => {
    const value = fieldValue(field).trim()
    const required = isFieldRequired(field)
    return {
      key: `field-${field.key}`,
      label: field.label || field.key,
      group: 'field',
      method: `${captureMethodLabel(field.captureMethod)}${conditionalRequiredHint(field)}`,
      intentLabel: field.requiredWhen?.fieldKey ? '条件补采' : constructionCollectionIntentLabel(field),
      intentType: constructionCollectionIntentType(field),
      required,
      done: Boolean(value),
      value: value || (required ? '待补齐' : '可选'),
    }
  }),
)
const photoChecklistItems = computed<SiteChecklistItem[]>(() =>
  activePhotoSlots.value.map((slot) => {
    const existing = hasSlotPhoto(activeGroup.value, slot.key)
    const pending = Boolean(selectedFiles.value[slot.key])
    const required = isPhotoSlotRequired(slot)
    return {
      key: `photo-${slot.key}`,
      label: slot.label || slot.key,
      group: 'photo',
      method: `拍照${conditionalRequiredHint(slot)}`,
      intentLabel: slot.requiredWhen?.fieldKey ? '条件补采' : constructionCollectionIntentLabel(slot),
      intentType: constructionCollectionIntentType(slot),
      required,
      done: existing || pending,
      value: existing ? '系统已有' : pending ? '本地待传' : required ? '待补齐' : '可选',
    }
  }),
)
const kpiChecklistItems = computed<SiteChecklistItem[]>(() => {
  if (!activePlatformWorkOrder.value) return []
  const inputItems = platformKpiInputFields.map((field) => {
    const value = fieldValue(field).trim() || activePlatformWorkOrder.value?.kpiValues[field.key] || ''
    return {
      key: `kpi-input-${field.key}`,
      label: field.label || field.key,
      group: 'kpi' as const,
      method: captureMethodLabel(field.captureMethod),
      intentLabel: 'KPI资料',
      intentType: 'info' as const,
      required: field.required,
      done: Boolean(value),
      value: value || (field.required ? '待补齐' : '可选'),
    }
  })
  const statusItems = activePlatformKpiItems.value.map((item) => {
    const value = String(item.value || '')
    const done =
      item.key === 'photo_count'
        ? Number(value || 0) > 0
        : Boolean(value && value !== '-' && !value.includes('待') && !value.includes('未记录'))
    return {
      key: `kpi-status-${item.key}`,
      label: item.label,
      group: 'kpi' as const,
      method: '系统生成',
      intentLabel: 'KPI资料',
      intentType: 'info' as const,
      required: true,
      done,
      value: value || '待补齐',
    }
  })
  return [...inputItems, ...statusItems]
})
const siteChecklistItems = computed<SiteChecklistItem[]>(() => [
  ...fieldChecklistItems.value,
  ...photoChecklistItems.value,
  ...kpiChecklistItems.value,
])
const siteChecklistSummary = computed(() => {
  const total = siteChecklistItems.value.length
  const done = siteChecklistItems.value.filter((item) => item.done).length
  const missing = siteChecklistItems.value.filter((item) => item.required && !item.done).length
  return { total, done, missing }
})
const requiredConstructionFieldLabels = computed(() =>
  activeConstructionFields.value.filter((field) => isFieldRequired(field) && !fieldValue(field).trim()).map((field) => field.label),
)
const missingRequiredKpiFieldLabels = computed(() => {
  if (!activePlatformWorkOrder.value) return []
  return platformKpiInputFields
    .filter((field) => {
      if (!field.required) return false
      const currentValue = fieldValue(field).trim()
      const savedValue = String(activePlatformWorkOrder.value?.kpiValues[field.key] || '').trim()
      return !currentValue && !savedValue
    })
    .map((field) => field.label || field.key)
})
const constructionSubmitGapGroups = computed(() => {
  const groups: { label: string; items: string[] }[] = []
  const fieldMissing = [
    ...(!hasConfiguredConstructionFields.value && !form.moduleAssetNo.trim() ? ['模块资产编号'] : []),
    ...requiredConstructionFieldLabels.value,
  ]
  if (fieldMissing.length) groups.push({ label: '缺少字段', items: fieldMissing })
  if (missingRequiredSlots.value.length) groups.push({ label: '缺少照片', items: missingRequiredSlots.value })
  if (missingRequiredKpiFieldLabels.value.length) groups.push({ label: '缺少KPI', items: missingRequiredKpiFieldLabels.value })
  return groups
})
const constructionSubmitBlocked = computed(() => constructionSubmitGapGroups.value.length > 0)

const visibleTasks = computed(() => {
  const source = isAdmin.value
    ? tasks.value.filter((task) => taskIsAssigned(task) && taskProgress(task) < 100)
    : tasks.value.filter((task) => task.constructionClaimedBy === actor.value || task.assignedConstructor === actor.value)
  return [...source].sort((left, right) => {
    const leftUploaded = Number(left.constructionUploadedCount || left.uploadedCount || 0)
    const rightUploaded = Number(right.constructionUploadedCount || right.uploadedCount || 0)
    if (leftUploaded !== rightUploaded) return rightUploaded - leftUploaded
    if (isAdmin.value) {
      const assigneeDiff = collator.compare(taskConstructorDisplayName(left), taskConstructorDisplayName(right))
      if (assigneeDiff) return assigneeDiff
    }
    return collator.compare(String(left.terminal || left.id), String(right.terminal || right.id))
  })
})

const taskSearchKeyword = computed(() => normalizeSearch(submittedTaskQuery.value))

const filteredVisibleTasks = computed(() => {
  const keyword = taskSearchKeyword.value
  if (taskPickerMode.value !== 'terminal' || !keyword) return visibleTasks.value
  return visibleTasks.value.filter((task) => matchesTaskQuery(task, keyword))
})

const visibleExceptionTaskCards = computed(() => {
  const source = fieldExceptionOrders.value.length ? fieldExceptionOrders.value : exceptionOrders.value
  const map = new Map<string, ConstructionExceptionOrder>()
  for (const order of source) {
    if (order.assignedTo !== actor.value) continue
    if (!isCollectableConstructionGroup(order.group || orderToGroup(order))) continue
    map.set(order.id || `${order.taskId}-${order.groupId}`, order)
  }
  return [...map.values()]
})

const visibleUnmatchedTaskCards = computed(() =>
  unmatchedRecords.value.filter(
    (record) => record.assignedTo === actor.value && isCollectableConstructionGroup(unmatchedRecordToConstructionGroup(record)),
  ),
)

const taskPickerTitle = computed(() => {
  if (isAdmin.value) return '已指派未完成终端'
  if (taskPickerMode.value === 'exception') return '异常任务'
  if (taskPickerMode.value === 'unmatched') return '未匹配任务'
  return '已指派终端'
})

const taskPickerSubtitle = computed(() => {
  if (isAdmin.value) return '当前团队已指派施工员且完成度未达到 100% 的施工终端，只读查看进度'
  if (taskPickerMode.value === 'exception') return '被指派的异常组可直接进入施工处理'
  if (taskPickerMode.value === 'unmatched') return '现场确认未匹配地址、换表或项目外施工'
  return '只显示当前账号已被指派的施工终端'
})

const taskPickerCount = computed(() => {
  if (taskPickerMode.value === 'terminal') return filteredVisibleTasks.value.length
  if (taskPickerMode.value === 'exception') return visibleExceptionTaskCards.value.length
  if (taskPickerMode.value === 'unmatched') return visibleUnmatchedTaskCards.value.length
  return visibleTasks.value.length
})

const taskEmptyDescription = computed(() => {
  if (taskPickerMode.value === 'terminal' && submittedTaskQuery.value.trim()) return '未找到匹配表号的施工工单'
  return isAdmin.value ? '暂无已指派未完成终端' : '暂无指派施工终端'
})

const selectedTask = computed(() => visibleTasks.value.find((task) => task.id === selectedTaskId.value) || null)
const inTaskPicker = computed(() => !activePlatformWorkOrder.value && (isAdmin.value || !selectedTask.value || taskPickerOpen.value))
const canSubmitSelectedTask = computed(() => {
  const task = selectedTask.value
  if (!task || isAdmin.value) return false
  return task.constructionClaimedBy === actor.value || task.assignedConstructor === actor.value
})
const taskDrafts = computed(() =>
  drafts.value.filter((draft) => String(draft.taskId || '') === selectedTaskId.value && (!draft.actor || draft.actor === actor.value)),
)
const exceptionGroupIdSet = computed(() => new Set(exceptionOrders.value.map((order) => String(order.groupId || '')).filter(Boolean)))
function draftGroupId(draft: CacheDraft) {
  return String(draft.groupId || draft.group_id || '')
}
function isExceptionDraft(draft: CacheDraft) {
  const groupId = draftGroupId(draft)
  return Boolean(draft.work_order_id) || Boolean(groupId && exceptionGroupIdSet.value.has(groupId))
}
const cachedTaskDrafts = computed(() => taskDrafts.value.filter((draft) => !isExceptionDraft(draft) && !isPlaceholderConstructionDraft(draft)))
const readyCachedDrafts = computed(() => cachedTaskDrafts.value.filter((draft) => draftReady(draft)))
const draftByGroupId = computed(() => {
  const map = new Map<string, CacheDraft>()
  for (const draft of taskDrafts.value) {
    const groupId = draftGroupId(draft)
    if (groupId) map.set(groupId, draft)
  }
  return map
})
const cachedDraftByGroupId = computed(() => {
  const map = new Map<string, CacheDraft>()
  for (const draft of cachedTaskDrafts.value) {
    const groupId = draftGroupId(draft)
    if (groupId) map.set(groupId, draft)
  }
  return map
})

const groupFilterCounts = computed(() => {
  const keyword = normalizeSearch(groupQuery.value)
  const cachedGroupIds = new Set(cachedTaskDrafts.value.map((draft) => draftGroupId(draft)).filter(Boolean))
  const exceptionGroupIds = exceptionGroupIdSet.value
  const byQuery = groups.value.filter(
    (group) =>
      isCollectableConstructionGroup(group) &&
      matchesGroupQuery(group, keyword) &&
      !group.exceptionOrderId &&
      !exceptionGroupIds.has(String(group.id)),
  )
  const exceptionGroups = exceptionOrders.value
    .map((order) => order.group || orderToGroup(order))
    .filter((group) => isCollectableConstructionGroup(group) && matchesGroupQuery(group, keyword))
  const countedCachedGroupIds = new Set<string>(byQuery.filter((group) => cachedGroupIds.has(String(group.id))).map((group) => String(group.id)))
  const standaloneCached = cachedTaskDrafts.value.filter((draft) => {
    const groupId = draftGroupId(draft)
    return groupId && !countedCachedGroupIds.has(groupId)
  }).length
  return {
    all: byQuery.length,
    unbuilt: byQuery.filter((group) => !cachedGroupIds.has(String(group.id)) && !group.exceptionOrderId).length,
    cached: byQuery.filter((group) => cachedGroupIds.has(String(group.id))).length + standaloneCached,
    exceptions: exceptionGroups.length,
  }
})

const groupSummary = computed(() => ({
  unbuilt: groupFilterCounts.value.unbuilt,
  cached: groupFilterCounts.value.cached,
  exceptions: groupFilterCounts.value.exceptions,
  total: groupFilterCounts.value.all,
}))

const groupFilterTabs = computed(() => [
  { label: '全部', value: 'all' as const, count: groupFilterCounts.value.all },
  { label: '未施工', value: 'unbuilt' as const, count: groupFilterCounts.value.unbuilt },
  { label: '已缓存', value: 'cached' as const, count: groupFilterCounts.value.cached },
  { label: '异常工单', value: 'exception' as const, count: groupFilterCounts.value.exceptions },
])

const workItems = computed<WorkItem[]>(() => {
  const items: WorkItem[] = []
  const seen = new Set<string>()
  const groupMap = new Map(groups.value.map((group) => [group.id, group]))
  const exceptionGroupIds = new Set(exceptionOrders.value.map((order) => String(order.groupId || '')).filter(Boolean))

  for (const group of groups.value) {
    if (group.exceptionOrderId || exceptionGroupIds.has(String(group.id))) continue
    if (!isCollectableConstructionGroup(group)) continue
    const draft = cachedDraftByGroupId.value.get(group.id)
    items.push({ key: `group-${group.id}`, kind: draft ? 'cached' : 'group', group, draft })
    seen.add(group.id)
  }

  for (const order of exceptionOrders.value) {
    const group = order.group || groupMap.get(order.groupId) || orderToGroup(order)
    if (!isCollectableConstructionGroup(group)) continue
    const draft = draftByGroupId.value.get(order.groupId)
    items.push({
      key: `exception-${order.id || order.groupId}`,
      kind: 'exception',
      group: {
        ...group,
        exceptionOrderId: order.id,
        exceptionNote: order.note,
        status: 'exception',
      },
      order,
      draft,
    })
    if (group.id) seen.add(String(group.id))
  }

  for (const draft of cachedTaskDrafts.value) {
    const groupId = String(draft.groupId || draft.group_id || '')
    if (!groupId || seen.has(groupId)) continue
    items.push({
      key: `draft-${groupId}`,
      kind: 'cached',
      group: draftToGroup(draft),
      draft,
    })
    seen.add(groupId)
  }

  return items
})

const visibleWorkItems = computed(() => {
  const keyword = normalizeSearch(groupQuery.value)
  return workItems.value
    .filter((item) => {
      if (groupFilter.value === 'all' && (item.order || item.key.startsWith('draft-'))) return false
      if (groupFilter.value === 'unbuilt' && (item.kind !== 'group' || item.order)) return false
      if (groupFilter.value === 'cached' && (!item.draft || item.order)) return false
      if (groupFilter.value === 'exception' && !item.order) return false
      if (!keyword) return true
      return matchesGroupQuery(item.group, keyword)
    })
    .sort((left, right) => {
      const rank: Record<WorkItem['kind'], number> = { group: 0, cached: 1, exception: 2, platform: 3 }
      if (rank[left.kind] !== rank[right.kind]) return rank[left.kind] - rank[right.kind]
      return collator.compare(left.group.address || left.group.meterNo || left.key, right.group.address || right.group.meterNo || right.key)
    })
})

const unbuiltDialogTitle = computed(() => {
  const task = unbuiltDialogTask.value
  return task ? `终端 ${task.terminal || task.id} 未施工清单` : '未施工清单'
})

const filteredUnbuiltDialogGroups = computed(() => {
  const keyword = normalizeSearch(unbuiltDialogQuery.value)
  const collectableGroups = unbuiltDialogGroups.value.filter(isCollectableConstructionGroup)
  if (!keyword) return collectableGroups
  return collectableGroups.filter((group) => matchesGroupQuery(group, keyword))
})

const missingRequiredSlots = computed(() => {
  if (!activeGroup.value) return []
  if (
    activeOrder.value &&
    !exceptionNeedsPhotoSlots({
      work_order_id: activeOrder.value.id,
      category: activeOrder.value.category,
      note: activeOrder.value.note,
    })
  ) {
    return []
  }
  return activePhotoSlots.value.filter((slot) => isPhotoSlotRequired(slot) && !hasSlotPhoto(activeGroup.value, slot.key)).map((slot) => slot.label)
})

const activeExistingPhotos = computed(() => activeGroup.value?.photos?.filter((photo) => photoUrl(photo)) || [])

const canUploadCurrent = computed(() => {
  if (!activeGroup.value) return false
  if (constructionGroupOpenBlockReason(activeGroup.value)) return false
  if (!hasConfiguredConstructionFields.value && !form.moduleAssetNo.trim()) return false
  if (requiredConstructionFieldLabels.value.length) return false
  if (missingRequiredSlots.value.length) return false
  return Boolean(Object.values(selectedFiles.value).some(Boolean) || activeOrder.value)
})
const canShowCurrentUpload = computed(
  () => !isAdmin.value && groupFilter.value === 'cached' && Boolean(activeGroup.value && cachedDraftByGroupId.value.get(activeGroup.value.id)),
)
const activeCachedDraft = computed(() => (activeGroup.value ? cachedDraftByGroupId.value.get(String(activeGroup.value.id)) || null : null))

const scannerTitle = computed(() => {
  if (scannerTarget.value === 'dynamic') return `扫描${activeScannerField()?.label || '字段'}`
  if (scannerTarget.value === 'collector') return '扫描采集器'
  if (scannerTarget.value === 'module') return '扫描模块号'
  return '扫描表号'
})

function activeScannerField() {
  return activeConstructionFields.value.find((field) => field.key === scannerFieldKey.value) || null
}

function fieldValue(field: ProjectFieldDefinition) {
  return fieldValueByKey(field.key)
}

function fieldValueByKey(fieldKey: string) {
  if (fieldKey === 'collector' || fieldKey === 'collector_no') return form.collector
  if (fieldKey === 'module_asset_no' || fieldKey === 'module' || fieldKey === 'asset_no') return form.moduleAssetNo
  return form.dynamicFields[fieldKey] || ''
}

function constructionFieldSectionsBase(): ConstructionFieldSection[] {
  return [
    { id: 'task-core', title: '任务核心字段', helper: '确认任务对象、地址、厂家等核心信息。', fields: [] },
    { id: 'main-device-replacement', title: '主设备更换', helper: '记录本次必须更换的主设备安装结果。', fields: [] },
    { id: 'device-replacement', title: '设备/附属设备采集', helper: '记录旧设备拆回、附属新设备和其他设备编码。', fields: [] },
    { id: 'accessory-confirmation', title: '附属设备确认', helper: '先确认通讯模块、SIM 卡、采集器等附属设备是否同步更换。', fields: [] },
    { id: 'conditional-accessory-fields', title: '条件补采', helper: '仅在对应附属设备选择更换后出现，用于补齐旧件、新件或照片前置字段。', fields: [] },
    { id: 'supporting-fields', title: '补充采集字段', helper: '项目自定义的辅助录入、定位或审阅前置资料。', fields: [] },
  ]
}

function isConditionalAccessoryField(field: ProjectFieldDefinition) {
  return Boolean(field.requiredWhen?.fieldKey)
}

function constructionFieldSectionId(field: ProjectFieldDefinition): ConstructionFieldSection['id'] {
  if (field.relationRole === 'task_detail' || field.relationRole === 'task_object') return 'task-core'
  if (isConditionalAccessoryField(field)) return 'conditional-accessory-fields'
  if (field.relationRole === 'replacement_device') return 'main-device-replacement'
  if (field.relationRole === 'accessory_replace_confirm') return 'accessory-confirmation'
  if (field.relationRole === 'old_device' || field.relationRole === 'accessory_new_device') return 'device-replacement'
  return 'supporting-fields'
}

function fieldRelationRoleLabel(role: ProjectFieldDefinition['relationRole'] | ConstructionPhotoSlot['relationRole']) {
  const labels: Record<NonNullable<ProjectFieldDefinition['relationRole']>, string> = {
    aggregate: '聚合口径',
    task_object: '任务对象',
    task_detail: '任务详情',
    replacement_device: '主设备 · 更换后',
    old_device: '旧设备 · 拆回',
    accessory_replace_confirm: '附属设备 · 是否更换',
    accessory_new_device: '附属设备 · 新设备',
    evidence_photo: '照片证据',
    supporting_field: '辅助字段',
  }
  return role ? labels[role] || '辅助字段' : '辅助字段'
}

function constructionCollectionIntentLabel(
  item: Pick<ProjectFieldDefinition, 'relationRole' | 'requiredWhen'> | Pick<ConstructionPhotoSlot, 'relationRole' | 'requiredWhen'>,
) {
  if (item.requiredWhen?.fieldKey) return '条件补采'
  if (item.relationRole === 'replacement_device') return '主设备本体'
  if (item.relationRole === 'accessory_replace_confirm') return '附属设备确认'
  if (item.relationRole === 'old_device' || item.relationRole === 'accessory_new_device') return '任务对象下的附属设备'
  if (item.relationRole === 'evidence_photo') return '照片证据'
  if (item.relationRole === 'task_object' || item.relationRole === 'task_detail') return '任务核心'
  return '补充资料'
}

function constructionCollectionIntentType(
  item: Pick<ProjectFieldDefinition, 'relationRole' | 'requiredWhen'> | Pick<ConstructionPhotoSlot, 'relationRole' | 'requiredWhen'>,
): SiteChecklistItem['intentType'] {
  if (item.requiredWhen?.fieldKey) return 'warning'
  if (item.relationRole === 'replacement_device') return 'danger'
  if (item.relationRole === 'accessory_replace_confirm') return 'warning'
  if (item.relationRole === 'old_device' || item.relationRole === 'accessory_new_device') return 'success'
  if (item.relationRole === 'evidence_photo') return 'info'
  return ''
}

function constructionConditionLabel(field: Pick<ProjectFieldDefinition, 'requiredWhen'> | Pick<ConstructionPhotoSlot, 'requiredWhen'>) {
  const requiredWhen = field.requiredWhen
  const fieldKey = requiredWhen?.fieldKey
  if (!fieldKey) return ''
  const equals = Array.isArray(requiredWhen.equals) ? requiredWhen.equals.join('/') : requiredWhen.equals
  return `${fieldKey} = ${equals || '指定值'} 时显示并必采`
}

function captureMethodLabel(method: ProjectFieldDefinition['captureMethod']) {
  const labels: Record<ProjectFieldDefinition['captureMethod'], string> = {
    manual: '手工录入',
    scan: '扫码',
    photo: '拍照',
    select: '下拉选择',
    datetime: '时间',
    location: '定位',
    system: '系统生成',
    none: '无需采集',
  }
  return labels[method] || '手工录入'
}

function platformFieldRequirement(field: ProjectFieldDefinition) {
  return `${field.label} · ${captureMethodLabel(field.captureMethod)}${field.required ? ' · 必填' : ''}`
}

function platformWorkOrderFieldValue(order: PlatformConstructionWorkOrder, field: ProjectFieldDefinition) {
  return order.collectionFieldValues[field.key] || order.fieldValues[field.key] || '-'
}

function platformWorkOrderConditionValues(order: PlatformConstructionWorkOrder) {
  const values: Record<string, string> = {
    ...order.fieldValues,
    ...order.collectionFieldValues,
    ...order.kpiValues,
  }
  const primaryKey = platformConstructionSchema.value?.primaryField?.key
  const aggregateKey = platformConstructionSchema.value?.aggregateField?.key
  if (primaryKey && !values[primaryKey]) values[primaryKey] = order.primaryValue || ''
  if (aggregateKey && !values[aggregateKey]) values[aggregateKey] = order.aggregateValue || ''
  return values
}

function platformConstructionFieldsForOrder(order: PlatformConstructionWorkOrder) {
  return platformConstructionFields.value.filter((field) => isFieldConditionActiveForValues(field, platformWorkOrderConditionValues(order)))
}

function platformConstructionPhotoSlotsForOrder(order: PlatformConstructionWorkOrder) {
  return platformConstructionPhotoSlots.value.filter((slot) => isPhotoSlotConditionActiveForValues(slot, platformWorkOrderConditionValues(order)))
}

function platformWorkOrderPhotoSlotStatus(order: PlatformConstructionWorkOrder, slot: ConstructionPhotoSlot) {
  const covered = order.coveredPhotoSlots.includes(slot.key) || order.collectionPhotos.some((photo) => photo.slot === slot.key)
  if (covered) return '已覆盖'
  return isPhotoSlotRequiredForValues(slot, platformWorkOrderConditionValues(order)) ? '待拍照' : '可选'
}

function platformDisplayFieldValue(order: PlatformConstructionWorkOrder, field: ProjectFieldDefinition) {
  if (field.key === platformConstructionSchema.value?.primaryField?.key) return order.primaryValue || '-'
  if (field.key === platformConstructionSchema.value?.aggregateField?.key) return order.aggregateValue || '-'
  return order.fieldValues[field.key] || order.collectionFieldValues[field.key] || '-'
}

function checklistGroupLabel(group: SiteChecklistItem['group']) {
  const labels: Record<SiteChecklistItem['group'], string> = {
    field: '字段',
    photo: '照片',
    kpi: 'KPI',
  }
  return labels[group]
}

function checklistStatusLabel(item: SiteChecklistItem) {
  return item.done ? '已完成' : '待补齐'
}

function checklistStatusType(item: SiteChecklistItem) {
  return item.done ? 'success' : item.required ? 'danger' : 'info'
}

function platformWorkOrderKpiLine(order: PlatformConstructionWorkOrder) {
  const installer = order.kpiValues.installer || order.collectedBy || '未记录安装人员'
  const completedAt = order.kpiValues.completed_at || '未记录完成时间'
  const online = order.kpiValues.online_duration_minutes ? `${order.kpiValues.online_duration_minutes} 分钟在线` : '未记录在线时长'
  const oldDevice = order.kpiValues.old_device_recovered === '1' ? '旧设备已记录' : '旧设备待记录'
  return `${installer} / ${completedAt} / ${online} / ${oldDevice}`
}

function platformWorkOrderNeedsRework(order: PlatformConstructionWorkOrder | null | undefined) {
  return order?.reviewStatus === 'returned'
}

function platformWasReworkResubmitted(order: PlatformConstructionWorkOrder | null | undefined) {
  return Boolean(order?.reviewHistory?.some((event) => event.action === 'rework_submitted'))
}

const platformReworkEvidenceGapGroups = computed(() => activePlatformWorkOrder.value?.reworkEvidenceGapGroups || [])

function platformWorkOrderReworkReason(order: PlatformConstructionWorkOrder | null | undefined) {
  return order?.reviewReason || order?.reviewNote || order?.reviewHistory?.find((event) => event.action === 'returned')?.reason || ''
}

function platformReworkGapSummary(order: PlatformConstructionWorkOrder | null | undefined) {
  if (!order || !platformWorkOrderNeedsRework(order)) return ''
  const firstGroup = (order.reworkEvidenceGapGroups || []).find((group) => group.items.length)
  if (!firstGroup) return platformWorkOrderReworkReason(order) || '请按审阅意见重新采集'
  const visibleItems = firstGroup.items.slice(0, 4)
  const suffix = firstGroup.items.length > visibleItems.length ? '等' : ''
  return `${firstGroup.label}：${visibleItems.join('、')}${suffix}`
}

function platformWorkOrderToGroup(order: PlatformConstructionWorkOrder): MaterialGroup {
  return {
    id: order.id,
    taskId: order.sourceTaskId || 'platform',
    address: order.aggregateValue,
    meterNo: order.primaryValue,
    meterMatchKey: order.primaryValue,
    terminal: order.primaryValue,
    status: 'pending',
    photoCount: order.coveredPhotoSlots.length,
    constructionStatus: order.collectionStatus || 'created',
    fieldValues: {
      ...order.fieldValues,
      ...order.collectionFieldValues,
    },
    photos: order.collectionPhotos.map((photo) => ({
      id: photo.id,
      url: '',
      name: photo.filename,
      status: 'unclassified',
      category: photo.slot,
      constructionSlot: photo.slot,
      constructionSlotLabel: photo.slot,
      creator: photo.uploadedBy,
    })),
  }
}

function loadPlatformWorkOrderIntoForm(order: PlatformConstructionWorkOrder) {
  clearPreviews()
  selectedFiles.value = {}
  form.collector = ''
  form.moduleAssetNo = ''
  form.dynamicFields = {
    ...order.fieldValues,
    ...order.collectionFieldValues,
    ...order.kpiValues,
  }
  form.note = ''
}

async function openPlatformWorkOrder(order: PlatformConstructionWorkOrder) {
  await flushCurrentDraftPersist()
  activePlatformWorkOrder.value = order
  activeOrder.value = null
  activeGroup.value = platformWorkOrderToGroup(order)
  selectedTaskId.value = ''
  selectedItemKey.value = `platform-${order.id}`
  taskPickerOpen.value = false
  collectOpen.value = shouldUseCollectorDrawer()
  loadPlatformWorkOrderIntoForm(order)
}

function replacePlatformWorkOrder(updated: PlatformConstructionWorkOrder) {
  platformConstructionWorkOrders.value = platformConstructionWorkOrders.value.map((order) => (order.id === updated.id ? updated : order))
  activePlatformWorkOrder.value = updated
  activeGroup.value = platformWorkOrderToGroup(updated)
}

async function savePlatformCollectionDraft(status: 'cached' | 'submitted' = 'cached') {
  if (!activePlatformWorkOrder.value) return
  cacheBusy.value = true
  try {
    let latestWorkOrder = activePlatformWorkOrder.value
    const pendingFiles = Object.entries(selectedFiles.value).filter(
      (entry): entry is [string, File] => Boolean(entry[1]) && activePhotoSlotKeys.value.has(entry[0]),
    )
    for (const [slot, file] of pendingFiles) {
      latestWorkOrder = await uploadProjectConstructionWorkOrderPhoto(activeProjectId.value, latestWorkOrder.id, {
        actor: actor.value,
        slot,
        clientPhotoId: `${slot}-${file.name}-${file.size}-${file.lastModified}`,
        file,
      })
    }
    const coveredPhotoSlots = Array.from(
      new Set([
        ...latestWorkOrder.coveredPhotoSlots,
        ...pendingFiles.map(([slot]) => slot),
      ]),
    )
    const updated = await saveProjectConstructionWorkOrderCollection(activeProjectId.value, latestWorkOrder.id, {
      actor: actor.value,
      clientBatchId: `platform-${latestWorkOrder.id}`,
      status,
      fieldValues: collectFieldValues(),
      coveredPhotoSlots,
    })
    clearPreviews()
    selectedFiles.value = {}
    replacePlatformWorkOrder(updated)
    const submittedMessage = platformWasReworkResubmitted(updated) ? '返工已重新提交审阅' : '平台采集元数据已提交'
    ElMessage.success(status === 'submitted' ? submittedMessage : '平台采集草稿已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '平台采集草稿保存失败')
  } finally {
    cacheBusy.value = false
  }
}

function setFieldValue(field: ProjectFieldDefinition, value: string) {
  const clean = String(value || '').trim()
  if (field.key === 'collector' || field.key === 'collector_no') form.collector = clean
  else if (field.key === 'module_asset_no' || field.key === 'module' || field.key === 'asset_no') form.moduleAssetNo = clean
  else form.dynamicFields[field.key] = clean
  clearInactiveConditionalValues(field.key)
}

function fieldPlaceholder(field: ProjectFieldDefinition) {
  if (shouldUseFieldSelect(field)) return '请选择'
  if (field.captureMethod === 'scan') return '扫码或手填'
  if (field.captureMethod === 'datetime') return '填写时间'
  if (field.captureMethod === 'location') return '填写或定位'
  return isFieldRequired(field) ? '必填' : '可选'
}

function fieldInputType(field: ProjectFieldDefinition) {
  if (field.dataType === 'number' || field.dataType === 'duration') return 'number'
  return 'text'
}

function shouldShowScanButton(field: ProjectFieldDefinition) {
  return field.captureMethod === 'scan'
}

function shouldUseFieldSelect(field: ProjectFieldDefinition) {
  return field.captureMethod === 'select' || field.dataType === 'enum' || field.dataType === 'boolean'
}

function fieldSelectOptions(field: ProjectFieldDefinition) {
  if (field.options?.length) return field.options
  if (field.dataType === 'boolean') return ['是', '否']
  return ['更换', '不更换', '待确认']
}

function fieldConditionValue(
  field: Pick<ProjectFieldDefinition, 'requiredWhen'> | Pick<ConstructionPhotoSlot, 'requiredWhen'>,
  values?: Record<string, string>,
) {
  const fieldKey = field.requiredWhen?.fieldKey
  if (!fieldKey) return ''
  if (values) return String(values[fieldKey] || '').trim()
  return fieldValueByKey(fieldKey).trim()
}

function requiredWhenMatches(
  field: Pick<ProjectFieldDefinition, 'requiredWhen'> | Pick<ConstructionPhotoSlot, 'requiredWhen'>,
  values?: Record<string, string>,
) {
  const expected = field.requiredWhen?.equals
  const current = fieldConditionValue(field, values)
  if (!expected || !current) return false
  return Array.isArray(expected) ? expected.includes(current) : current === expected
}

function isFieldConditionActive(field: ProjectFieldDefinition) {
  return isFieldConditionActiveForValues(field)
}

function isFieldConditionActiveForValues(field: ProjectFieldDefinition, values?: Record<string, string>) {
  if (!field.requiredWhen?.fieldKey) return true
  return requiredWhenMatches(field, values)
}

function isPhotoSlotConditionActive(slot: ConstructionPhotoSlot) {
  return isPhotoSlotConditionActiveForValues(slot)
}

function isPhotoSlotConditionActiveForValues(slot: ConstructionPhotoSlot, values?: Record<string, string>) {
  if (!slot.requiredWhen?.fieldKey) return true
  return requiredWhenMatches(slot, values)
}

function isFieldRequired(field: ProjectFieldDefinition) {
  return isFieldRequiredForValues(field)
}

function isFieldRequiredForValues(field: ProjectFieldDefinition, values?: Record<string, string>) {
  return Boolean(isFieldConditionActiveForValues(field, values) && (field.required || requiredWhenMatches(field, values)))
}

function isPhotoSlotRequired(slot: ConstructionPhotoSlot) {
  return isPhotoSlotRequiredForValues(slot)
}

function isPhotoSlotRequiredForValues(slot: ConstructionPhotoSlot, values?: Record<string, string>) {
  return Boolean(isPhotoSlotConditionActiveForValues(slot, values) && (slot.required || requiredWhenMatches(slot, values)))
}

function conditionalRequiredHint(field: Pick<ProjectFieldDefinition, 'requiredWhen'> | Pick<ConstructionPhotoSlot, 'requiredWhen'>) {
  if (!field.requiredWhen?.fieldKey) return ''
  const equals = Array.isArray(field.requiredWhen.equals) ? field.requiredWhen.equals.join('/') : field.requiredWhen.equals
  return equals ? ` · ${equals}时必填` : ''
}

function startDynamicScanner(field: ProjectFieldDefinition) {
  scannerFieldKey.value = field.key
  void startScanner('dynamic')
}

function collectFieldValues() {
  const values: Record<string, string> = {}
  for (const field of activeConstructionFields.value) values[field.key] = fieldValue(field).trim()
  if (activePlatformWorkOrder.value) {
    for (const field of platformKpiInputFields) values[field.key] = fieldValue(field).trim()
  }
  return values
}

function clearInactiveConditionalValues(changedFieldKey = '') {
  for (const field of constructionFields.value) {
    if (changedFieldKey && field.requiredWhen?.fieldKey !== changedFieldKey) continue
    if (isFieldConditionActive(field)) continue
    if (field.key === 'collector' || field.key === 'collector_no') form.collector = ''
    else if (field.key === 'module_asset_no' || field.key === 'module' || field.key === 'asset_no') form.moduleAssetNo = ''
    else delete form.dynamicFields[field.key]
  }
  for (const slot of photoSlots.value) {
    if (changedFieldKey && slot.requiredWhen?.fieldKey !== changedFieldKey) continue
    if (isPhotoSlotConditionActive(slot)) continue
    clearSelectedSlotPhoto(slot.key)
  }
}

function normalizeSearch(value: string) {
  return String(value || '')
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[^\u4e00-\u9fa5a-z0-9]+/g, '')
}

function normalizeCode(value: string) {
  return String(value || '')
    .normalize('NFKC')
    .replace(/[^0-9a-zA-Z]/g, '')
    .toUpperCase()
}

function totalMeterMatchKey(value: string) {
  const normalized = normalizeCode(value)
  if (normalized.length === 12) return normalized.slice(2)
  return normalized
}

function scannedBarcodeMatchKey(value: string) {
  const normalized = normalizeCode(value)
  if (normalized.length >= 22) return normalized.slice(11, -1)
  if (normalized.length >= 13) return normalized.slice(0, -1)
  return totalMeterMatchKey(normalized)
}

function meterCodeCandidates(value: string) {
  const normalized = normalizeCode(value)
  const candidates = new Set([normalized, totalMeterMatchKey(normalized), scannedBarcodeMatchKey(normalized)])
  if (normalized.length > 2) candidates.add(normalized.slice(2))
  if (normalized.length > 12) candidates.add(normalized.slice(0, -1))
  if (normalized.length > 12) candidates.add(normalized.slice(11, -1))
  candidates.delete('')
  return candidates
}

function groupMeterCandidates(group: MaterialGroup) {
  const candidates = new Set<string>()
  ;[group.meterNo, group.meterMatchKey, group.id].forEach((value) => {
    meterCodeCandidates(String(value || '')).forEach((candidate) => candidates.add(candidate))
  })
  return candidates
}

function fuzzyIncludes(haystack: string, needle: string) {
  if (!needle) return true
  if (haystack.includes(needle)) return true
  let index = 0
  for (const char of haystack) {
    if (char === needle[index]) index += 1
    if (index === needle.length) return true
  }
  return false
}

function queryTokens(value: string) {
  const source = String(value || '').normalize('NFKC').toLowerCase()
  const tokens = source
    .split(/[^\u4e00-\u9fa5a-z0-9]+/g)
    .map(normalizeSearch)
    .filter(Boolean)
  const compact = normalizeSearch(source)
  return tokens.length ? tokens : compact ? [compact] : []
}

function groupSearchBlob(group: MaterialGroup) {
  return normalizeSearch(
    `${group.meterNo || ''} ${group.meterMatchKey || ''} ${group.address || ''} ${group.terminal || ''} ${
      group.constructionCollector || ''
    } ${group.constructionModuleAssetNo || ''}`,
  )
}

function matchesGroupQuery(group: MaterialGroup, query: string) {
  const tokens = queryTokens(query)
  if (!tokens.length) return true
  const blob = groupSearchBlob(group)
  if (tokens.every((token) => fuzzyIncludes(blob, token))) return true
  const queryCandidates = meterCodeCandidates(query)
  if (!queryCandidates.size) return false
  const groupCandidates = groupMeterCandidates(group)
  return [...queryCandidates].some((candidate) => groupCandidates.has(candidate))
}

function taskSearchBlob(task: ReviewTask) {
  return normalizeSearch(
    `${task.terminal || ''} ${task.id || ''} ${task.address || ''} ${task.addressSearchText || ''} ${
      task.meterSearchText || ''
    }`,
  )
}

function taskMeterCandidates(task: ReviewTask) {
  const candidates = new Set<string>()
  ;[task.meterSearchText, task.terminal, task.id].forEach((value) => {
    String(value || '')
      .split(/\s+/)
      .forEach((part) => meterCodeCandidates(part).forEach((candidate) => candidates.add(candidate)))
  })
  return candidates
}

function taskMeterParts(task: ReviewTask) {
  return String(task.meterSearchText || '')
    .split(/\s+/)
    .map((part) => part.trim())
    .filter(Boolean)
}

function taskMatchedMeterLabel(task: ReviewTask) {
  const query = submittedTaskQuery.value.trim()
  if (!query) return ''
  const queryCandidates = meterCodeCandidates(query)
  const parts = taskMeterParts(task)
  for (const part of parts) {
    const partCandidates = meterCodeCandidates(part)
    if ([...queryCandidates].some((candidate) => partCandidates.has(candidate))) return part
  }
  const normalized = normalizeSearch(query)
  return parts.find((part) => normalizeSearch(part).includes(normalized)) || query
}

function matchesTaskQuery(task: ReviewTask, query: string) {
  const tokens = queryTokens(query)
  if (!tokens.length) return true
  const blob = taskSearchBlob(task)
  if (tokens.every((token) => fuzzyIncludes(blob, token))) return true
  const queryCandidates = meterCodeCandidates(query)
  if (!queryCandidates.size) return false
  const taskCandidates = taskMeterCandidates(task)
  return [...queryCandidates].some((candidate) => taskCandidates.has(candidate))
}

function clearTaskSearch() {
  taskQuery.value = ''
  submittedTaskQuery.value = ''
}

function submitTaskSearch() {
  submittedTaskQuery.value = taskQuery.value.trim()
  if (!submittedTaskQuery.value) return
  const [firstMatch] = filteredVisibleTasks.value
  if (!firstMatch) {
    selectedTaskId.value = ''
    ElMessage.warning('未找到匹配表号的施工工单')
    return
  }
  selectedTaskId.value = firstMatch.id
  ElMessage.success(`已找到终端 ${firstMatch.terminal || firstMatch.id}`)
}

function findWorkItemByMeterCode(value: string) {
  const scanned = meterCodeCandidates(value)
  if (!scanned.size) return null
  const exact = workItems.value.find((item) => {
    const groupKeys = groupMeterCandidates(item.group)
    return [...scanned].some((candidate) => groupKeys.has(candidate))
  })
  if (exact) return exact
  const normalized = normalizeSearch(value)
  const loose = workItems.value.filter((item) => groupSearchBlob(item.group).includes(normalized))
  return loose.length === 1 ? loose[0] : null
}

function addressNumber(text: string, unitPattern: string) {
  const match = String(text || '').match(new RegExp(`([a-z]?\\d+(?:-\\d+)?)(?=${unitPattern})`, 'i'))
  return match ? match[1] : ''
}

function addressSortKey(group: MaterialGroup) {
  const address = normalizeSearch(group.address || '')
  return [
    address ? 0 : 1,
    address.replace(/\d+/g, ''),
    addressNumber(address, '弄|巷|村'),
    addressNumber(address, '号'),
    addressNumber(address, '幢|栋|楼'),
    addressNumber(address, '单元'),
    addressNumber(address, '室|房'),
    addressNumber(address, '车位|车库|库'),
    address,
    normalizeSearch(group.meterNo || group.meterMatchKey || group.id || ''),
  ]
}

function compareGroupsByAddress(left: MaterialGroup, right: MaterialGroup) {
  const leftKey = addressSortKey(left)
  const rightKey = addressSortKey(right)
  for (let index = 0; index < leftKey.length; index += 1) {
    const diff = collator.compare(String(leftKey[index]), String(rightKey[index]))
    if (diff) return diff
  }
  return 0
}

function sortGroupsByAddress(items: MaterialGroup[]) {
  return [...items].sort(compareGroupsByAddress)
}

function online() {
  return typeof navigator === 'undefined' ? true : navigator.onLine
}

function taskConstructorAccount(task: ReviewTask) {
  return task.assignedConstructor || task.constructionClaimedBy || ''
}

function userDisplayName(username = '') {
  const account = String(username || '').trim()
  if (!account) return ''
  const user = userByUsername.value.get(account)
  return user?.name?.trim() || account
}

function taskConstructorDisplayName(task: ReviewTask) {
  const account = taskConstructorAccount(task)
  return task.assignedConstructorName || task.constructionClaimedByName || userDisplayName(account) || account || '未指派'
}

function taskConstructorAccountHint(task: ReviewTask) {
  const account = taskConstructorAccount(task)
  const name = taskConstructorDisplayName(task)
  return account && account !== name ? `账号 ${account}` : ''
}

function taskRepresentativeAddress(task: ReviewTask) {
  return task.address || task.addressSearchText || '未填写代表地址'
}

function taskIsAssigned(task: ReviewTask) {
  return Boolean(taskConstructorAccount(task))
}

function taskStatus(task: ReviewTask) {
  if (isAdmin.value && taskIsAssigned(task)) return '已指派'
  if (task.constructionClaimedBy === actor.value || task.assignedConstructor === actor.value) return '已指派给我'
  if (task.constructionClaimedBy || task.assignedConstructor) return `已指派 ${task.constructionClaimedBy || task.assignedConstructor}`
  if (task.constructionEnabled) return '待指派'
  return '未开放'
}

function taskProgress(task: ReviewTask) {
  const total = Number(task.renovationCount || task.totalGroups || 0)
  const uploaded = Number(task.constructionUploadedCount || task.uploadedCount || 0)
  return total ? Math.min(100, Math.round((uploaded / total) * 100)) : 0
}

function taskUnbuiltCount(task: ReviewTask) {
  const explicit = Number(task.constructionUnbuiltCount)
  if (Number.isFinite(explicit) && task.constructionUnbuiltCount !== undefined) return explicit
  const total = Number(task.renovationCount || task.totalGroups || 0)
  const uploaded = Number(task.constructionUploadedCount || task.uploadedCount || 0)
  return Math.max(total - uploaded, 0)
}

function taskExceptionCount(task: ReviewTask) {
  return Number(task.constructionExceptionCount || 0)
}

function logoutConstruction() {
  auth.logout()
  void router.push({ name: 'login' })
}

function draftKey(taskId: string | number, groupId: string | number) {
  return `${teamId.value}:${actor.value}:${taskId}:${groupId}`
}

function snapshotKey(taskId: string | number) {
  return `${teamId.value}:${actor.value}:${taskId}`
}

function draftToGroup(draft: CacheDraft): MaterialGroup {
  return {
    id: String(draft.groupId || draft.group_id || draft.client_batch_id),
    taskId: draft.taskId || '',
    address: draft.address || '',
    meterNo: draft.meter_no || '',
    terminal: draft.terminal || '',
    status: 'pending',
    photoCount: 0,
    constructionCollector: draft.collector || '',
    constructionModuleAssetNo: draft.module_asset_no || '',
    constructionStatus: 'cached',
  }
}

function orderToGroup(order: ConstructionExceptionOrder): MaterialGroup {
  const payload = order.payload || {}
  return {
    id: order.groupId || order.id,
    taskId: order.taskId || '',
    address: firstText(order.address, payloadText(payload, 'address')),
    meterNo: firstText(order.meterNo, payloadText(payload, 'meter_no', 'meterNo')),
    terminal: order.terminal || '',
    status: 'exception',
    photoCount: order.group?.photoCount || order.group?.photos?.length || 0,
    constructionCollector: firstText(order.group?.constructionCollector, payloadText(payload, 'collector')),
    constructionModuleAssetNo: firstText(
      order.group?.constructionModuleAssetNo,
      payloadText(payload, 'module_asset_no', 'moduleAssetNo', 'asset_no'),
    ),
    constructionStatus: 'exception',
    exceptionOrderId: order.id,
    exceptionNote: order.note,
    photos: order.group?.photos || [],
  }
}

function unmatchedRecordToConstructionGroup(record: UnmatchedRecord): MaterialGroup {
  return {
    id: record.unmatchedId || record.meterNo || record.barcode,
    taskId: '',
    address: record.address || '',
    meterNo: record.meterNo || record.barcode || '',
    meterMatchKey: record.meterMatchKey || '',
    terminal: record.terminal || '',
    status: 'pending',
    photoCount: record.photoCount || 0,
  }
}

function itemBadge(item: WorkItem) {
  if (item.draft) return { label: '已缓存', type: 'warning' as const }
  if (item.order) return { label: '异常工单', type: 'danger' as const }
  return { label: '未施工', type: 'info' as const }
}

function photoUrl(photo?: ReviewPhoto | null) {
  return photo?.imageUrl || photo?.url || ''
}

function firstText(...values: unknown[]) {
  for (const value of values) {
    const text = String(value ?? '').trim()
    if (text) return text
  }
  return ''
}

function payloadText(payload: Record<string, unknown> | undefined, ...keys: string[]) {
  if (!payload) return ''
  for (const key of keys) {
    const text = firstText(payload[key])
    if (text) return text
  }
  return ''
}

function existingPhotoForSlot(group: MaterialGroup | null, slotKey: string) {
  if (!group?.photos?.length) return null
  const aliases = slotAliases[slotKey] || [slotKey]
  return (
    group.photos.find((photo) => photo.constructionSlot === slotKey) ||
    group.photos.find((photo) => photo.category === slotKey) ||
    group.photos.find((photo) => {
      const text = `${photo.constructionSlot || ''} ${photo.constructionSlotLabel || ''} ${photo.category || ''} ${photo.categoryLabel || ''} ${photo.archiveFilename || ''} ${photo.name || ''}`
      return aliases.some((alias) => text.includes(alias))
    }) ||
    null
  )
}

function hasSlotPhoto(group: MaterialGroup | null, slotKey: string) {
  return Boolean(selectedFiles.value[slotKey] || existingPhotoForSlot(group, slotKey))
}

function coveredSlotsForGroup(group: MaterialGroup | null) {
  return activePhotoSlots.value.filter((slot) => existingPhotoForSlot(group, slot.key)).map((slot) => slot.key)
}

function clearPreviews() {
  for (const url of Object.values(previewUrls.value)) URL.revokeObjectURL(url)
  previewUrls.value = {}
}

function clearSelectedSlotPhoto(slotKey: string) {
  const oldUrl = previewUrls.value[slotKey]
  if (oldUrl) URL.revokeObjectURL(oldUrl)
  selectedFiles.value[slotKey] = null
  delete previewUrls.value[slotKey]
  selectedFiles.value = { ...selectedFiles.value }
  previewUrls.value = { ...previewUrls.value }
}

function resetCollectorForm() {
  form.collector = ''
  form.moduleAssetNo = ''
  form.dynamicFields = {}
  form.note = ''
  activeGroup.value = null
  activeOrder.value = null
  activePlatformWorkOrder.value = null
  selectedFiles.value = {}
  selectedItemKey.value = ''
  scannerFieldKey.value = ''
  clearPreviews()
}

function setFileInput(slotKey: string, source: PhotoSource, el: unknown, scope = 'inline') {
  const key = `${scope}:${slotKey}:${source}`
  if (el instanceof HTMLInputElement) fileInputs.set(key, el)
  else fileInputs.delete(key)
}

function triggerPhotoInput(slotKey: string, source: PhotoSource) {
  const preferredScope = collectOpen.value ? 'drawer' : 'inline'
  const preferred = fileInputs.get(`${preferredScope}:${slotKey}:${source}`)
  const fallback =
    fileInputs.get(`inline:${slotKey}:${source}`) || fileInputs.get(`drawer:${slotKey}:${source}`)
  ;(preferred || fallback)?.click()
}

async function compressImageFile(file: File): Promise<File> {
  if (!file.type.startsWith('image/') || file.type.includes('gif')) return file
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image()
    const objectUrl = URL.createObjectURL(file)
    img.onload = () => {
      URL.revokeObjectURL(objectUrl)
      resolve(img)
    }
    img.onerror = () => {
      URL.revokeObjectURL(objectUrl)
      reject(new Error('图片读取失败'))
    }
    img.src = objectUrl
  })
  const maxSide = 1600
  const scale = Math.min(1, maxSide / Math.max(image.naturalWidth || image.width, image.naturalHeight || image.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round((image.naturalWidth || image.width) * scale))
  canvas.height = Math.max(1, Math.round((image.naturalHeight || image.height) * scale))
  const ctx = canvas.getContext('2d')
  if (!ctx) return file
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height)
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.78))
  if (!blob) return file
  const name = file.name.replace(/\.[^.]+$/, '') || 'photo'
  return new File([blob], `${name}.jpg`, { type: 'image/jpeg', lastModified: Date.now() })
}

async function pickFile(slotKey: string, event: Event) {
  const input = event.target as HTMLInputElement
  const rawFile = input.files?.[0]
  input.value = ''
  if (!rawFile) return
  slotBusy.value = { ...slotBusy.value, [slotKey]: true }
  try {
    const file = await compressImageFile(rawFile)
    const oldUrl = previewUrls.value[slotKey]
    if (oldUrl) URL.revokeObjectURL(oldUrl)
    selectedFiles.value = { ...selectedFiles.value, [slotKey]: file }
    previewUrls.value = { ...previewUrls.value, [slotKey]: URL.createObjectURL(file) }
    await saveCurrentDraft({ silent: true })
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '照片处理失败')
  } finally {
    slotBusy.value = { ...slotBusy.value, [slotKey]: false }
  }
}

function getQuagga(): any {
  const source = window as unknown as {
    Quagga?: unknown
    Quagga2?: unknown
    exports?: { Quagga?: unknown }
    module?: { exports?: unknown }
  }
  return source.Quagga || source.Quagga2 || source.exports?.Quagga || source.module?.exports || null
}

function withTimeout<T>(promise: Promise<T>, milliseconds: number, message: string) {
  let timer = 0
  return new Promise<T>((resolve, reject) => {
    timer = window.setTimeout(() => reject(new Error(message)), milliseconds)
    promise.then(
      (value) => {
        window.clearTimeout(timer)
        resolve(value)
      },
      (error) => {
        window.clearTimeout(timer)
        reject(error)
      },
    )
  })
}

async function ensureQuaggaLoaded() {
  if (getQuagga()?.init) return getQuagga()
  await withTimeout(
    new Promise<void>((resolve, reject) => {
      const existing = document.querySelector<HTMLScriptElement>('script[data-quagga-loader="1"]')
      if (existing) {
        if (existing.dataset.loaded === '1' || getQuagga()?.init) {
          resolve()
          return
        }
        existing.addEventListener(
          'load',
          () => {
            existing.dataset.loaded = '1'
            resolve()
          },
          { once: true },
        )
        existing.addEventListener('error', () => reject(new Error('QuaggaJS 加载失败')), { once: true })
        return
      }
      const script = document.createElement('script')
      script.src = '/static/vendor/quagga.min.js?v=20260615-quagga2'
      script.async = true
      script.dataset.quaggaLoader = '1'
      script.onload = () => {
        script.dataset.loaded = '1'
        resolve()
      }
      script.onerror = () => reject(new Error('QuaggaJS 加载失败'))
      document.head.appendChild(script)
    }),
    SCANNER_START_TIMEOUT_MS,
    'QuaggaJS 加载超时',
  )
  return getQuagga()
}

function resetScannerRuntime() {
  clearTimeout(scannerTimer)
  scannerTimer = 0
  const quagga = getQuagga()
  if (quaggaActive && quagga) {
    if (quaggaDetectedHandler) quagga.offDetected?.(quaggaDetectedHandler)
    try {
      quagga.stop()
    } catch {
      // Ignore scanner shutdown races on mobile browsers.
    }
  }
  quaggaActive = false
  quaggaDetectedHandler = null
  scannerStream?.getTracks().forEach((track) => track.stop())
  scannerStream = null
  if (scannerVideo.value) scannerVideo.value.srcObject = null
  scannerCamera.value?.querySelectorAll('canvas, video:not(.scanner-video)').forEach((node) => node.remove())
}

function closeScanner() {
  resetScannerRuntime()
  scannerOpen.value = false
  scannerFieldKey.value = ''
}

async function startScanner(target: ScannerTarget) {
  scannerTarget.value = target
  scannerOpen.value = true
  scanCandidate = ''
  scanCandidateHits = 0
  scanLocked = false
  scannerStatus.value = '正在启动相机，请允许浏览器使用摄像头。'
  scannerHint.value =
    target === 'dynamic'
      ? `扫描${activeScannerField()?.label || '字段'}条码后填入当前字段`
      : target === 'collector'
      ? '采集器扫码成功后只填入编号，照片仍需单独拍摄'
      : target === 'module'
        ? '将模块条码横向放入框内'
        : '扫描表号条码后直接打开施工单'

  await nextTick()
  if (!window.isSecureContext || typeof navigator.mediaDevices?.getUserMedia !== 'function') {
    prepareScannerFallback('当前浏览器未开放摄像头能力')
    return
  }

  const quagga = await ensureQuaggaLoaded().catch(() => null)
  if (quagga?.init) {
    try {
      await withTimeout(startQuaggaScanner(), SCANNER_START_TIMEOUT_MS, '相机启动超时')
      return
    } catch {
      resetScannerRuntime()
      scannerStatus.value = '实时扫码启动失败，正在切换相机预览。'
    }
  }

  try {
    await withTimeout(startNativeScanner(), SCANNER_START_TIMEOUT_MS, '相机启动超时')
    return
  } catch {
    resetScannerRuntime()
    prepareScannerFallback('相机启动失败')
    return
  }
}

async function startQuaggaScanner() {
  const quagga = await ensureQuaggaLoaded()
  const target = scannerCamera.value
  if (!quagga?.init || !target) throw new Error('QuaggaJS 不可用')
  scannerCamera.value?.querySelectorAll('canvas, video:not(.scanner-video)').forEach((node) => node.remove())
  await withTimeout(
    new Promise<void>((resolve, reject) => {
      quagga.init(
        {
          inputStream: {
            name: 'Live',
            type: 'LiveStream',
            target,
            constraints: {
              facingMode: { ideal: 'environment' },
              width: { ideal: 1280 },
              height: { ideal: 720 },
              audio: false,
            },
          },
          locator: { patchSize: 'medium', halfSample: true },
          locate: true,
          numOfWorkers: Math.min(2, Math.max(0, navigator.hardwareConcurrency || 0)),
          frequency: 8,
          decoder: { readers: QUAGGA_READERS },
        },
        (error: unknown) => (error ? reject(error) : resolve()),
      )
    }),
    SCANNER_START_TIMEOUT_MS,
    'QuaggaJS 初始化超时',
  )
  quaggaActive = true
  quaggaDetectedHandler = (result: any) => handleDetectedCode(result?.codeResult?.code || '')
  quagga.onDetected(quaggaDetectedHandler)
  quagga.start()
  scannerStatus.value = 'QuaggaJS 正在识别条形码。'
}

async function requestCameraStream() {
  try {
    return await withTimeout(
      navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      }),
      SCANNER_START_TIMEOUT_MS,
      '后置摄像头启动超时',
    )
  } catch {
    return await withTimeout(navigator.mediaDevices.getUserMedia({ video: true, audio: false }), SCANNER_START_TIMEOUT_MS, '摄像头启动超时')
  }
}

async function startNativeScanner() {
  if (!scannerVideo.value) throw new Error('扫描视频容器不可用')
  scannerVideo.value.setAttribute('playsinline', 'true')
  scannerVideo.value.setAttribute('webkit-playsinline', 'true')
  scannerVideo.value.autoplay = true
  scannerStream = await requestCameraStream()
  scannerVideo.value.srcObject = scannerStream
  await withTimeout(scannerVideo.value.play(), 3000, '摄像头预览启动超时')
  const detectorCtor = (window as unknown as { BarcodeDetector?: new (options: { formats: string[] }) => any }).BarcodeDetector
  if (!detectorCtor) {
    scannerStatus.value = '相机已打开，当前浏览器不支持实时识别，可拍照识别或手动输入。'
    scannerHint.value = '保持此窗口可确认相机已启动；需要自动识别时请点击拍照识别'
    return
  }
  const detector = new detectorCtor({ formats: ['code_128', 'code_39', 'qr_code', 'ean_13', 'ean_8'] })
  scannerStatus.value = '相机已打开，正在使用浏览器原生识别。'
  const tick = async () => {
    try {
      const codes = await detector.detect(scannerVideo.value)
      if (codes.length) {
        await applyScanValue(codes[0].rawValue || '')
        closeScanner()
        return
      }
    } catch {
      closeScanner()
      scannerOpen.value = true
      prepareScannerFallback('实时识别失败')
      return
    }
    scannerTimer = window.setTimeout(tick, 320)
  }
  void tick()
}

function handleDetectedCode(rawCode: string) {
  const code = String(rawCode || '').trim()
  if (!code || scanLocked) return
  if (scanCandidate === code) scanCandidateHits += 1
  else {
    scanCandidate = code
    scanCandidateHits = 1
  }
  scannerStatus.value = scanCandidateHits < 2 ? `已捕捉 ${code}，请保持稳定` : `已识别 ${code}`
  if (scanCandidateHits < 2) return
  scanLocked = true
  void applyScanValue(code).finally(closeScanner)
}

async function decodeImageBarcode(file: File) {
  const quagga = await ensureQuaggaLoaded().catch(() => null)
  if (quagga?.decodeSingle) {
    const src = URL.createObjectURL(file)
    try {
      return await new Promise<string>((resolve) => {
        quagga.decodeSingle(
          {
            src,
            inputStream: { size: 1600 },
            locator: { patchSize: 'medium', halfSample: false },
            locate: true,
            decoder: { readers: QUAGGA_READERS },
          },
          (result: any) => resolve(result?.codeResult?.code || ''),
        )
      })
    } finally {
      URL.revokeObjectURL(src)
    }
  }
  const detectorCtor = (window as unknown as { BarcodeDetector?: new (options: { formats: string[] }) => any }).BarcodeDetector
  if (!detectorCtor) return ''
  try {
    const bitmap = await createImageBitmap(file)
    const detector = new detectorCtor({ formats: ['code_128', 'code_39', 'qr_code', 'ean_13', 'ean_8'] })
    const codes = await detector.detect(bitmap)
    bitmap.close?.()
    return codes[0]?.rawValue || ''
  } catch {
    return ''
  }
}

async function fallbackScannerInput(reason = '') {
  scannerStatus.value = `${reason || '实时扫码不可用'}，可拍照识别或手动输入。`
  const input = scannerFileInput.value
  if (!input) {
    await manualScannerInput()
    return
  }
  input.value = ''
  const file = await new Promise<File | null>((resolve) => {
    input.addEventListener('change', () => resolve(input.files?.[0] || null), { once: true })
    input.click()
  })
  if (!file) {
    await manualScannerInput()
    return
  }
  const decoded = await decodeImageBarcode(file)
  if (decoded) {
    await applyScanValue(decoded)
    ElMessage.success('已识别并填入编号')
    closeScanner()
    return
  }
  await manualScannerInput('已拍照，但当前环境无法自动识别条码，请手动确认编号')
}

function prepareScannerFallback(reason = '') {
  scannerStatus.value = `${reason || '实时扫码不可用'}，请点击“拍照识别”或“手动输入”。`
  scannerHint.value = '移动浏览器要求相机/相册必须由用户点击按钮打开'
}

async function manualScannerInput(message = '请输入编号') {
  const dynamicField = activeScannerField()
  const current =
    scannerTarget.value === 'dynamic' && dynamicField
      ? fieldValue(dynamicField)
      : scannerTarget.value === 'collector'
      ? form.collector
      : scannerTarget.value === 'module'
        ? form.moduleAssetNo
        : quickMeter.value
  const { value } = await ElMessageBox.prompt(message, scannerTitle.value, {
    confirmButtonText: '确认',
    cancelButtonText: '取消',
    inputValue: current,
  })
  const clean = String(value || '').trim()
  if (clean) await applyScanValue(clean)
  closeScanner()
}

async function applyScanValue(value: string) {
  const clean = String(value || '').trim()
  if (scannerTarget.value === 'quickMeter') {
    quickMeter.value = clean
    openByMeter(clean)
    return
  }
  if (scannerTarget.value === 'dynamic') {
    const field = activeScannerField()
    if (field) setFieldValue(field, clean)
  }
  if (scannerTarget.value === 'collector') form.collector = clean
  if (scannerTarget.value === 'module') form.moduleAssetNo = clean
  await saveCurrentDraft({ silent: true })
  ElMessage.success(clean ? `已填入 ${clean}` : '未识别到有效编号')
}

function openRawDatabase(version?: number): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = version ? indexedDB.open(DB_NAME, version) : indexedDB.open(DB_NAME)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(DRAFT_STORE)) db.createObjectStore(DRAFT_STORE, { keyPath: 'client_batch_id' })
      if (!db.objectStoreNames.contains(SNAPSHOT_STORE)) db.createObjectStore(SNAPSHOT_STORE, { keyPath: 'id' })
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('本地缓存数据库打开失败'))
  })
}

async function openCacheDatabase(): Promise<IDBDatabase> {
  const db = await openRawDatabase()
  if (db.objectStoreNames.contains(DRAFT_STORE) && db.objectStoreNames.contains(SNAPSHOT_STORE)) return db
  const nextVersion = db.version + 1
  db.close()
  return openRawDatabase(nextVersion)
}

async function withStore<T>(
  storeName: typeof DRAFT_STORE | typeof SNAPSHOT_STORE,
  mode: IDBTransactionMode,
  action: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await openCacheDatabase()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, mode)
    const request = action(tx.objectStore(storeName))
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('本地缓存操作失败'))
    tx.oncomplete = () => db.close()
    tx.onerror = () => {
      db.close()
      reject(tx.error || new Error('本地缓存事务失败'))
    }
  })
}

async function loadDrafts() {
  try {
    const allDrafts = await withStore<CacheDraft[]>(DRAFT_STORE, 'readonly', (store) => store.getAll())
    const invalidDrafts = allDrafts.filter(isEmptyPlaceholderConstructionDraft)
    if (invalidDrafts.length) {
      await Promise.all(invalidDrafts.map((draft) => deleteDraft(draft.client_batch_id)))
    }
    drafts.value = allDrafts.filter((draft) => !isEmptyPlaceholderConstructionDraft(draft))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '缓存读取失败'
  }
}

async function putDraft(draft: CacheDraft) {
  await withStore(DRAFT_STORE, 'readwrite', (store) => store.put(draft))
}

async function deleteDraft(clientBatchId: string) {
  await withStore(DRAFT_STORE, 'readwrite', (store) => store.delete(clientBatchId))
}

async function getDraft(clientBatchId: string): Promise<CacheDraft | undefined> {
  return withStore<CacheDraft | undefined>(DRAFT_STORE, 'readonly', (store) => store.get(clientBatchId))
}

function draftHasContent(draft: CacheDraft) {
  return Boolean(
    (draft.photos || []).length ||
      String(draft.collector || '').trim() ||
      String(draft.module_asset_no || '').trim() ||
      Object.values(draft.field_values || {}).some((value) => String(value || '').trim()) ||
      String(draft.work_order_id || '').trim(),
  )
}

async function putTerminalSnapshot(task: ReviewTask, taskGroups: MaterialGroup[], orders: ConstructionExceptionOrder[]) {
  const plainTask = JSON.parse(JSON.stringify(task)) as ReviewTask
  const plainGroups = JSON.parse(JSON.stringify(taskGroups)) as MaterialGroup[]
  const plainOrders = JSON.parse(JSON.stringify(orders)) as ConstructionExceptionOrder[]
  const snapshot: TerminalSnapshot = {
    id: snapshotKey(task.id),
    actor: actor.value,
    taskId: task.id,
    terminal: task.terminal || '',
    task: plainTask,
    groups: plainGroups,
    exceptionOrders: plainOrders,
    updated_at: new Date().toISOString(),
  }
  await withStore(SNAPSHOT_STORE, 'readwrite', (store) => store.put(snapshot))
}

async function getTerminalSnapshot(taskId: string): Promise<TerminalSnapshot | undefined> {
  return withStore<TerminalSnapshot | undefined>(SNAPSHOT_STORE, 'readonly', (store) => store.get(snapshotKey(taskId)))
}

async function getAllSnapshots(): Promise<TerminalSnapshot[]> {
  return withStore<TerminalSnapshot[]>(SNAPSHOT_STORE, 'readonly', (store) => store.getAll())
}

function fileFromDraftPhoto(photo: DraftPhoto, index: number): File | null {
  const source = photo.file || photo.blob
  if (!source) return null
  if (source instanceof File) return source
  return new File([source], photo.filename || photo.name || `photo-${index + 1}.jpg`, { type: source.type || 'image/jpeg' })
}

function exceptionNeedsPhotoSlots(source: PhotoRequirementSource = {}) {
  if (!source.work_order_id && !source.exception_order_id) return true
  const text = `${source.exception_category || source.category || ''} ${source.exception_note || source.note || ''}`.toLowerCase()
  if (!text.trim()) return true
  return /photo|image|missing|照片|缺|图|圖/.test(text)
}

function missingSlotsForDraft(draft: CacheDraft) {
  if (draft.work_order_id && !exceptionNeedsPhotoSlots(draft)) return []
  const covered = new Set([...(draft.covered_slots || []), ...((draft.photos || []).map((photo) => photo.slot).filter(Boolean) as string[])])
  return photoSlots.value
    .filter((slot) => isPhotoSlotConditionActiveForValues(slot, draft.field_values || {}) && isPhotoSlotRequiredForValues(slot, draft.field_values || {}) && !covered.has(slot.key))
    .map((slot) => slot.label)
}

function missingConfiguredFieldsForDraft(draft: CacheDraft) {
  if (!hasConfiguredConstructionFields.value) return draft.module_asset_no?.trim() ? [] : ['模块资产编号']
  return constructionFields.value
    .filter((field) => isFieldConditionActiveForValues(field, draft.field_values || {}) && isFieldRequiredForValues(field, draft.field_values || {}) && !String(draft.field_values?.[field.key] || '').trim())
    .map((field) => field.label)
}

function draftReady(draft: CacheDraft) {
  return Boolean(
    (draft.groupId || draft.group_id) &&
      missingConfiguredFieldsForDraft(draft).length === 0 &&
      !constructionDraftUploadBlockReason(draft) &&
      missingSlotsForDraft(draft).length === 0,
  )
}

function draftCompletedAt(draft: CacheDraft) {
  if (!draftReady(draft)) return ''
  return draft.client_completed_at || draft.updated_at || draft.created_at || ''
}

async function loadDraftIntoForm(group: MaterialGroup) {
  suspendDraftAutoPersist = true
  try {
    selectedFiles.value = {}
    clearPreviews()
    const draft = await getDraft(draftKey(selectedTaskId.value, group.id))
    const orderPayload = activeOrder.value?.payload || {}
    form.collector = firstText(
      draft?.collector,
      group.constructionCollector,
      payloadText(orderPayload, 'collector'),
      group.photos?.[0]?.collector,
    )
    form.moduleAssetNo = firstText(
      draft?.module_asset_no,
      group.constructionModuleAssetNo,
      payloadText(orderPayload, 'module_asset_no', 'moduleAssetNo', 'asset_no'),
      group.photos?.[0]?.moduleAssetNo,
    )
    form.dynamicFields = { ...(draft?.field_values || {}) }
    for (const field of constructionFields.value) {
      const existing = fieldValue(field)
      if (existing) continue
      setFieldValue(field, firstText(payloadText(orderPayload, field.key), payloadText(orderPayload, field.key.replace(/_/g, ''))))
    }
    form.note = firstText(draft?.exception_note, group.exceptionNote, activeOrder.value?.note)
    if (draft?.photos?.length) {
      const files: Record<string, File | null> = {}
      const urls: Record<string, string> = {}
      draft.photos.forEach((photo, index) => {
        const file = fileFromDraftPhoto(photo, index)
        if (!file || !photo.slot) return
        files[photo.slot] = file
        urls[photo.slot] = URL.createObjectURL(file)
      })
      selectedFiles.value = files
      previewUrls.value = urls
    }
  } finally {
    await nextTick()
    suspendDraftAutoPersist = false
  }
}

function buildCurrentDraft(): CacheDraft {
  if (!activeGroup.value || !selectedTask.value) throw new Error('请先选择施工资料组')
  const now = new Date().toISOString()
  const previousDraft = draftByGroupId.value.get(String(activeGroup.value.id))
  const photos = Object.entries(selectedFiles.value)
    .filter(([slot]) => activePhotoSlotKeys.value.has(slot))
    .map(([slot, file]) => {
      if (!file) return null
      return {
        slot,
        file,
        filename: file.name,
        name: file.name,
        client_photo_id: `${slot}-${file.name}-${file.size}-${file.lastModified}`,
      }
    })
    .filter(Boolean) as DraftPhoto[]
  const draft: CacheDraft = {
    client_batch_id: draftKey(selectedTask.value.id, activeGroup.value.id),
    teamId: teamId.value,
    actor: actor.value,
    taskId: selectedTask.value.id,
    groupId: activeGroup.value.id,
    terminal: activeGroup.value.terminal,
    meter_no: activeGroup.value.meterNo,
    address: activeGroup.value.address,
    collector: form.collector.trim(),
    module_asset_no: form.moduleAssetNo.trim(),
    work_order_id: activeOrder.value?.id || activeGroup.value.exceptionOrderId || '',
    exception_category: activeOrder.value?.category || '',
    exception_note: form.note.trim(),
    covered_slots: coveredSlotsForGroup(activeGroup.value),
    field_values: collectFieldValues(),
    photos,
    status: 'queued',
    created_at: previousDraft?.created_at || now,
    updated_at: now,
  }
  draft.client_completed_at = draftReady(draft) ? now : previousDraft?.client_completed_at || ''
  return draft
}

async function persistCurrentDraft() {
  if (!activeGroup.value || !selectedTask.value) return
  const previousDraft = activeGroup.value ? draftByGroupId.value.get(String(activeGroup.value.id)) : null
  const draft = buildCurrentDraft()
  if (draftHasContent(draft)) {
    await putDraft(draft)
    if (draft.client_completed_at && !previousDraft?.client_completed_at) {
      void sendConstructionNonIdleEvent('group_draft_completed', draft)
    }
  } else await deleteDraft(draft.client_batch_id)
  await loadDrafts()
}

async function sendConstructionHeartbeat() {
  if (isAdmin.value || !online() || !selectedTaskId.value) return
  try {
    await recordConstructionHeartbeat({
      actor: actor.value,
      taskId: selectedTaskId.value,
      occurredAt: new Date().toISOString(),
    })
  } catch (error) {
    console.warn('construction heartbeat failed', error)
  }
}

async function sendConstructionNonIdleEvent(
  eventType: 'group_draft_completed' | 'group_draft_deleted' | 'group_uploaded',
  draft: CacheDraft,
) {
  if (isAdmin.value || !online()) return
  try {
    await recordConstructionNonIdleEvent({
      eventType,
      actor: draft.actor || actor.value,
      taskId: draft.taskId || selectedTaskId.value,
      groupId: String(draft.groupId || draft.group_id || ''),
      clientBatchId: draft.client_batch_id,
      occurredAt: eventType === 'group_draft_completed' ? draft.client_completed_at || new Date().toISOString() : new Date().toISOString(),
    })
  } catch (error) {
    console.warn('construction non-idle event failed', error)
  }
}

async function saveCurrentDraft(options: { silent?: boolean } = {}) {
  if (!activeGroup.value || !selectedTask.value) return
  cacheBusy.value = true
  try {
    await persistCurrentDraft()
    if (!options.silent) ElMessage.success('已保存到本地缓存')
  } catch (error) {
    if (!options.silent) ElMessage.error(error instanceof Error ? error.message : '保存缓存失败')
  } finally {
    cacheBusy.value = false
  }
}

async function removeCachedDraft(draft?: CacheDraft | null) {
  if (!draft?.client_batch_id) return
  try {
    await ElMessageBox.confirm('确认删除这条本地缓存？只会清理本机待上传草稿，不会删除服务器资料。', '删除本地缓存', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    const wasActive = activeCachedDraft.value?.client_batch_id === draft.client_batch_id
    await deleteDraft(draft.client_batch_id)
    if (draft.client_completed_at) void sendConstructionNonIdleEvent('group_draft_deleted', draft)
    await loadDrafts()
    if (wasActive) {
      selectedItemKey.value = ''
      collectOpen.value = false
      resetCollectorForm()
    }
    ElMessage.success('本地缓存已删除')
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(error instanceof Error ? error.message : '删除缓存失败')
  }
}

function scheduleCurrentDraftPersist() {
  window.clearTimeout(draftPersistTimer)
  draftPersistTimer = window.setTimeout(() => {
    draftPersistTimer = 0
    persistCurrentDraft().catch((error) => {
      console.warn('construction draft autosave failed', error)
    })
  }, 500)
}

async function flushCurrentDraftPersist() {
  if (draftPersistTimer) {
    window.clearTimeout(draftPersistTimer)
    draftPersistTimer = 0
  }
  await persistCurrentDraft()
}

async function uploadDraft(draft: CacheDraft) {
  if (!online()) throw new Error('当前离线，已保留本地缓存')
  const blockedReason = constructionDraftUploadBlockReason(draft)
  if (blockedReason) throw new Error(blockedReason)
  const missingFields = missingConfiguredFieldsForDraft(draft)
  if (missingFields.length) throw new Error(`缺少必填字段：${missingFields.join('、')}`)
  const missing = missingSlotsForDraft(draft)
  if (missing.length) throw new Error(`缺少必填照片：${missing.join('、')}`)
  const groupId = String(draft.groupId || draft.group_id || '')
  if (!groupId) throw new Error('缓存缺少资料组 ID')
  const photos = (draft.photos || [])
    .map((photo, index) => {
      const file = fileFromDraftPhoto(photo, index)
      return file
        ? {
            slot: photo.slot || 'other',
            file,
            clientPhotoId: photo.client_photo_id || `${draft.client_batch_id}-${index + 1}`,
          }
        : null
    })
    .filter(Boolean) as Array<{ slot: string; file: File; clientPhotoId: string }>

  let uploadedGroupId = groupId
  if (photos.length) {
    const result = await uploadConstructionBatch(groupId, {
      actor: draft.actor || actor.value,
      clientBatchId: draft.client_batch_id,
      clientCompletedAt: draftCompletedAt(draft),
      collector: draft.collector || '',
      moduleAssetNo: draft.module_asset_no || '',
      fieldValues: draft.field_values || {},
      photos,
    })
    uploadedGroupId = result.group?.id || uploadedGroupId
  }

  if (draft.work_order_id) {
    const result = await submitConstructionExceptionOrder(
      draft.work_order_id,
      {
        meterNo: draft.meter_no,
        collector: draft.collector,
        moduleAssetNo: draft.module_asset_no,
      },
      draft.exception_note || '现场已处理异常工单',
    )
    uploadedGroupId = result.group?.id || uploadedGroupId
  }

  if (!photos.length && !draft.work_order_id) throw new Error('没有可上传的照片')

  await deleteDraft(draft.client_batch_id)
  await loadDrafts()
  return uploadedGroupId
}

async function uploadCurrentDraft() {
  if (!activeGroup.value) return
  try {
    await saveCurrentDraft({ silent: true })
    const draft = buildCurrentDraft()
    uploading.value = true
    const groupId = await uploadDraft(draft)
    ElMessage.success('施工资料已上传')
    await reloadAfterUpload(groupId)
    collectOpen.value = false
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '上传失败，已保留本地缓存')
  } finally {
    uploading.value = false
  }
}

async function uploadAllCached() {
  if (!readyCachedDrafts.value.length) {
    ElMessage.warning('当前终端没有可上传的完整缓存')
    return
  }
  uploading.value = true
  let success = 0
  let failed = 0
  for (const draft of [...readyCachedDrafts.value]) {
    try {
      await uploadDraft(draft)
      success += 1
    } catch {
      failed += 1
    }
  }
  uploading.value = false
  ElMessage.success(`缓存上传完成：成功 ${success}，失败 ${failed}`)
  await reloadAfterUpload()
}

async function submitSelectedConstructionTask() {
  const task = selectedTask.value
  if (!task) return
  if (!canSubmitSelectedTask.value) {
    ElMessage.warning('只有当前被指派的施工员可以提交这个施工任务')
    return
  }
  if (!online()) {
    ElMessage.warning('当前离线，联网后再提交施工任务')
    return
  }
  const unbuiltCount = taskUnbuiltCount(task)
  const cacheCount = cachedTaskDrafts.value.length
  const details: string[] = []
  if (cacheCount) details.push(`还有 ${cacheCount} 条本地缓存未上传`)
  if (unbuiltCount) details.push(`还有 ${unbuiltCount} 个资料组显示未施工`)
  const message = details.length
    ? `${details.join('，')}。提交后该终端会从你的施工采集页释放，请确认现场任务已经处理完毕。`
    : '确认提交这个施工任务？提交后该终端会从你的施工采集页释放。'
  try {
    await flushCurrentDraftPersist()
    await ElMessageBox.confirm(message, '提交施工任务', {
      type: details.length ? 'warning' : 'success',
      confirmButtonText: '确认提交',
      cancelButtonText: '取消',
    })
    submittingTask.value = true
    await releaseConstructionTask(task.id)
    ElMessage.success('施工任务已提交')
    selectedTaskId.value = ''
    selectedItemKey.value = ''
    groups.value = []
    exceptionOrders.value = []
    collectOpen.value = false
    activeGroup.value = null
    activeOrder.value = null
    taskPickerOpen.value = true
    await loadTasks()
  } catch (error) {
    if (error === 'cancel') return
    ElMessage.error(error instanceof Error ? error.message : '提交施工任务失败')
  } finally {
    submittingTask.value = false
  }
}

async function selectTask(task: ReviewTask) {
  if (isAdmin.value) {
    selectedTaskId.value = task.id
    taskPickerMode.value = 'terminal'
    taskQuery.value = ''
    submittedTaskQuery.value = ''
    taskPickerOpen.value = true
    return
  }
  await flushCurrentDraftPersist()
  taskPickerMode.value = 'terminal'
  selectedTaskId.value = task.id
  selectedItemKey.value = ''
  taskQuery.value = ''
  submittedTaskQuery.value = ''
  groupQuery.value = ''
  quickMeter.value = ''
  groupFilter.value = 'all'
  taskPickerOpen.value = false
  resetCollectorForm()
  await loadGroups()
}

async function openUnbuiltDialog(task: ReviewTask, options: { preserveQuery?: boolean } = {}) {
  if (!isAdmin.value) return
  const previousQuery = unbuiltDialogQuery.value
  unbuiltDialogOpen.value = true
  unbuiltDialogTask.value = task
  unbuiltDialogGroups.value = []
  unbuiltDialogQuery.value = options.preserveQuery ? previousQuery : ''
  unbuiltDialogError.value = ''
  unbuiltDialogLoading.value = true
  try {
    const items = await fetchConstructionTaskGroups(task.id)
    unbuiltDialogGroups.value = sortGroupsByAddress(items.filter(isCollectableConstructionGroup))
  } catch (error) {
    unbuiltDialogError.value = error instanceof Error ? error.message : '未施工清单加载失败'
  } finally {
    unbuiltDialogLoading.value = false
  }
}

async function reloadUnbuiltDialog() {
  if (!unbuiltDialogTask.value) return
  await openUnbuiltDialog(unbuiltDialogTask.value, { preserveQuery: true })
}

async function loadFieldTaskCards() {
  if (isAdmin.value || !online()) return
  try {
    const [orders, unmatched] = await Promise.all([
      fetchConstructionExceptionOrders('', actor.value),
      fetchUnmatchedRecords(''),
    ])
    fieldExceptionOrders.value = orders
    unmatchedRecords.value = unmatched
  } catch {
    // Field task cards are auxiliary. Keep terminal collection available on weak networks.
  }
}

async function loadPlatformProjects() {
  try {
    platformProjects.value = await fetchProjectsWithModules()
  } catch {
    platformProjects.value = []
  }
  await loadPlatformConstructionWorkOrders()
}

async function loadPlatformConstructionWorkOrders() {
  const projectId = activeProjectId.value
  if (!projectId) return
  loadingPlatformWorkOrders.value = true
  try {
    const data = await fetchProjectConstructionWorkOrders(projectId)
    platformConstructionWorkOrders.value = data.items
    platformConstructionSchema.value = data.fieldSchema
    platformConstructionTotal.value = data.total
  } catch {
    platformConstructionWorkOrders.value = []
    platformConstructionSchema.value = null
    platformConstructionTotal.value = 0
  } finally {
    loadingPlatformWorkOrders.value = false
  }
}

function findTaskForFieldCard(taskId?: string | number, terminal?: string) {
  const normalizedTaskId = String(taskId || '').trim()
  const normalizedTerminal = String(terminal || '').trim()
  return visibleTasks.value.find((item) => {
    if (normalizedTaskId && String(item.id) === normalizedTaskId) return true
    if (normalizedTerminal && String(item.terminal || '') === normalizedTerminal) return true
    return false
  })
}

async function selectTaskPickerMode(mode: TaskPickerMode) {
  await flushCurrentDraftPersist()
  taskPickerMode.value = mode
  if (mode !== 'terminal') {
    taskPickerOpen.value = true
    selectedTaskId.value = ''
    groups.value = []
    exceptionOrders.value = []
    resetCollectorForm()
    await loadFieldTaskCards()
    if (mode === 'exception' && visibleExceptionTaskCards.value.length === 1) {
      await openExceptionTaskCard(visibleExceptionTaskCards.value[0])
    }
    if (mode === 'unmatched' && visibleUnmatchedTaskCards.value.length === 1) {
      await openUnmatchedTaskCard(visibleUnmatchedTaskCards.value[0])
    }
  }
}

async function openExceptionTaskCard(order: ConstructionExceptionOrder) {
  const task = findTaskForFieldCard(order.taskId, order.terminal)
  if (!task) {
    ElMessage.warning('该异常任务尚未绑定可进入的终端')
    return
  }
  await selectTask(task)
  groupFilter.value = 'exception'
  await nextTick()
  const target = workItems.value.find((item) => item.order?.id === order.id || String(item.group.id) === String(order.groupId))
  if (target) await openWorkItem(target)
}

async function openUnmatchedTaskCard(record: UnmatchedRecord) {
  const task = findTaskForFieldCard('', record.terminal)
  if (!task) {
    ElMessage.info('该未匹配任务需要先由管理员补充或指派终端')
    return
  }
  await selectTask(task)
  groupQuery.value = record.barcode || record.meterNo || record.address || ''
}

async function useSnapshot(taskId: string, reason = '') {
  const snapshot = await getTerminalSnapshot(taskId)
  if (!snapshot) throw new Error(reason || '当前终端没有可用离线包，请先在有网时打开一次')
  offlineMode.value = true
  groups.value = sortGroupsByAddress((snapshot.groups || []).filter(isCollectableConstructionGroup))
  exceptionOrders.value = (snapshot.exceptionOrders || []).filter((order) => isCollectableConstructionGroup(order.group || orderToGroup(order)))
  const exists = tasks.value.some((task) => task.id === snapshot.task.id)
  if (!exists) tasks.value = [snapshot.task, ...tasks.value]
}

async function loadAccountUsers() {
  if (!isAdmin.value) {
    accountUsers.value = []
    return
  }
  try {
    accountUsers.value = await fetchUserAccounts()
  } catch {
    accountUsers.value = []
  }
}

async function loadTasks() {
  loadingTasks.value = true
  errorMessage.value = ''
  try {
    await loadDrafts()
    await loadAccountUsers()
    if (!online()) throw new Error('offline')
    tasks.value = await fetchConstructionTasks(false, isAdmin.value ? '' : actor.value)
    await loadFieldTaskCards()
    offlineMode.value = false
  } catch (error) {
    try {
      const snapshots = await getAllSnapshots()
      tasks.value = snapshots
        .filter((snapshot) => snapshot.actor === actor.value)
        .map((snapshot) => ({ ...snapshot.task, constructionClaimedBy: snapshot.task.constructionClaimedBy || actor.value }))
      offlineMode.value = tasks.value.length > 0
      if (!tasks.value.length && error instanceof Error && error.message !== 'offline') throw error
    } catch (cacheError) {
      errorMessage.value = cacheError instanceof Error ? cacheError.message : '施工任务加载失败'
    }
  } finally {
    if (isAdmin.value) {
      if (!selectedTaskId.value || !visibleTasks.value.some((task) => task.id === selectedTaskId.value)) {
        selectedTaskId.value = visibleTasks.value[0]?.id || ''
      }
      taskPickerMode.value = 'terminal'
      taskPickerOpen.value = true
    } else if (taskPickerMode.value !== 'terminal') {
      selectedTaskId.value = ''
      taskPickerOpen.value = true
    } else if (!selectedTaskId.value || !visibleTasks.value.some((task) => task.id === selectedTaskId.value)) {
      selectedTaskId.value = visibleTasks.value[0]?.id || ''
      const hasAssignedFieldTasks = visibleExceptionTaskCards.value.length > 0 || visibleUnmatchedTaskCards.value.length > 0
      taskPickerOpen.value = hasAssignedFieldTasks || visibleTasks.value.length !== 1
    }
    loadingTasks.value = false
  }
  void loadPlatformConstructionWorkOrders()
  if (!isAdmin.value && taskPickerMode.value === 'terminal' && selectedTaskId.value) await loadGroups()
}

async function loadGroups() {
  if (!selectedTaskId.value) {
    groups.value = []
    exceptionOrders.value = []
    return
  }
  loadingGroups.value = true
  errorMessage.value = ''
  try {
    await loadDrafts()
    if (!online()) throw new Error('offline')
    const [taskGroups, orders] = await Promise.all([
      fetchConstructionTaskGroups(selectedTaskId.value),
      fetchConstructionExceptionOrders(selectedTaskId.value),
    ])
    const collectableGroups = taskGroups.filter(isCollectableConstructionGroup)
    const collectableOrders = orders.filter((order) => isCollectableConstructionGroup(order.group || orderToGroup(order)))
    groups.value = sortGroupsByAddress(collectableGroups)
    exceptionOrders.value = collectableOrders
    offlineMode.value = false
    if (selectedTask.value) await putTerminalSnapshot(selectedTask.value, collectableGroups, collectableOrders)
  } catch (error) {
    try {
      await useSnapshot(selectedTaskId.value, error instanceof Error ? error.message : '')
    } catch (cacheError) {
      errorMessage.value = cacheError instanceof Error ? cacheError.message : '资料组加载失败'
      groups.value = []
      exceptionOrders.value = []
    }
  } finally {
    loadingGroups.value = false
  }
}

async function openWorkItem(item: WorkItem) {
  await flushCurrentDraftPersist()
  const blockedReason = constructionGroupOpenBlockReason(item.group)
  if (blockedReason) {
    ElMessage.warning(blockedReason)
    return
  }
  selectedItemKey.value = item.key
  activeOrder.value = item.order || null
  activePlatformWorkOrder.value = null
  activeGroup.value = item.group
  collectOpen.value = shouldUseCollectorDrawer()
  await loadDraftIntoForm(item.group)
  if (online() && item.group.id) {
    try {
      const detail = await fetchGroup(item.group.id)
      activeGroup.value = {
        ...item.group,
        ...detail.group,
        exceptionOrderId: item.order?.id || detail.group.exceptionOrderId,
        exceptionNote: item.order?.note || detail.group.exceptionNote,
      }
      await loadDraftIntoForm(activeGroup.value)
    } catch {
      // 现场弱网时继续使用终端离线包里的概要数据。
    }
  }
}

function shouldUseCollectorDrawer() {
  return typeof window !== 'undefined' && window.matchMedia('(max-width: 960px)').matches
}

async function reloadAfterUpload(preferredGroupId = '') {
  await Promise.all([loadDrafts(), loadGroups(), loadTasks()])
  if (preferredGroupId) {
    const next = visibleWorkItems.value.find((item) => item.group.id === preferredGroupId)
    if (next) selectedItemKey.value = next.key
  }
}

function handleExternalRefresh(event: MessageEvent) {
  if (event.data?.type !== 'module-manager:data-refresh') return
  void loadTasks()
}

function openByMeter(value = quickMeter.value) {
  const keyword = normalizeSearch(value)
  if (!keyword) {
    ElMessage.warning('请先输入或扫码表号')
    return
  }
  const item = findWorkItemByMeterCode(value)
  if (!item) {
    groupQuery.value = value
    ElMessage.warning('无工单：扫码结果不在当前施工工单中')
    return
  }
  groupFilter.value = 'all'
  groupQuery.value = value
  void openWorkItem(item)
}

function clearGroupSearch() {
  groupQuery.value = ''
  quickMeter.value = ''
}

async function returnToTaskPicker() {
  await flushCurrentDraftPersist()
  if (activePlatformWorkOrder.value) resetCollectorForm()
  taskPickerOpen.value = true
}

watch(
  () => [form.collector, form.moduleAssetNo, form.note, JSON.stringify(form.dynamicFields)],
  () => {
    if (suspendDraftAutoPersist || !activeGroup.value) return
    scheduleCurrentDraftPersist()
  },
)

watch(selectedTaskId, () => {
  void sendConstructionHeartbeat()
})

watch(activeProjectId, () => {
  void loadPlatformConstructionWorkOrders()
})

onMounted(() => {
  window.addEventListener('message', handleExternalRefresh)
  void loadPlatformProjects()
  void loadTasks()
  void sendConstructionHeartbeat()
  heartbeatTimer = window.setInterval(() => {
    void sendConstructionHeartbeat()
  }, HEARTBEAT_INTERVAL_MS)
})

watch(collectOpen, (open, oldOpen) => {
  if (!open && oldOpen) void flushCurrentDraftPersist()
})

onBeforeUnmount(() => {
  window.removeEventListener('message', handleExternalRefresh)
  window.clearTimeout(draftPersistTimer)
  window.clearInterval(heartbeatTimer)
  void flushCurrentDraftPersist()
  closeScanner()
  clearPreviews()
})
</script>

<template>
  <section class="construction-v24" :class="{ 'is-work-mode': !inTaskPicker, 'is-task-mode': inTaskPicker }">
    <header class="construction-top panel">
      <div>
        <p class="eyebrow">{{ isAdmin ? '施工进度' : '施工采集' }}</p>
        <h2>{{ isAdmin ? '已指派未完成终端' : '已指派终端采集' }}</h2>
        <p class="muted">
          {{
            isAdmin
              ? '查看当前团队已指派施工员且未完成的施工终端；指派与改派仍在任务领取。'
              : '扫码、拍照、本地缓存、上传与提交施工任务；指派请前往任务领取。'
          }}
          <span class="construction-version-inline">V{{ APP_VERSION }}</span>
        </p>
      </div>
      <div class="top-actions">
        <el-tag v-if="offlineMode" type="warning" effect="light">离线包</el-tag>
        <el-button :icon="Refresh" :loading="loadingTasks || loadingGroups || loadingPlatformWorkOrders" @click="loadTasks">刷新</el-button>
        <el-button
          v-if="!isAdmin && groupFilter === 'cached' && cachedTaskDrafts.length"
          type="primary"
          :icon="UploadFilled"
          :loading="uploading"
          :disabled="!readyCachedDrafts.length"
          @click="uploadAllCached"
        >
          上传缓存 {{ readyCachedDrafts.length || '' }}
        </el-button>
      </div>
    </header>

    <el-alert v-if="errorMessage" class="claim-alert" type="error" :closable="false" :title="errorMessage" />

    <div class="construction-workspace" :class="{ 'task-select-mode': inTaskPicker, 'work-mode': !inTaskPicker }">
      <aside v-show="inTaskPicker" class="panel task-panel">
        <div class="panel-head">
          <div>
            <h3>
              {{ taskPickerTitle }}
              <span class="construction-version-inline">V{{ APP_VERSION }}</span>
            </h3>
            <span class="task-picker-subtitle">
              {{ taskPickerSubtitle }}
            </span>
          </div>
          <div class="head-actions">
            <el-tag v-if="offlineMode" type="warning" effect="light">离线包</el-tag>
            <el-tag effect="light">{{ taskPickerCount }}</el-tag>
            <el-button size="small" :icon="Refresh" :loading="loadingTasks || loadingPlatformWorkOrders" @click="loadTasks">刷新</el-button>
            <el-button size="small" class="construction-panel-logout" @click="logoutConstruction">退出</el-button>
          </div>
        </div>
        <div v-loading="loadingTasks" class="task-list">
          <div v-if="taskPickerMode === 'terminal'" class="task-search-row">
            <el-input
              v-model="taskQuery"
              :prefix-icon="Search"
              clearable
              placeholder="输入表号搜索工单"
              @clear="clearTaskSearch"
              @keyup.enter="submitTaskSearch"
            />
            <el-button type="primary" :icon="Search" @click="submitTaskSearch">搜索</el-button>
          </div>

          <article v-if="taskPickerMode === 'terminal' && hasPlatformConstructionEntry" class="field-task-card kind-platform platform-work-order-entry">
            <div class="field-task-title">
              <strong>平台接入工单</strong>
              <el-tag type="success" effect="light">{{ loadingPlatformWorkOrders ? '读取中' : `${platformConstructionTotal} 条` }}</el-tag>
            </div>
            <p>{{ activeProject?.name || activeProjectId }} · {{ platformPrimaryLabel }} / {{ platformAggregateLabel }}</p>
            <div v-if="platformConstructionReworkOrders.length" class="platform-rework-filter">
              <el-checkbox v-model="platformReworkOnly">只看退回返工</el-checkbox>
              <el-tag type="warning" effect="light">{{ platformConstructionReworkOrders.length }} 条返工</el-tag>
            </div>
            <div v-if="platformConstructionDisplayFields.length || platformConstructionFields.length || platformConstructionPhotoSlots.length" class="platform-schema-chips">
              <span v-for="field in platformConstructionDisplayFields" :key="field.key" class="display-field-chip">
                {{ field.label }} · 展示
              </span>
              <div v-if="platformConstructionFieldSections.length" class="platform-schema-sections">
                <section
                  v-for="section in platformConstructionFieldSections"
                  :key="section.id"
                  class="platform-schema-section"
                  :class="`construction-section-${section.id}`"
                >
                  <strong>{{ section.title }}</strong>
                  <small>{{ section.helper }}</small>
                  <span v-for="field in section.fields" :key="field.key">
                    {{ platformFieldRequirement(field) }}
                    <em>{{ fieldRelationRoleLabel(field.relationRole) }}</em>
                  </span>
                </section>
              </div>
              <span v-for="slot in platformConstructionPhotoSlots" :key="slot.key">
                {{ platformFieldRequirement(slot) }}
              </span>
            </div>
            <div v-if="platformConstructionPreview.length" class="platform-work-order-samples">
              <div v-for="order in platformConstructionPreview" :key="order.id">
                <strong>{{ order.primaryValue || order.id }}</strong>
                <span>{{ platformAggregateLabel }} {{ order.aggregateValue || '-' }}</span>
                <el-tag v-if="platformWorkOrderNeedsRework(order)" size="small" type="warning" effect="light">退回返工</el-tag>
                <small v-if="platformWorkOrderNeedsRework(order)" class="platform-rework-note">
                  {{ platformReworkGapSummary(order) }}
                </small>
                <small v-for="field in platformConstructionDisplayFields" :key="`${order.id}-display-${field.key}`">
                  {{ field.label }} {{ platformDisplayFieldValue(order, field) }}
                </small>
                <small v-for="field in platformConstructionFieldsForOrder(order)" :key="`${order.id}-${field.key}`">
                  {{ field.label }} {{ platformWorkOrderFieldValue(order, field) }}
                </small>
                <small v-for="slot in platformConstructionPhotoSlotsForOrder(order)" :key="`${order.id}-slot-${slot.key}`">
                  {{ slot.label }} {{ platformWorkOrderPhotoSlotStatus(order, slot) }}
                </small>
                <small class="platform-kpi-line">{{ platformWorkOrderKpiLine(order) }}</small>
                <el-button size="small" type="primary" plain @click.stop="openPlatformWorkOrder(order)">打开采集</el-button>
              </div>
            </div>
            <el-empty v-if="platformReworkOnly && !platformConstructionPreview.length" description="暂无退回返工" />
            <small>系统外项目接入平台后的施工清单，后续会接入扫码、拍照和提交。</small>
          </article>

          <article
            v-if="taskPickerMode === 'terminal' && !isAdmin && visibleExceptionTaskCards.length"
            class="field-task-card kind-exception field-task-entry"
            role="button"
            tabindex="0"
            @click="selectTaskPickerMode('exception')"
            @keydown.enter.prevent="selectTaskPickerMode('exception')"
            @keydown.space.prevent="selectTaskPickerMode('exception')"
          >
            <div class="field-task-title">
              <strong>异常任务</strong>
              <el-tag type="danger" effect="light">{{ visibleExceptionTaskCards.length }}</el-tag>
            </div>
            <p>管理员派发的异常资料组，进入后只补充缺失或错误的数据。</p>
            <small>点击进入异常工单处理</small>
          </article>

          <div v-if="taskPickerMode === 'exception'" class="field-task-picker-list">
            <article
              v-for="order in visibleExceptionTaskCards"
              :key="order.id"
              class="field-task-card kind-exception"
              role="button"
              tabindex="0"
              @click="openExceptionTaskCard(order)"
              @keydown.enter.prevent="openExceptionTaskCard(order)"
              @keydown.space.prevent="openExceptionTaskCard(order)"
            >
              <div class="field-task-title">
                <strong>{{ order.meterNo || order.groupId || order.id }}</strong>
                <el-tag type="danger" effect="light">{{ order.assignedTo ? `已指派 ${order.assignedTo}` : '待指派' }}</el-tag>
              </div>
              <p>{{ order.terminal || '未绑定终端' }} / {{ order.address || '未填写地址' }}</p>
              <small>{{ order.category || '异常工单' }} {{ order.note || '' }}</small>
              <el-button size="small" type="primary" plain @click.stop="openExceptionTaskCard(order)">进入处理</el-button>
            </article>
            <el-empty v-if="!visibleExceptionTaskCards.length" description="暂无异常任务" />
          </div>

          <div v-if="taskPickerMode === 'unmatched'" class="field-task-picker-list">
            <article
              v-for="record in visibleUnmatchedTaskCards"
              :key="record.unmatchedId"
              class="field-task-card kind-unmatched"
              role="button"
              tabindex="0"
              @click="openUnmatchedTaskCard(record)"
              @keydown.enter.prevent="openUnmatchedTaskCard(record)"
              @keydown.space.prevent="openUnmatchedTaskCard(record)"
            >
              <div class="field-task-title">
                <strong>{{ record.barcode || record.meterNo || record.unmatchedId }}</strong>
                <el-tag type="warning" effect="light">{{ record.assignedTo ? `已指派 ${record.assignedTo}` : '待确认' }}</el-tag>
              </div>
              <p>{{ record.terminal || '未匹配终端' }} / {{ record.address || '未匹配地址' }}</p>
              <small>{{ record.projectOutside ? '项目外施工' : '现场确认' }}</small>
              <el-button size="small" type="primary" plain @click.stop="openUnmatchedTaskCard(record)">进入终端</el-button>
            </article>
            <el-empty v-if="!visibleUnmatchedTaskCards.length" description="暂无未匹配任务" />
          </div>

          <article
            v-if="taskPickerMode === 'terminal'"
            v-for="task in filteredVisibleTasks"
            :key="task.id"
            class="task-card"
            :class="{ active: task.id === selectedTaskId }"
            role="button"
            tabindex="0"
            @click="selectTask(task)"
            @keydown.enter.prevent="selectTask(task)"
            @keydown.space.prevent="selectTask(task)"
          >
            <div class="task-title">
              <strong>终端 {{ task.terminal || task.id }}</strong>
              <el-tag :type="task.constructionClaimedBy || task.assignedConstructor ? 'success' : 'info'" effect="light">
                {{ taskStatus(task) }}
              </el-tag>
            </div>
            <div v-if="submittedTaskQuery && taskMatchedMeterLabel(task)" class="task-meter-hit">
              <span>匹配表号</span>
              <strong>{{ taskMatchedMeterLabel(task) }}</strong>
            </div>
            <div v-if="isAdmin" class="task-assignee">
              <span>施工员</span>
              <strong>{{ taskConstructorDisplayName(task) }}</strong>
              <small v-if="taskConstructorAccountHint(task)">{{ taskConstructorAccountHint(task) }}</small>
            </div>
            <div class="task-metrics">
              <span><em>{{ isAdmin ? '总资料组数' : '改造数' }}</em><strong>{{ task.renovationCount || task.totalGroups || 0 }}</strong></span>
              <span><em>{{ isAdmin ? '已上传/已完成' : '已上传' }}</em><strong>{{ task.constructionUploadedCount || task.uploadedCount || 0 }}</strong></span>
              <button
                v-if="isAdmin"
                type="button"
                class="task-metric-button"
                :disabled="taskUnbuiltCount(task) <= 0"
                @click.stop="openUnbuiltDialog(task)"
                @keydown.stop
              >
                <em>未施工数</em>
                <strong>{{ taskUnbuiltCount(task) }}</strong>
                <small v-if="taskUnbuiltCount(task) > 0">查看清单</small>
              </button>
              <span v-else><em>未施工</em><strong>{{ taskUnbuiltCount(task) }}</strong></span>
              <span><em>{{ isAdmin ? '异常数' : '异常' }}</em><strong>{{ taskExceptionCount(task) }}</strong></span>
            </div>
            <div class="task-progress" :class="{ 'with-label': isAdmin }">
              <span v-if="isAdmin" class="task-progress-label">完成度</span>
              <i :style="{ width: `${taskProgress(task)}%` }" />
              <b>{{ taskProgress(task) }}%</b>
            </div>
            <div v-if="isAdmin" class="task-address">
              <span>代表地址</span>
              <strong>{{ taskRepresentativeAddress(task) }}</strong>
            </div>
          </article>
          <el-empty
            v-if="!loadingTasks && taskPickerMode === 'terminal' && !filteredVisibleTasks.length"
            :description="taskEmptyDescription"
          />
        </div>
      </aside>

      <main v-show="!inTaskPicker" class="panel group-panel">
        <div class="panel-head group-head">
          <div>
            <h3>{{ activePlatformWorkOrder ? '平台接入工单' : selectedTask ? `终端 ${selectedTask.terminal || selectedTask.id}` : '施工区' }}</h3>
          </div>
          <div class="head-actions">
            <el-button size="small" @click="returnToTaskPicker">返回任务区</el-button>
            <el-tag effect="light">{{ activePlatformWorkOrder ? 1 : groupSummary.total }}</el-tag>
            <el-button v-if="!activePlatformWorkOrder" size="small" :icon="Refresh" :loading="loadingGroups" @click="loadGroups">刷新</el-button>
            <el-button
              v-if="canSubmitSelectedTask && !activePlatformWorkOrder"
              size="small"
              type="primary"
              :loading="submittingTask"
              @click="submitSelectedConstructionTask"
            >
              提交施工任务
            </el-button>
            <el-button size="small" class="construction-panel-logout" @click="logoutConstruction">退出</el-button>
          </div>
        </div>

        <div class="panel-body group-body">
          <div class="group-tools">
            <div class="group-search-row">
              <el-input
                v-model="groupQuery"
                :prefix-icon="Search"
                placeholder="同终端内搜表号、地址，如 628 C297"
                clearable
                @keyup.enter="openByMeter(groupQuery)"
              />
              <el-button :icon="Connection" @click="startScanner('quickMeter')">扫表号</el-button>
              <el-button @click="clearGroupSearch">清空</el-button>
            </div>
            <div class="group-filter-tabs" role="tablist" aria-label="施工资料组筛选">
              <button
                v-for="tab in groupFilterTabs"
                :key="tab.value"
                type="button"
                :class="{ active: groupFilter === tab.value }"
                @click="groupFilter = tab.value"
              >
                <span>{{ tab.label }}</span>
                <strong>{{ tab.count }}</strong>
              </button>
            </div>
            <div v-if="selectedTask && groupFilter === 'cached' && cachedTaskDrafts.length" class="cache-inline-actions">
              <span>{{ cachedTaskDrafts.length }} 个本地缓存</span>
              <el-button size="small" type="primary" :loading="uploading" :disabled="!readyCachedDrafts.length" @click="uploadAllCached">
                一键上传
              </el-button>
            </div>
          </div>

          <div v-loading="loadingGroups" class="group-list">
            <article
              v-if="activePlatformWorkOrder && activeGroup"
              class="group-card active"
            >
              <div class="group-main">
                <div class="group-name-row">
                  <strong>{{ activePlatformWorkOrder.primaryValue || activePlatformWorkOrder.id }}</strong>
                  <el-tag :type="platformWorkOrderNeedsRework(activePlatformWorkOrder) ? 'warning' : 'success'" effect="light">
                    {{ platformWorkOrderNeedsRework(activePlatformWorkOrder) ? '退回返工' : (activePlatformWorkOrder.collectionStatus || '待采集') }}
                  </el-tag>
                </div>
                <span>{{ platformAggregateLabel }} {{ activePlatformWorkOrder.aggregateValue || '-' }}</span>
                <small>平台工单 {{ activePlatformWorkOrder.id }}</small>
                <div v-if="platformConstructionDisplayFields.length" class="platform-core-context">
                  <span v-for="field in platformConstructionDisplayFields" :key="field.key">
                    {{ field.label }} {{ platformDisplayFieldValue(activePlatformWorkOrder, field) }}
                  </span>
                </div>
                <small v-if="platformWorkOrderNeedsRework(activePlatformWorkOrder)" class="platform-rework-note">
                  {{ platformReworkGapSummary(activePlatformWorkOrder) }}
                </small>
              </div>
            </article>
            <article
              v-for="item in visibleWorkItems"
              :key="item.key"
              class="group-card"
              :class="{ active: item.key === selectedItemKey, cached: Boolean(item.draft), exception: Boolean(item.order) }"
              @click="openWorkItem(item)"
            >
              <div class="group-main">
                <div class="group-name-row">
                  <strong>{{ item.group.meterNo || item.group.meterMatchKey || item.group.id }}</strong>
                  <el-tag :type="itemBadge(item).type" effect="light">{{ itemBadge(item).label }}</el-tag>
                </div>
                <span>{{ item.group.address || '未填写地址' }}</span>
                <small>终端 {{ item.group.terminal || selectedTask?.terminal || '-' }}</small>
                <small v-if="item.draft" class="cache-line">
                  本地缓存 {{ item.draft.photos?.length || 0 }} 张
                  <template v-if="item.draft.module_asset_no"> / 模块 {{ item.draft.module_asset_no }}</template>
                </small>
                <small v-if="item.order" class="exception-line">
                  {{ item.order.category || '异常工单' }} {{ item.order.note || '' }}
                </small>
              </div>
              <div v-if="item.draft" class="group-card-actions">
                <el-button size="small" type="danger" plain @click.stop="removeCachedDraft(item.draft)">删除缓存</el-button>
              </div>
            </article>
            <el-empty
              v-if="!loadingGroups && selectedTask && !activePlatformWorkOrder && !visibleWorkItems.length"
              description="当前筛选下没有资料组，可切换分类或搜索表号"
            />
            <el-empty v-if="!loadingGroups && !selectedTask && !activePlatformWorkOrder" description="请先选择一个终端任务" />
          </div>
        </div>
      </main>

      <aside v-show="!inTaskPicker" class="panel editor-panel desktop-editor">
        <div class="panel-head">
          <div>
            <h3>采集表单</h3>
            <span>{{ activeGroup ? '选择照片后自动写入本地缓存' : '选择资料组后开始采集' }}</span>
          </div>
          <el-tag v-if="activeGroup" type="info" effect="light">{{ online() ? '在线' : '离线' }}</el-tag>
        </div>

        <div class="editor-body">
          <div v-if="!activeGroup" class="editor-empty">
            <strong>选择资料组后开始采集</strong>
            <span>可先拍照缓存，恢复网络后统一上传。</span>
          </div>

          <div v-else class="collector-sheet collector-sheet-inline">
            <header class="sheet-head">
              <div>
                <p class="eyebrow">{{ activePlatformWorkOrder ? '平台接入采集' : activeOrder ? '异常工单处理' : '施工采集单' }}</p>
                <h3>{{ activeGroup.meterNo || activeGroup.id }}</h3>
                <span>{{ activeGroup.terminal || selectedTask?.terminal || '-' }} / {{ activeGroup.address || '未填写地址' }}</span>
              </div>
              <el-tag
                v-if="activePlatformWorkOrder"
                :type="platformWorkOrderNeedsRework(activePlatformWorkOrder) ? 'warning' : 'success'"
                effect="light"
              >
                {{ platformWorkOrderNeedsRework(activePlatformWorkOrder) ? '退回返工' : (activePlatformWorkOrder.collectionStatus || '待采集') }}
              </el-tag>
              <el-tag v-if="activeOrder" type="danger" effect="light">{{ activeOrder.category || '异常' }}</el-tag>
            </header>

            <div v-if="activeOrder?.note" class="exception-note">
              {{ activeOrder.note }}
            </div>
            <div v-if="platformWorkOrderNeedsRework(activePlatformWorkOrder)" class="platform-rework-note platform-rework-note-panel">
              {{ platformReworkGapSummary(activePlatformWorkOrder) }}
            </div>
            <div v-if="platformReworkEvidenceGapGroups.length" class="platform-rework-gap-panel">
              <strong>退回补采清单</strong>
              <span v-for="group in platformReworkEvidenceGapGroups" :key="group.label">
                <em>{{ group.label }}</em>
                {{ group.items.join('、') }}
              </span>
            </div>

            <div class="readonly-grid">
              <div>
                <span>表号</span>
                <strong>{{ activeGroup.meterNo || '-' }}</strong>
              </div>
              <div>
                <span>终端</span>
                <strong>{{ activeGroup.terminal || selectedTask?.terminal || '-' }}</strong>
              </div>
              <div class="wide">
                <span>地址</span>
                <strong>{{ activeGroup.address || '-' }}</strong>
              </div>
            </div>

            <section v-if="siteChecklistItems.length" class="site-checklist-panel">
              <div class="site-checklist-head">
                <div>
                  <strong>施工必采清单</strong>
                  <span>字段配置同步，按当前项目字段提醒现场补齐。</span>
                </div>
                <el-tag :type="siteChecklistSummary.missing ? 'warning' : 'success'" effect="light">
                  {{ siteChecklistSummary.done }}/{{ siteChecklistSummary.total }} 已完成
                </el-tag>
              </div>
              <div class="site-checklist-grid">
                <article
                  v-for="item in siteChecklistItems"
                  :key="item.key"
                  :class="{ done: item.done, required: item.required }"
                >
                  <div>
                    <el-tag size="small" effect="plain">{{ checklistGroupLabel(item.group) }}</el-tag>
                    <el-tag size="small" :type="checklistStatusType(item)" effect="light">
                      {{ checklistStatusLabel(item) }}
                    </el-tag>
                    <el-tag class="construction-intent-tag" size="small" :type="item.intentType" effect="light" title="施工采集意图">
                      {{ item.intentLabel }}
                    </el-tag>
                  </div>
                  <strong>{{ item.label }}</strong>
                  <small>{{ item.method }}<template v-if="item.required"> · 必填</template></small>
                  <span>{{ item.value }}</span>
                </article>
              </div>
              <small v-if="siteChecklistSummary.missing">
                还有 {{ siteChecklistSummary.missing }} 项必填资料待补齐，补齐后才能提交。
              </small>
            </section>

            <div v-if="hasConfiguredConstructionFields" class="construction-section-list">
              <section
              v-for="section in activeConstructionFieldSections"
                :key="section.id"
                class="construction-section"
                :class="`construction-section-${section.id}`"
              >
                <div class="construction-section-head">
                  <div>
                    <strong>{{ section.title }}</strong>
                    <span>{{ section.helper }}</span>
                  </div>
                  <el-tag size="small" effect="plain">{{ section.fields.length }} 项</el-tag>
                </div>
                <div class="field-grid">
                  <label v-for="field in section.fields" :key="field.key">
                    <span>
                      {{ field.label }} <b v-if="isFieldRequired(field)">*</b>
                      <el-tag class="construction-role-tag" size="small" effect="plain">
                        {{ fieldRelationRoleLabel(field.relationRole) }}
                      </el-tag>
                      <el-tag class="construction-intent-tag" size="small" :type="constructionCollectionIntentType(field)" effect="light" title="施工采集意图">
                        {{ constructionCollectionIntentLabel(field) }}
                      </el-tag>
                    </span>
                    <small v-if="field.requiredWhen?.fieldKey" class="construction-condition-hint">
                      {{ constructionConditionLabel(field) }}
                    </small>
                    <div class="field-with-action">
                      <el-select
                        v-if="shouldUseFieldSelect(field)"
                        :model-value="fieldValue(field)"
                        :placeholder="fieldPlaceholder(field)"
                        clearable
                        @change="(value: string) => { setFieldValue(field, String(value)); scheduleCurrentDraftPersist(); saveCurrentDraft({ silent: true }) }"
                      >
                        <el-option
                          v-for="option in fieldSelectOptions(field)"
                          :key="option"
                          :label="option"
                          :value="option"
                        />
                      </el-select>
                      <el-input
                        v-else
                        :model-value="fieldValue(field)"
                        :type="fieldInputType(field)"
                        :placeholder="fieldPlaceholder(field)"
                        clearable
                        @update:model-value="(value: string | number) => { setFieldValue(field, String(value)); scheduleCurrentDraftPersist() }"
                        @change="saveCurrentDraft({ silent: true })"
                      />
                      <el-button v-if="shouldShowScanButton(field)" :icon="Connection" @click="startDynamicScanner(field)">扫码</el-button>
                    </div>
                  </label>
                </div>
              </section>
            </div>
            <div v-else class="field-grid">
                <label>
                  <span>采集器</span>
                  <div class="field-with-action">
                    <el-input
                      v-model="form.collector"
                      placeholder="扫码或手填采集器号"
                      clearable
                      @input="scheduleCurrentDraftPersist"
                      @change="saveCurrentDraft({ silent: true })"
                    />
                    <el-button :icon="Connection" @click="startScanner('collector')">扫码</el-button>
                  </div>
                </label>
                <label>
                  <span>模块资产编号 <b>*</b></span>
                  <div class="field-with-action">
                    <el-input
                      v-model="form.moduleAssetNo"
                      placeholder="必填，可扫码或手填"
                      clearable
                      @input="scheduleCurrentDraftPersist"
                      @change="saveCurrentDraft({ silent: true })"
                    />
                    <el-button :icon="Connection" @click="startScanner('module')">扫码</el-button>
                  </div>
                </label>
            </div>

            <section v-if="activePlatformWorkOrder" class="platform-kpi-panel">
              <div class="platform-kpi-panel-head">
                <strong>KPI 必备资料</strong>
                <span>安装人员自动取当前账号，时间和在线时长用于效率计算</span>
              </div>
              <div class="platform-kpi-inputs">
                <label v-for="field in platformKpiInputFields" :key="field.key">
                  <span>{{ field.label }} <b v-if="field.required">*</b></span>
                  <el-input
                    :model-value="fieldValue(field)"
                    :type="fieldInputType(field)"
                    :placeholder="fieldPlaceholder(field)"
                    clearable
                    @update:model-value="(value: string | number) => { setFieldValue(field, String(value)); scheduleCurrentDraftPersist() }"
                    @change="saveCurrentDraft({ silent: true })"
                  />
                </label>
              </div>
              <div class="platform-kpi-status">
                <span v-for="item in activePlatformKpiItems" :key="item.key">
                  {{ item.label }} {{ item.value }}
                </span>
              </div>
            </section>

            <el-input
              v-if="activeOrder"
              v-model="form.note"
              type="textarea"
              :rows="2"
              placeholder="异常处理说明"
              @input="scheduleCurrentDraftPersist"
              @change="saveCurrentDraft({ silent: true })"
            />

            <section v-if="activeExistingPhotos.length" class="existing-photos">
              <div class="existing-head">
                <strong>已上传照片</strong>
                <span>{{ activeExistingPhotos.length }} 张，已有对应槽位时无需重复上传</span>
              </div>
              <div class="existing-list">
                <img
                  v-for="photo in activeExistingPhotos"
                  :key="photo.id"
                  :src="photoUrl(photo)"
                  :alt="photo.categoryLabel || photo.name || '已上传照片'"
                  loading="lazy"
                  decoding="async"
                />
              </div>
            </section>

            <section
              v-for="photoSection in activeConstructionPhotoSections"
              :key="photoSection.id"
              class="construction-photo-section"
            >
              <div class="construction-section-head">
                <div>
                  <strong>{{ photoSection.title }}</strong>
                  <span>{{ photoSection.helper }}</span>
                </div>
                <el-tag size="small" effect="plain">{{ photoSection.slots.length }} 张</el-tag>
              </div>
              <div class="slot-grid">
                <article v-for="(slot, index) in photoSection.slots" :key="slot.key" class="photo-slot">
                  <div class="slot-title">
                    <strong>{{ index + 1 }}. {{ slot.label }} <b v-if="isPhotoSlotRequired(slot)">*</b></strong>
                    <el-tag class="construction-role-tag" size="small" effect="plain">
                      {{ fieldRelationRoleLabel(slot.relationRole) }}
                    </el-tag>
                    <el-tag class="construction-intent-tag" size="small" :type="constructionCollectionIntentType(slot)" effect="light" title="施工采集意图">
                      {{ constructionCollectionIntentLabel(slot) }}
                    </el-tag>
                    <el-tag v-if="existingPhotoForSlot(activeGroup, slot.key) && !selectedFiles[slot.key]" size="small" type="success" effect="light">
                      系统已有
                    </el-tag>
                    <el-tag v-if="selectedFiles[slot.key]" size="small" type="warning" effect="light">本地待传</el-tag>
                  </div>

                  <div class="slot-preview" :class="{ empty: !previewUrls[slot.key] && !photoUrl(existingPhotoForSlot(activeGroup, slot.key)) }">
                    <img
                      v-if="previewUrls[slot.key] || photoUrl(existingPhotoForSlot(activeGroup, slot.key))"
                      :src="previewUrls[slot.key] || photoUrl(existingPhotoForSlot(activeGroup, slot.key))"
                      alt=""
                      loading="lazy"
                      decoding="async"
                    />
                    <div v-else>
                      <el-icon><Picture /></el-icon>
                      <span>{{ isPhotoSlotRequired(slot) ? '必填照片' : '可选照片' }}</span>
                    </div>
                  </div>
                  <div v-if="existingPhotoForSlot(activeGroup, slot.key) && !selectedFiles[slot.key]" class="slot-note">
                    已存在对应照片，无需重复上传；如需替换可重新拍照或从相册选择。
                  </div>

                  <div class="slot-actions">
                    <el-button :icon="Camera" :loading="slotBusy[slot.key]" @click="triggerPhotoInput(slot.key, 'camera')">拍照</el-button>
                    <el-button :icon="FolderOpened" @click="triggerPhotoInput(slot.key, 'album')">相册</el-button>
                  </div>
                  <input
                    :ref="(el) => setFileInput(slot.key, 'camera', el, 'inline')"
                    class="file-input"
                    type="file"
                    accept="image/*"
                    capture="environment"
                    @change="pickFile(slot.key, $event)"
                  />
                  <input
                    :ref="(el) => setFileInput(slot.key, 'album', el, 'inline')"
                    class="file-input"
                    type="file"
                    accept="image/*"
                    @change="pickFile(slot.key, $event)"
                  />
                </article>
              </div>
            </section>

            <div
              v-if="constructionSubmitGapGroups.length"
              class="sheet-warning construction-submit-gap"
            >
              <strong>施工提交缺口</strong>
              <span v-for="group in constructionSubmitGapGroups" :key="group.label">{{ group.label }}：{{ group.items.join('、') }}</span>
            </div>

            <footer class="sheet-actions">
              <span class="draft-status">{{ Object.values(selectedFiles).filter(Boolean).length }} 张本地待上传</span>
              <el-button v-if="activePlatformWorkOrder" size="large" type="primary" :loading="cacheBusy" @click="savePlatformCollectionDraft('cached')">
                保存平台草稿
              </el-button>
              <el-button
                v-if="activePlatformWorkOrder"
                size="large"
                :loading="cacheBusy"
                :disabled="constructionSubmitBlocked"
                @click="savePlatformCollectionDraft('submitted')"
              >
                提交元数据
              </el-button>
              <el-button v-if="activeCachedDraft && !activePlatformWorkOrder" size="large" type="danger" plain @click="removeCachedDraft(activeCachedDraft)">删除缓存</el-button>
              <el-button v-if="!activePlatformWorkOrder" size="large" :loading="cacheBusy" @click="saveCurrentDraft()">保存缓存</el-button>
              <el-button v-if="canShowCurrentUpload && !activePlatformWorkOrder" size="large" type="primary" :loading="uploading" :disabled="!canUploadCurrent" @click="uploadCurrentDraft">
                上传当前组
              </el-button>
            </footer>
          </div>
        </div>
      </aside>
    </div>

    <el-dialog
      v-model="unbuiltDialogOpen"
      class="unbuilt-dialog"
      :title="unbuiltDialogTitle"
      width="760px"
      append-to-body
    >
      <div v-loading="unbuiltDialogLoading" class="unbuilt-dialog-body">
        <div v-if="unbuiltDialogTask" class="unbuilt-dialog-summary">
          <div>
            <span>施工员</span>
            <strong>{{ taskConstructorDisplayName(unbuiltDialogTask) }}</strong>
          </div>
          <div>
            <span>完成度</span>
            <strong>{{ taskProgress(unbuiltDialogTask) }}%</strong>
          </div>
          <div>
            <span>未施工</span>
            <strong>{{ unbuiltDialogGroups.length }}</strong>
          </div>
        </div>
        <el-input
          v-model="unbuiltDialogQuery"
          :prefix-icon="Search"
          placeholder="搜索表号、地址、终端"
          clearable
        />
        <el-alert
          v-if="unbuiltDialogError"
          type="error"
          :title="unbuiltDialogError"
          show-icon
          :closable="false"
        />
        <div class="unbuilt-dialog-list">
          <article v-for="group in filteredUnbuiltDialogGroups" :key="group.id" class="unbuilt-row">
            <div>
              <strong>{{ group.meterNo || group.meterMatchKey || group.id }}</strong>
              <span>{{ group.address || '未填写地址' }}</span>
            </div>
            <small>终端 {{ group.terminal || unbuiltDialogTask?.terminal || '-' }}</small>
          </article>
          <el-empty
            v-if="!unbuiltDialogLoading && !filteredUnbuiltDialogGroups.length"
            description="暂无未施工清单"
          />
        </div>
      </div>
      <template #footer>
        <el-button :loading="unbuiltDialogLoading" @click="reloadUnbuiltDialog">刷新</el-button>
        <el-button type="primary" @click="unbuiltDialogOpen = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="collectOpen" class="construction-drawer" size="92%" direction="btt" :with-header="false" destroy-on-close>
      <div class="collector-sheet" v-if="activeGroup">
        <header class="sheet-head">
          <div>
            <p class="eyebrow">{{ activeOrder ? '异常工单处理' : '施工采集单' }}</p>
            <h3>{{ activeGroup.meterNo || activeGroup.id }}</h3>
            <span>{{ activeGroup.terminal || selectedTask?.terminal || '-' }} / {{ activeGroup.address || '未填写地址' }}</span>
          </div>
          <div class="sheet-head-actions">
            <el-tag v-if="activeOrder" type="danger" effect="light">{{ activeOrder.category || '异常' }}</el-tag>
            <el-button class="sheet-close" :icon="Close" circle aria-label="关闭采集单" @click="collectOpen = false" />
          </div>
        </header>

        <div v-if="activeOrder?.note" class="exception-note">
          {{ activeOrder.note }}
        </div>

        <div class="readonly-grid">
          <div>
            <span>表号</span>
            <strong>{{ activeGroup.meterNo || '-' }}</strong>
          </div>
          <div>
            <span>终端</span>
            <strong>{{ activeGroup.terminal || selectedTask?.terminal || '-' }}</strong>
          </div>
          <div class="wide">
            <span>地址</span>
            <strong>{{ activeGroup.address || '-' }}</strong>
          </div>
        </div>

        <section v-if="siteChecklistItems.length" class="site-checklist-panel">
          <div class="site-checklist-head">
            <div>
              <strong>施工必采清单</strong>
              <span>字段配置同步，按当前项目字段提醒现场补齐。</span>
            </div>
            <el-tag :type="siteChecklistSummary.missing ? 'warning' : 'success'" effect="light">
              {{ siteChecklistSummary.done }}/{{ siteChecklistSummary.total }} 已完成
            </el-tag>
          </div>
          <div class="site-checklist-grid">
            <article
              v-for="item in siteChecklistItems"
              :key="item.key"
              :class="{ done: item.done, required: item.required }"
            >
              <div>
                <el-tag size="small" effect="plain">{{ checklistGroupLabel(item.group) }}</el-tag>
                <el-tag size="small" :type="checklistStatusType(item)" effect="light">
                  {{ checklistStatusLabel(item) }}
                </el-tag>
                <el-tag class="construction-intent-tag" size="small" :type="item.intentType" effect="light" title="施工采集意图">
                  {{ item.intentLabel }}
                </el-tag>
              </div>
              <strong>{{ item.label }}</strong>
              <small>{{ item.method }}<template v-if="item.required"> · 必填</template></small>
              <span>{{ item.value }}</span>
            </article>
          </div>
          <small v-if="siteChecklistSummary.missing">
            还有 {{ siteChecklistSummary.missing }} 项必填资料待补齐，补齐后才能提交。
          </small>
        </section>

        <div v-if="hasConfiguredConstructionFields" class="construction-section-list">
          <section
            v-for="section in activeConstructionFieldSections"
            :key="section.id"
            class="construction-section"
            :class="`construction-section-${section.id}`"
          >
            <div class="construction-section-head">
              <div>
                <strong>{{ section.title }}</strong>
                <span>{{ section.helper }}</span>
              </div>
              <el-tag size="small" effect="plain">{{ section.fields.length }} 项</el-tag>
            </div>
            <div class="field-grid">
              <label v-for="field in section.fields" :key="field.key">
                <span>
                  {{ field.label }} <b v-if="isFieldRequired(field)">*</b>
                  <el-tag class="construction-role-tag" size="small" effect="plain">
                    {{ fieldRelationRoleLabel(field.relationRole) }}
                  </el-tag>
                  <el-tag class="construction-intent-tag" size="small" :type="constructionCollectionIntentType(field)" effect="light" title="施工采集意图">
                    {{ constructionCollectionIntentLabel(field) }}
                  </el-tag>
                </span>
                <small v-if="field.requiredWhen?.fieldKey" class="construction-condition-hint">
                  {{ constructionConditionLabel(field) }}
                </small>
                <div class="field-with-action">
                  <el-select
                    v-if="shouldUseFieldSelect(field)"
                    :model-value="fieldValue(field)"
                    :placeholder="fieldPlaceholder(field)"
                    clearable
                    @change="(value: string) => { setFieldValue(field, String(value)); scheduleCurrentDraftPersist(); saveCurrentDraft({ silent: true }) }"
                  >
                    <el-option
                      v-for="option in fieldSelectOptions(field)"
                      :key="option"
                      :label="option"
                      :value="option"
                    />
                  </el-select>
                  <el-input
                    v-else
                    :model-value="fieldValue(field)"
                    :type="fieldInputType(field)"
                    :placeholder="fieldPlaceholder(field)"
                    clearable
                    @update:model-value="(value: string | number) => { setFieldValue(field, String(value)); scheduleCurrentDraftPersist() }"
                    @change="saveCurrentDraft({ silent: true })"
                  />
                  <el-button v-if="shouldShowScanButton(field)" :icon="Connection" @click="startDynamicScanner(field)">扫码</el-button>
                </div>
              </label>
            </div>
          </section>
        </div>
        <div v-else class="field-grid">
            <label>
              <span>采集器</span>
              <div class="field-with-action">
                <el-input
                  v-model="form.collector"
                  placeholder="扫码或手填采集器号"
                  clearable
                  @input="scheduleCurrentDraftPersist"
                  @change="saveCurrentDraft({ silent: true })"
                />
                <el-button :icon="Connection" @click="startScanner('collector')">扫码</el-button>
              </div>
            </label>
            <label>
              <span>模块资产编号 <b>*</b></span>
              <div class="field-with-action">
                <el-input
                  v-model="form.moduleAssetNo"
                  placeholder="必填，可扫码或手填"
                  clearable
                  @input="scheduleCurrentDraftPersist"
                  @change="saveCurrentDraft({ silent: true })"
                />
                <el-button :icon="Connection" @click="startScanner('module')">扫码</el-button>
              </div>
            </label>
        </div>

        <section v-if="activePlatformWorkOrder" class="platform-kpi-panel">
          <div class="platform-kpi-panel-head">
            <strong>KPI 必备资料</strong>
            <span>安装人员自动取当前账号，时间和在线时长用于效率计算</span>
          </div>
          <div class="platform-kpi-inputs">
            <label v-for="field in platformKpiInputFields" :key="field.key">
              <span>{{ field.label }} <b v-if="field.required">*</b></span>
              <el-input
                :model-value="fieldValue(field)"
                :type="fieldInputType(field)"
                :placeholder="fieldPlaceholder(field)"
                clearable
                @update:model-value="(value: string | number) => { setFieldValue(field, String(value)); scheduleCurrentDraftPersist() }"
                @change="saveCurrentDraft({ silent: true })"
              />
            </label>
          </div>
          <div class="platform-kpi-status">
            <span v-for="item in activePlatformKpiItems" :key="item.key">
              {{ item.label }} {{ item.value }}
            </span>
          </div>
        </section>

        <el-input
          v-if="activeOrder"
          v-model="form.note"
          type="textarea"
          :rows="2"
          placeholder="异常处理说明"
          @input="scheduleCurrentDraftPersist"
          @change="saveCurrentDraft({ silent: true })"
        />

        <section v-if="activeExistingPhotos.length" class="existing-photos">
          <div class="existing-head">
            <strong>已上传照片</strong>
            <span>{{ activeExistingPhotos.length }} 张，已有对应槽位时无需重复上传</span>
          </div>
          <div class="existing-list">
            <img
              v-for="photo in activeExistingPhotos"
              :key="photo.id"
              :src="photoUrl(photo)"
              :alt="photo.categoryLabel || photo.name || '已上传照片'"
              loading="lazy"
              decoding="async"
            />
          </div>
        </section>

        <section
          v-for="photoSection in activeConstructionPhotoSections"
          :key="photoSection.id"
          class="construction-photo-section"
        >
          <div class="construction-section-head">
            <div>
              <strong>{{ photoSection.title }}</strong>
              <span>{{ photoSection.helper }}</span>
            </div>
            <el-tag size="small" effect="plain">{{ photoSection.slots.length }} 张</el-tag>
          </div>
          <div class="slot-grid">
            <article v-for="(slot, index) in photoSection.slots" :key="slot.key" class="photo-slot">
              <div class="slot-title">
                <strong>{{ index + 1 }}. {{ slot.label }} <b v-if="isPhotoSlotRequired(slot)">*</b></strong>
                <el-tag class="construction-role-tag" size="small" effect="plain">
                  {{ fieldRelationRoleLabel(slot.relationRole) }}
                </el-tag>
                <el-tag class="construction-intent-tag" size="small" :type="constructionCollectionIntentType(slot)" effect="light" title="施工采集意图">
                  {{ constructionCollectionIntentLabel(slot) }}
                </el-tag>
                <el-tag v-if="existingPhotoForSlot(activeGroup, slot.key) && !selectedFiles[slot.key]" size="small" type="success" effect="light">
                  系统已有
                </el-tag>
                <el-tag v-if="selectedFiles[slot.key]" size="small" type="warning" effect="light">本地待传</el-tag>
              </div>

              <div class="slot-preview" :class="{ empty: !previewUrls[slot.key] && !photoUrl(existingPhotoForSlot(activeGroup, slot.key)) }">
                <img
                  v-if="previewUrls[slot.key] || photoUrl(existingPhotoForSlot(activeGroup, slot.key))"
                  :src="previewUrls[slot.key] || photoUrl(existingPhotoForSlot(activeGroup, slot.key))"
                  alt=""
                  loading="lazy"
                  decoding="async"
                />
                <div v-else>
                  <el-icon><Picture /></el-icon>
                  <span>{{ isPhotoSlotRequired(slot) ? '必填照片' : '可选照片' }}</span>
                </div>
              </div>
              <div v-if="existingPhotoForSlot(activeGroup, slot.key) && !selectedFiles[slot.key]" class="slot-note">
                已存在对应照片，无需重复上传；如需替换可重新拍照或从相册选择。
              </div>

              <div class="slot-actions">
                <el-button :icon="Camera" :loading="slotBusy[slot.key]" @click="triggerPhotoInput(slot.key, 'camera')">拍照</el-button>
                <el-button :icon="FolderOpened" @click="triggerPhotoInput(slot.key, 'album')">相册</el-button>
              </div>
              <input
                :ref="(el) => setFileInput(slot.key, 'camera', el, 'drawer')"
                class="file-input"
                type="file"
                accept="image/*"
                capture="environment"
                @change="pickFile(slot.key, $event)"
              />
              <input
                :ref="(el) => setFileInput(slot.key, 'album', el, 'drawer')"
                class="file-input"
                type="file"
                accept="image/*"
                @change="pickFile(slot.key, $event)"
              />
            </article>
          </div>
        </section>

        <div
          v-if="constructionSubmitGapGroups.length"
          class="sheet-warning construction-submit-gap"
        >
          <strong>施工提交缺口</strong>
          <span v-for="group in constructionSubmitGapGroups" :key="group.label">{{ group.label }}：{{ group.items.join('、') }}</span>
        </div>

        <footer class="sheet-actions">
          <span class="draft-status">{{ Object.values(selectedFiles).filter(Boolean).length }} 张本地待上传</span>
          <el-button v-if="activePlatformWorkOrder" size="large" type="primary" :loading="cacheBusy" @click="savePlatformCollectionDraft('cached')">
            保存平台草稿
          </el-button>
          <el-button
            v-if="activePlatformWorkOrder"
            size="large"
            :loading="cacheBusy"
            :disabled="constructionSubmitBlocked"
            @click="savePlatformCollectionDraft('submitted')"
          >
            提交元数据
          </el-button>
          <el-button v-if="activeCachedDraft && !activePlatformWorkOrder" size="large" type="danger" plain @click="removeCachedDraft(activeCachedDraft)">删除缓存</el-button>
          <el-button v-if="!activePlatformWorkOrder" size="large" :loading="cacheBusy" @click="saveCurrentDraft()">保存缓存</el-button>
          <el-button v-if="canShowCurrentUpload && !activePlatformWorkOrder" size="large" type="primary" :loading="uploading" :disabled="!canUploadCurrent" @click="uploadCurrentDraft">
            上传当前组
          </el-button>
        </footer>
      </div>
    </el-drawer>

    <div v-if="scannerOpen" class="scanner-backdrop">
      <section class="scanner-panel">
        <header class="scanner-head">
          <div>
            <strong>{{ scannerTitle }}</strong>
            <span>{{ scannerStatus }}</span>
          </div>
          <el-button :icon="Close" circle @click="closeScanner" />
        </header>
        <div ref="scannerCamera" class="scanner-camera">
          <video ref="scannerVideo" class="scanner-video" playsinline muted />
          <div class="scan-frame" aria-hidden="true" />
          <p>{{ scannerHint }}</p>
        </div>
        <input ref="scannerFileInput" class="file-input" type="file" accept="image/*" capture="environment" />
        <footer class="scanner-actions">
          <el-button @click="fallbackScannerInput('手动拍照识别')">拍照识别</el-button>
          <el-button type="primary" @click="manualScannerInput()">手动输入</el-button>
        </footer>
      </section>
    </div>
  </section>
</template>

<style scoped>
.construction-v24 {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: calc(100dvh - var(--v2-header-height, 64px) - 20px);
  overflow: hidden;
}

.construction-v24.is-work-mode {
  height: calc(100dvh - var(--v2-header-height, 64px) - 20px);
}

.construction-v24.is-task-mode {
  justify-content: start;
}

.panel {
  border: 1px solid var(--v2-border, #d7e0ea);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 14px 36px rgba(18, 38, 63, 0.06);
}

.construction-top {
  display: none;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
}

.eyebrow {
  margin: 0 0 4px;
  color: #0f7f95;
  font-size: 12px;
  font-weight: 700;
}

.construction-top h2,
.panel-head h3,
.sheet-head h3 {
  margin: 0;
  color: #111827;
  font-size: 20px;
  font-weight: 800;
  letter-spacing: 0;
}

.construction-top h2 {
  font-size: 17px;
}

.muted,
.panel-head span,
.sheet-head span,
.task-meta,
.group-main small {
  color: #667085;
}

.muted {
  line-height: 1.55;
  overflow-wrap: anywhere;
  text-overflow: clip;
  white-space: normal;
  word-break: break-word;
}

.construction-version-inline {
  display: inline-block;
  margin-left: 8px;
  color: #98a2b3;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.2;
  white-space: nowrap;
}

.panel-head h3 .construction-version-inline {
  display: inline-block;
  color: #98a2b3;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.2;
  vertical-align: 1px;
  white-space: nowrap;
}

.top-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.construction-workspace {
  display: grid;
  grid-template-columns: minmax(340px, 460px) minmax(0, 1fr);
  gap: 10px;
  flex: 1;
  min-height: 0;
}

.construction-workspace.task-select-mode {
  grid-template-columns: minmax(280px, 560px);
  align-items: start;
  align-content: start;
  justify-content: center;
  padding-top: 6px;
}

.construction-workspace.work-mode {
  grid-template-columns: minmax(360px, 520px) minmax(0, 1fr);
  align-items: stretch;
  height: 100%;
  min-height: 0;
}

.task-panel,
.group-panel,
.editor-panel {
  min-width: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-height: 0;
  overflow: hidden;
}

.construction-workspace.work-mode .group-panel,
.construction-workspace.work-mode .editor-panel {
  height: 100%;
  min-height: 0;
}

.construction-workspace.task-select-mode .task-panel {
  max-height: calc(100dvh - var(--v2-header-height, 64px) - 42px);
}

.panel-head {
  min-height: 52px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-bottom: 1px solid #e6edf3;
  background: linear-gradient(180deg, #fff, #f7fafc);
}

.head-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.panel-head h3 {
  font-size: 16px;
}

.task-list,
.group-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow: auto;
  padding: 10px;
}

.task-list {
  min-height: 0;
  max-height: none;
}

.task-search-row {
  position: sticky;
  top: 0;
  z-index: 2;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 2px 0 6px;
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(8px);
}

.task-meter-hit {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 9px;
  border: 1px solid #b7d7f8;
  border-radius: 9px;
  background: #f4f9ff;
  color: #0b5cab;
}

.task-meter-hit span {
  font-size: 12px;
  color: #4d6b88;
}

.task-meter-hit strong {
  min-width: 0;
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.field-task-picker-list {
  display: grid;
  gap: 8px;
}

.field-task-card {
  display: grid;
  gap: 7px;
  padding: 10px;
  border: 1px solid #d9e4ee;
  border-left: 4px solid transparent;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.18s ease;
}

.field-task-card:hover,
.field-task-card:focus-visible {
  border-color: #9ccfe0;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08);
  outline: none;
  transform: translateY(-1px);
}

.field-task-card.kind-exception {
  border-left-color: #b42318;
}

.field-task-card.kind-unmatched {
  border-left-color: #d97706;
}

.field-task-entry {
  margin-bottom: 4px;
}

.field-task-entry .el-tag,
.field-task-title .el-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}

.field-task-title {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.field-task-title strong,
.field-task-card p,
.field-task-card small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.field-task-card p {
  margin: 0;
  color: #475467;
  font-size: 13px;
}

.field-task-card small {
  color: #667085;
  font-size: 12px;
}

.construction-panel-logout {
  color: #334155;
}

.group-list {
  min-height: 0;
  max-height: none;
  overscroll-behavior: contain;
  scrollbar-width: thin;
}

.group-body {
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  overflow: hidden;
  padding: 0;
}

.editor-panel {
  min-height: 0;
}

.editor-body {
  min-height: 0;
  overflow: auto;
  padding: 10px;
}

.editor-empty {
  min-height: 260px;
  display: grid;
  align-content: center;
  justify-items: center;
  gap: 8px;
  margin: 12px;
  border: 1px dashed #c7d4e1;
  border-radius: 12px;
  background: linear-gradient(180deg, #fff, #f7fafc);
  color: #667085;
  text-align: center;
}

.editor-empty strong {
  color: #111827;
  font-size: 16px;
}

.task-card,
.group-card {
  width: 100%;
  border: 1px solid #d9e4ee;
  border-radius: 10px;
  background: #fff;
  color: #111827;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease,
    transform 0.15s ease;
}

.task-card {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 12px;
}

.task-card:hover,
.group-card:hover,
.task-card.active,
.group-card.active {
  border-color: #0f7f95;
  box-shadow: 0 14px 32px rgba(15, 127, 149, 0.12);
}

.task-card.active,
.group-card.active {
  background: #f4fbfd;
}

.task-title,
.group-head,
.group-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.task-title strong,
.group-main strong {
  color: #111827;
  font-size: 16px;
  font-weight: 800;
}

.task-assignee,
.task-address {
  display: grid;
  min-width: 0;
  gap: 3px;
  border: 1px solid rgba(15, 127, 149, 0.12);
  border-radius: 10px;
  background: rgba(232, 246, 250, 0.52);
  padding: 9px 10px;
}

.task-assignee span,
.task-address span,
.task-progress-label {
  color: #667085;
  font-size: 12px;
  font-weight: 760;
  line-height: 1.2;
}

.task-assignee strong,
.task-address strong {
  min-width: 0;
  color: #111827;
  font-size: 14px;
  font-weight: 820;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.task-assignee small {
  min-width: 0;
  color: #667085;
  font-size: 12px;
  line-height: 1.25;
  overflow-wrap: anywhere;
}

.task-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
}

.task-metrics span,
.task-metric-button {
  min-width: 0;
  border: 0;
  border-radius: 9px;
  background: #f7fafc;
  padding: 8px;
  text-align: left;
}

.task-metric-button {
  width: 100%;
  color: inherit;
  font: inherit;
  cursor: pointer;
  transition:
    background 0.15s ease,
    box-shadow 0.15s ease;
}

.task-metric-button:not(:disabled):hover,
.task-metric-button:not(:disabled):focus-visible {
  outline: none;
  background: #e8f6fa;
  box-shadow: inset 0 0 0 1px rgba(15, 127, 149, 0.24);
}

.task-metric-button:disabled {
  cursor: default;
  opacity: 0.65;
}

.task-metric-button small {
  display: block;
  margin-top: 3px;
  color: #0f7f95;
  font-size: 11px;
  font-weight: 800;
  line-height: 1.2;
}

.task-metrics em {
  display: block;
  color: #667085;
  font-size: 12px;
  font-style: normal;
  line-height: 1.2;
}

.task-metrics strong {
  display: block;
  margin-top: 3px;
  color: #111827;
  font-size: 18px;
  font-weight: 900;
}

.task-progress {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
}

.task-progress.with-label {
  grid-template-columns: auto minmax(0, 1fr) auto;
}

.task-progress::before {
  content: "";
  grid-column: 1;
  grid-row: 1;
  height: 7px;
  border-radius: 999px;
  background: #e6edf3;
}

.task-progress i {
  grid-column: 1;
  grid-row: 1;
  height: 7px;
  max-width: 100%;
  border-radius: 999px;
  background: #0f7f95;
}

.task-progress.with-label::before,
.task-progress.with-label i {
  grid-column: 2;
}

.task-progress b {
  color: #667085;
  font-size: 12px;
}

:deep(.unbuilt-dialog) {
  max-width: calc(100vw - 24px);
}

.unbuilt-dialog-body {
  display: grid;
  gap: 12px;
}

.unbuilt-dialog-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.unbuilt-dialog-summary > div {
  min-width: 0;
  border: 1px solid #d9e4ee;
  border-radius: 12px;
  background: #f8fbfd;
  padding: 12px;
}

.unbuilt-dialog-summary span {
  display: block;
  color: #667085;
  font-size: 12px;
  font-weight: 760;
  line-height: 1.3;
}

.unbuilt-dialog-summary strong {
  display: block;
  margin-top: 4px;
  color: #111827;
  font-size: 20px;
  font-weight: 900;
  line-height: 1.25;
  overflow-wrap: anywhere;
}

.unbuilt-dialog-list {
  display: grid;
  min-height: 180px;
  max-height: 52vh;
  gap: 8px;
  overflow: auto;
  padding-right: 4px;
}

.unbuilt-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #d9e4ee;
  border-radius: 10px;
  background: #fff;
  padding: 10px 12px;
}

.unbuilt-row div {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.unbuilt-row strong {
  color: #111827;
  font-size: 15px;
  font-weight: 900;
  line-height: 1.25;
}

.unbuilt-row span {
  color: #526173;
  font-size: 13px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.unbuilt-row small {
  flex: 0 0 auto;
  align-self: flex-start;
  color: #667085;
  font-size: 12px;
  font-weight: 800;
  line-height: 1.25;
}

.task-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.group-tools {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
  padding: 10px;
  border-bottom: 1px solid #e6edf3;
  align-items: center;
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(8px);
}

.group-search-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 8px;
  align-items: center;
}

.group-filter-tabs {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
}

.group-filter-tabs button {
  min-width: 0;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  border: 1px solid #d9e4ee;
  border-radius: 9px;
  background: #fff;
  color: #526173;
  padding: 0 9px;
  font-weight: 800;
  cursor: pointer;
}

.group-filter-tabs button.active {
  border-color: #0f7f95;
  background: #e8f6fa;
  color: #083d4d;
}

.group-filter-tabs strong {
  color: inherit;
  font-size: 13px;
}

.cache-inline-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  color: #667085;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.group-card {
  display: block;
  padding: 12px;
}

.group-card.cached {
  border-color: #d9b76f;
}

.group-card.exception {
  border-color: #e2a4a0;
}

.group-main {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.group-name-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.group-main span,
.group-main small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cache-line {
  color: #9a6700;
}

.exception-line {
  color: #b42318;
}

:deep(.construction-drawer) {
  background: #f6f8fb;
}

:deep(.construction-drawer .el-drawer__body) {
  padding: 0;
}

.collector-sheet {
  display: flex;
  min-height: 100dvh;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.collector-sheet-inline {
  min-height: auto;
  padding: 12px;
}

.sheet-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.sheet-head-actions {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
}

.sheet-close {
  border-color: #d9e4ee;
  color: #526173;
}

.sheet-head h3 {
  font-size: 22px;
}

.exception-note,
.sheet-warning {
  border: 1px solid #ffd5d2;
  border-radius: 10px;
  background: #fff5f4;
  color: #b42318;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.5;
}

.construction-submit-gap {
  display: grid;
  gap: 4px;
}

.construction-submit-gap strong,
.construction-submit-gap span {
  overflow-wrap: anywhere;
}

.readonly-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.readonly-grid > div,
.field-grid label {
  border: 1px solid #d9e4ee;
  border-radius: 10px;
  background: #fff;
  padding: 10px 12px;
}

.readonly-grid .wide {
  grid-column: 1 / -1;
}

.readonly-grid span,
.field-grid span {
  display: block;
  margin-bottom: 4px;
  color: #667085;
  font-size: 12px;
  font-weight: 700;
}

.readonly-grid strong {
  display: block;
  overflow: hidden;
  color: #111827;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.field-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.construction-section-list,
.construction-section,
.construction-photo-section {
  display: grid;
  gap: 10px;
}

.construction-section,
.construction-photo-section {
  border: 1px solid #d9e4ee;
  border-radius: 12px;
  background: #fff;
  padding: 10px;
}

.construction-section-device-replacement {
  border-color: #bddfd0;
  background: #f7fcf9;
}

.construction-section-main-device-replacement {
  border-color: #f4b4aa;
  background: #fff8f6;
}

.construction-section-accessory-confirmation {
  border-color: #f3d28f;
  background: #fffaf0;
}

.construction-section-conditional-accessory-fields {
  border-color: #f3d28f;
  background: #fffdf7;
}

.construction-section-task-core {
  border-color: #d8c9f7;
  background: #fbf9ff;
}

.construction-section-supporting-fields {
  background: #fbfdff;
}

.construction-section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.construction-section-head > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.construction-section-head strong {
  color: #111827;
  font-size: 14px;
  font-weight: 900;
}

.construction-section-head span {
  color: #667085;
  font-size: 12px;
  line-height: 1.45;
}

.construction-role-tag {
  display: inline-flex;
  margin-left: 6px;
  vertical-align: middle;
}

.construction-intent-tag {
  display: inline-flex;
  margin-left: 6px;
  vertical-align: middle;
}

.construction-condition-hint {
  display: block;
  margin: -2px 0 8px;
  color: #9a6700;
  font-size: 12px;
  font-weight: 800;
  line-height: 1.35;
}

.field-with-action {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
}

.field-grid b,
.slot-title b {
  color: #b42318;
}

.existing-photos {
  border: 1px solid #d9e4ee;
  border-radius: 12px;
  background: #fff;
  padding: 10px;
}

.existing-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.existing-head strong {
  color: #111827;
  font-weight: 900;
}

.existing-head span {
  color: #667085;
  font-size: 12px;
}

.existing-list {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 2px;
}

.existing-list img {
  width: 76px;
  height: 76px;
  flex: 0 0 auto;
  border: 1px solid #d9e4ee;
  border-radius: 9px;
  background: #111827;
  object-fit: cover;
}

.slot-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.photo-slot {
  border: 1px solid #d9e4ee;
  border-radius: 12px;
  background: #fff;
  padding: 12px;
}

.slot-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.slot-title strong {
  color: #111827;
}

.slot-preview {
  display: grid;
  overflow: hidden;
  min-height: 160px;
  place-items: center;
  border: 1px dashed #c7d4e1;
  border-radius: 10px;
  background: #f7fafc;
  color: #667085;
}

.slot-preview img {
  width: 100%;
  height: 180px;
  object-fit: contain;
  background: #111827;
}

.slot-preview > div {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  font-weight: 700;
}

.slot-note {
  margin-top: 8px;
  border: 1px solid #d9eadf;
  border-radius: 8px;
  background: #f5fbf7;
  color: #287047;
  padding: 7px 9px;
  font-size: 12px;
  line-height: 1.45;
}

.slot-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-top: 10px;
}

.file-input {
  position: fixed;
  left: 0;
  bottom: 0;
  z-index: -1;
  width: 1px;
  height: 1px;
  opacity: 0.01;
}

.scanner-backdrop {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: grid;
  place-items: center;
  padding: 16px;
  background: rgba(10, 18, 27, 0.66);
}

.scanner-panel {
  width: min(620px, 100%);
  display: grid;
  gap: 12px;
  border: 1px solid rgba(255, 255, 255, 0.22);
  border-radius: 16px;
  background: #fff;
  padding: 14px;
  box-shadow: 0 34px 90px rgba(0, 0, 0, 0.28);
}

.scanner-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.scanner-head strong,
.scanner-head span {
  display: block;
}

.scanner-head strong {
  color: #111827;
  font-size: 16px;
  font-weight: 800;
}

.scanner-head span {
  margin-top: 4px;
  color: #667085;
  font-size: 12px;
}

.scanner-camera {
  position: relative;
  min-height: 280px;
  overflow: hidden;
  border-radius: 12px;
  background: #0b1118;
}

.scanner-camera video,
.scanner-camera :deep(video),
.scanner-camera :deep(canvas) {
  width: 100%;
  max-height: 66dvh;
  display: block;
}

.scanner-camera :deep(canvas.drawingBuffer) {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.scan-frame {
  position: absolute;
  left: 10%;
  right: 10%;
  top: 39%;
  z-index: 4;
  height: 86px;
  border: 2px solid rgba(220, 249, 255, 0.95);
  border-radius: 12px;
  box-shadow:
    0 0 0 999px rgba(0, 0, 0, 0.18),
    inset 0 0 28px rgba(15, 127, 149, 0.26);
  pointer-events: none;
}

.scan-frame::before {
  content: "";
  position: absolute;
  left: 12px;
  right: 12px;
  top: 50%;
  height: 2px;
  border-radius: 999px;
  background: #22d3ee;
  box-shadow: 0 0 18px rgba(34, 211, 238, 0.85);
}

.scanner-camera p {
  position: absolute;
  right: 12px;
  bottom: 12px;
  left: 12px;
  z-index: 5;
  margin: 0;
  border-radius: 8px;
  background: rgba(12, 17, 23, 0.72);
  color: #eef9ff;
  padding: 8px 10px;
  font-size: 12px;
  text-align: center;
}

.scanner-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.sheet-actions {
  position: sticky;
  bottom: 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin: auto -18px -18px;
  border-top: 1px solid #d9e4ee;
  background: rgba(246, 248, 251, 0.96);
  padding: 12px 18px calc(12px + env(safe-area-inset-bottom));
  backdrop-filter: blur(12px);
}

.collector-sheet-inline .sheet-actions {
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  margin: 0 -12px -12px;
  padding: 10px 12px;
}

.draft-status {
  min-width: 0;
  color: #667085;
  font-size: 12px;
  font-weight: 800;
}

/* V3 construction scoped visual layer. Business logic and API calls stay in the script above. */
.construction-v24 {
  --construction-accent: var(--v2-primary, #0a72d8);
  --construction-accent-hover: var(--v2-primary-hover, #075eb5);
  --construction-accent-soft: rgba(10, 114, 216, 0.08);
  --construction-surface: rgba(255, 255, 255, 0.9);
  --construction-surface-strong: rgba(255, 255, 255, 0.98);
  --construction-subtle: rgba(248, 250, 252, 0.92);
  --construction-border: rgba(16, 24, 40, 0.08);
  --construction-border-strong: rgba(10, 114, 216, 0.24);
  --construction-shadow: 0 18px 46px rgba(16, 24, 40, 0.07), inset 0 1px 0 rgba(255, 255, 255, 0.78);
  --construction-shadow-soft: 0 10px 28px rgba(16, 24, 40, 0.055), inset 0 1px 0 rgba(255, 255, 255, 0.72);
  min-width: 0;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(247, 250, 253, 0.96) 36%, rgba(242, 246, 251, 0.98) 100%),
    var(--v2-bg-app, #f5f7fb);
  color: var(--v2-text, #27364a);
}

.construction-v24 :deep(.el-button + .el-button) {
  margin-left: 0;
}

.construction-v24 :deep(.el-button) {
  min-height: 36px;
  border-radius: 10px;
  font-weight: 820;
  white-space: nowrap;
}

.construction-v24 :deep(.el-button--small) {
  min-height: 34px;
  padding-right: 12px;
  padding-left: 12px;
}

.construction-v24 :deep(.el-button--large) {
  min-height: 44px;
  border-radius: 11px;
}

.construction-v24 :deep(.el-input__wrapper),
.construction-v24 :deep(.el-textarea__inner) {
  min-height: 38px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 0 0 1px var(--construction-border) inset, 0 1px 0 rgba(255, 255, 255, 0.78);
}

.construction-v24 :deep(.el-input__inner) {
  min-width: 0;
}

.construction-v24 :deep(.el-tag) {
  max-width: 100%;
  border-radius: 999px;
  font-weight: 780;
}

.panel {
  overflow: hidden;
  border-color: var(--construction-border);
  border-radius: var(--v2-radius-panel, 12px);
  background:
    linear-gradient(180deg, var(--construction-surface-strong), rgba(255, 255, 255, 0.88)),
    var(--v2-bg-surface, #fff);
  box-shadow: var(--construction-shadow);
  backdrop-filter: blur(18px) saturate(155%);
  -webkit-backdrop-filter: blur(18px) saturate(155%);
}

.construction-workspace {
  gap: 12px;
}

.construction-workspace.task-select-mode {
  grid-template-columns: minmax(320px, 680px);
  padding-top: 12px;
}

.construction-workspace.work-mode {
  grid-template-columns: minmax(370px, 520px) minmax(0, 1fr);
}

.panel-head {
  min-height: 64px;
  align-items: flex-start;
  padding: 14px 16px;
  border-bottom-color: var(--construction-border);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(249, 251, 254, 0.9)),
    var(--v2-bg-surface, #fff);
}

.panel-head > div:first-child,
.sheet-head > div:first-child {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.panel-head h3 {
  color: var(--v2-text-strong, #101828);
  font-size: 17px;
  line-height: 1.22;
}

.panel-head span,
.sheet-head span {
  min-width: 0;
  overflow: hidden;
  color: var(--v2-text-muted, #68778b);
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.head-actions {
  gap: 8px;
}

.task-list,
.group-list {
  gap: 10px;
  padding: 12px;
}

.field-task-picker-list {
  gap: 10px;
}

.task-card,
.field-task-card,
.group-card,
.photo-slot,
.existing-photos,
.readonly-grid > div,
.field-grid label {
  border-color: var(--construction-border);
  border-radius: var(--v2-radius-panel, 12px);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.99), rgba(249, 251, 254, 0.94)),
    var(--v2-bg-surface, #fff);
  box-shadow: var(--construction-shadow-soft);
}

.task-card,
.field-task-card {
  padding: 14px;
}

.task-card:hover,
.field-task-card:hover,
.field-task-card:focus-visible,
.group-card:hover {
  border-color: var(--construction-border-strong);
  box-shadow: 0 16px 36px rgba(16, 24, 40, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.84);
}

.task-card.active,
.group-card.active {
  border-color: var(--construction-border-strong);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.99), rgba(244, 249, 255, 0.96)),
    var(--v2-primary-muted, #f4f9ff);
  box-shadow: 0 16px 38px rgba(10, 114, 216, 0.13), inset 0 0 0 1px rgba(10, 114, 216, 0.08);
}

.field-task-card.kind-exception {
  border-left-color: var(--v2-danger, #b42318);
}

.field-task-card.kind-unmatched {
  border-left-color: var(--v2-warning, #a15c00);
}

.field-task-card.kind-platform {
  border-left-color: var(--v2-success, #067647);
}

.field-task-entry {
  margin-bottom: 4px;
}

.field-task-entry .el-tag,
.field-task-title .el-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}

.platform-work-order-entry {
  display: grid;
  gap: 10px;
}

.platform-schema-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.platform-schema-sections {
  display: grid;
  flex: 1 1 100%;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px;
  min-width: 0;
}

.platform-schema-section {
  display: grid;
  gap: 5px;
  min-width: 0;
  border: 1px solid rgba(16, 24, 40, 0.08);
  border-radius: 10px;
  padding: 8px;
}

.platform-schema-section strong {
  color: #111827;
  font-size: 12px;
  font-weight: 900;
}

.platform-schema-section small {
  color: #667085;
  font-size: 11px;
  line-height: 1.35;
}

.platform-rework-filter {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid rgba(234, 88, 12, 0.18);
  border-radius: 10px;
  background: rgba(255, 247, 237, 0.72);
}

.platform-schema-chips span {
  min-width: 0;
  max-width: 100%;
  border: 1px solid rgba(16, 24, 40, 0.06);
  border-radius: 999px;
  background: rgba(240, 253, 244, 0.76);
  color: var(--v2-text, #344054);
  font-size: 12px;
  line-height: 1.3;
  padding: 5px 9px;
  overflow-wrap: anywhere;
}

.platform-schema-section span {
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.8);
}

.platform-schema-section span em {
  display: block;
  margin-top: 2px;
  color: #667085;
  font-style: normal;
  font-weight: 800;
}

.platform-work-order-samples {
  display: grid;
  gap: 6px;
}

.platform-work-order-samples > div {
  display: grid;
  gap: 3px;
  border: 1px solid rgba(16, 24, 40, 0.045);
  border-radius: 10px;
  background: rgba(248, 250, 252, 0.86);
  padding: 9px;
}

.platform-work-order-samples strong,
.platform-work-order-samples span,
.platform-work-order-samples small {
  min-width: 0;
  overflow-wrap: anywhere;
}

.platform-core-context {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 8px;
  min-width: 0;
}

.platform-core-context span,
.display-field-chip {
  color: var(--el-color-primary);
  font-weight: 600;
}

.platform-kpi-line {
  color: var(--v2-text-muted, #64748b);
  font-weight: 700;
}

.site-checklist-panel {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid rgba(10, 114, 216, 0.16);
  border-radius: 8px;
  background: #f8fbff;
}

.site-checklist-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.site-checklist-head > div {
  display: grid;
  gap: 3px;
}

.site-checklist-head strong {
  color: var(--v2-text-strong, #0f172a);
}

.site-checklist-head span,
.site-checklist-panel > small {
  color: var(--v2-text-muted, #64748b);
  font-size: 12px;
  line-height: 1.45;
}

.site-checklist-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.site-checklist-grid article {
  display: grid;
  gap: 6px;
  min-width: 0;
  padding: 10px;
  border: 1px solid rgba(100, 116, 139, 0.14);
  border-radius: 8px;
  background: #ffffff;
}

.site-checklist-grid article.done {
  border-color: rgba(6, 118, 71, 0.2);
  background: rgba(240, 253, 244, 0.9);
}

.site-checklist-grid article.required:not(.done) {
  border-color: rgba(180, 35, 24, 0.2);
  background: rgba(255, 247, 247, 0.92);
}

.site-checklist-grid article > div {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.site-checklist-grid strong,
.site-checklist-grid span,
.site-checklist-grid small {
  min-width: 0;
  overflow-wrap: anywhere;
}

.site-checklist-grid strong {
  color: var(--v2-text-strong, #101828);
  font-size: 13px;
  line-height: 1.35;
}

.site-checklist-grid small,
.site-checklist-grid span {
  color: var(--v2-text-muted, #64748b);
  font-size: 12px;
  line-height: 1.4;
}

.platform-kpi-panel {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid rgba(10, 114, 216, 0.16);
  border-radius: 8px;
  background: #f8fbff;
}

.platform-kpi-panel-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}

.platform-kpi-panel-head strong {
  color: var(--v2-text-strong, #0f172a);
}

.platform-kpi-panel-head span,
.platform-kpi-status span {
  color: var(--v2-text-muted, #64748b);
  font-size: 12px;
  font-weight: 700;
}

.platform-kpi-inputs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.platform-kpi-inputs label {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.platform-kpi-inputs label > span {
  color: var(--v2-text-muted, #64748b);
  font-size: 12px;
  font-weight: 760;
}

.platform-kpi-status {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.platform-kpi-status span {
  padding: 5px 8px;
  border: 1px solid rgba(100, 116, 139, 0.14);
  border-radius: 999px;
  background: #ffffff;
}

.platform-rework-note {
  color: #9a3412;
  font-weight: 760;
}

.platform-rework-note-panel {
  padding: 10px 12px;
  border: 1px solid rgba(234, 88, 12, 0.22);
  border-radius: 10px;
  background: rgba(255, 247, 237, 0.9);
}

.platform-rework-gap-panel {
  display: grid;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid rgba(234, 88, 12, 0.2);
  border-radius: 10px;
  background: #fff7ed;
  color: #9a3412;
}

.platform-rework-gap-panel strong {
  color: #7c2d12;
  font-size: 14px;
}

.platform-rework-gap-panel span {
  display: block;
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: 13px;
  line-height: 1.45;
}

.platform-rework-gap-panel em {
  margin-right: 6px;
  color: #c2410c;
  font-style: normal;
  font-weight: 740;
}

.task-title,
.field-task-title,
.group-name-row {
  align-items: flex-start;
}

.task-title strong,
.field-task-title strong,
.group-main strong {
  min-width: 0;
  color: var(--v2-text-strong, #101828);
  font-size: 16px;
  line-height: 1.25;
  overflow-wrap: anywhere;
}

.task-metrics {
  gap: 8px;
}

.task-metrics span,
.task-metric-button {
  border: 1px solid rgba(16, 24, 40, 0.045);
  border-radius: 10px;
  background: rgba(248, 250, 252, 0.86);
  padding: 9px;
}

.task-metrics strong {
  color: var(--v2-text-strong, #101828);
  font-family: var(--v2-font-mono, monospace);
}

.task-progress::before {
  height: 8px;
  background: rgba(226, 232, 240, 0.95);
}

.task-progress i {
  height: 8px;
  background: linear-gradient(90deg, var(--construction-accent), #18a0c8);
}

.task-actions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(86px, 1fr));
}

.task-actions .el-button {
  width: 100%;
}

.group-tools {
  position: sticky;
  top: 0;
  z-index: 3;
  gap: 10px;
  padding: 12px;
  border-bottom-color: var(--construction-border);
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: blur(20px) saturate(160%);
  -webkit-backdrop-filter: blur(20px) saturate(160%);
}

.group-search-row {
  gap: 8px;
}

.group-search-row .el-button {
  min-width: 72px;
}

.group-filter-tabs {
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--construction-border);
  border-radius: var(--v2-radius-panel, 12px);
  background: rgba(241, 245, 249, 0.78);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

.group-filter-tabs button {
  height: 42px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--v2-text-muted, #68778b);
  padding: 0 10px;
  transition:
    background var(--v2-transition-fast, 140ms ease),
    color var(--v2-transition-fast, 140ms ease),
    box-shadow var(--v2-transition-fast, 140ms ease);
}

.group-filter-tabs button.active {
  background: #fff;
  color: var(--v2-text-strong, #101828);
  box-shadow: 0 7px 18px rgba(16, 24, 40, 0.085), inset 0 0 0 1px rgba(10, 114, 216, 0.11);
}

.group-filter-tabs strong {
  display: inline-grid;
  min-width: 24px;
  height: 24px;
  place-items: center;
  border-radius: 999px;
  background: rgba(10, 114, 216, 0.08);
  color: inherit;
  font-family: var(--v2-font-mono, monospace);
  font-size: 12px;
}

.cache-inline-actions {
  justify-content: space-between;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid rgba(161, 92, 0, 0.16);
  border-radius: 10px;
  background: rgba(255, 246, 230, 0.74);
}

.cache-inline-actions span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.group-card {
  padding: 14px;
}

.group-card.cached {
  border-color: rgba(161, 92, 0, 0.24);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.99), rgba(255, 250, 240, 0.94)),
    #fff;
}

.group-card.exception {
  border-color: rgba(180, 35, 24, 0.22);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.99), rgba(255, 246, 245, 0.94)),
    #fff;
}

.cache-line {
  color: var(--v2-warning, #a15c00);
}

.group-card-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
}

.group-card-actions .el-button {
  min-height: 32px;
}

.exception-line {
  color: var(--v2-danger, #b42318);
}

:deep(.construction-drawer) {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(244, 247, 251, 0.98)),
    var(--v2-bg-app, #f5f7fb);
}

.collector-sheet {
  gap: 14px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(246, 249, 253, 0.98)),
    var(--v2-bg-app, #f5f7fb);
}

.collector-sheet-inline {
  background: transparent;
}

.sheet-head {
  align-items: flex-start;
}

.eyebrow {
  color: var(--construction-accent);
  font-weight: 820;
}

.sheet-head h3 {
  color: var(--v2-text-strong, #101828);
  font-size: clamp(20px, 2vw, 25px);
  line-height: 1.12;
  overflow-wrap: anywhere;
}

.exception-note,
.sheet-warning,
.slot-note {
  border-radius: 10px;
}

.sheet-warning {
  display: grid;
  gap: 4px;
  border-color: var(--v2-danger-border, #ffc7c0);
  background: rgba(255, 240, 238, 0.88);
}

.readonly-grid,
.field-grid {
  gap: 10px;
}

.readonly-grid > div,
.field-grid label {
  min-width: 0;
}

.readonly-grid strong {
  color: var(--v2-text-strong, #101828);
}

.field-with-action {
  grid-template-columns: minmax(0, 1fr) minmax(78px, auto);
}

.existing-photos,
.photo-slot {
  padding: 12px;
}

.existing-list img {
  width: 82px;
  height: 82px;
  border-color: var(--construction-border);
  border-radius: 10px;
}

.photo-slot {
  display: grid;
  min-width: 0;
}

.slot-title {
  align-items: flex-start;
}

.slot-title strong {
  min-width: 0;
  color: var(--v2-text-strong, #101828);
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.slot-preview {
  min-height: 0;
  aspect-ratio: 4 / 3;
  border-color: rgba(10, 114, 216, 0.18);
  border-radius: 11px;
  background:
    linear-gradient(180deg, rgba(248, 250, 252, 0.94), rgba(241, 245, 249, 0.92)),
    #f8fafc;
}

.slot-preview img {
  height: 100%;
  min-height: 0;
  background: #0b1118;
}

.slot-preview > div {
  color: var(--v2-text-muted, #68778b);
}

.slot-preview :deep(.el-icon) {
  font-size: 28px;
}

.slot-actions {
  gap: 8px;
}

.slot-actions .el-button,
.scanner-actions .el-button {
  width: 100%;
  min-height: 40px;
}

.sheet-actions {
  grid-template-columns: minmax(0, 1fr) minmax(126px, auto) minmax(148px, auto);
  align-items: center;
  border-top-color: var(--construction-border);
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(22px) saturate(165%);
  -webkit-backdrop-filter: blur(22px) saturate(165%);
}

.collector-sheet-inline .sheet-actions {
  border-radius: 0 0 var(--v2-radius-panel, 12px) var(--v2-radius-panel, 12px);
}

.draft-status {
  overflow: hidden;
  color: var(--v2-text-muted, #68778b);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scanner-backdrop {
  background: rgba(10, 18, 27, 0.62);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.scanner-panel {
  border-color: rgba(255, 255, 255, 0.28);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 34px 90px rgba(0, 0, 0, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.82);
}

.scanner-camera {
  border-radius: 14px;
}

.scan-frame {
  border-color: rgba(232, 246, 255, 0.98);
  box-shadow:
    0 0 0 999px rgba(0, 0, 0, 0.2),
    inset 0 0 28px rgba(10, 114, 216, 0.28);
}

@media (max-width: 960px) {
  .construction-v24 {
    height: 100dvh;
    min-height: 100dvh;
    padding: 0;
    gap: 0;
    overflow: hidden;
  }

  .construction-top,
  .construction-v24.is-work-mode .construction-top {
    display: none;
  }

  .top-actions {
    justify-content: stretch;
  }

  .top-actions .el-button {
    flex: 1;
  }

  .construction-workspace {
    grid-template-columns: 1fr;
    height: 100%;
    min-height: 0;
    padding: 8px 8px calc(8px + env(safe-area-inset-bottom));
  }

  .construction-workspace.task-select-mode {
    align-content: start;
  }

  .construction-workspace.task-select-mode .task-panel {
    max-height: calc(100dvh - 16px - env(safe-area-inset-bottom));
  }

  .desktop-editor {
    display: none;
  }

  .task-list {
    max-height: calc(100dvh - 86px - env(safe-area-inset-bottom));
    flex-direction: column;
    overflow-y: auto;
  }

  .task-card {
    min-width: 0;
  }

  .group-tools {
    grid-template-columns: 1fr;
    z-index: 3;
    background: rgba(255, 255, 255, 0.96);
    backdrop-filter: blur(10px);
  }

  .group-search-row {
    grid-template-columns: minmax(0, 1fr) 82px 64px;
  }

  .group-filter-tabs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .cache-inline-actions {
    justify-content: space-between;
  }

  .construction-workspace.work-mode,
  .group-panel {
    height: 100dvh;
    min-height: 0;
  }

  .construction-workspace.work-mode {
    padding: 0;
  }

  .group-panel {
    border-radius: 0;
    border-right: 0;
    border-left: 0;
    grid-template-rows: auto minmax(0, 1fr);
  }

  .group-panel .panel-head {
    min-height: 52px;
    position: relative;
    z-index: 4;
    padding: 9px 10px;
    box-shadow: 0 1px 0 rgba(217, 228, 238, 0.85);
  }

  .group-panel .head-actions {
    gap: 6px;
  }

  .group-panel .head-actions .el-tag {
    display: none;
  }

  .group-body {
    min-height: 0;
    overflow: hidden;
    display: grid;
    grid-template-rows: auto minmax(0, 1fr);
  }

  .group-list {
    max-height: none;
    min-height: 0;
    overflow-y: auto;
    padding: 10px;
  }

  .construction-panel-logout {
    min-height: 40px;
    border-radius: 14px;
  }

  .group-card {
    border-radius: 18px;
    padding: 14px;
    background: linear-gradient(180deg, #fff, #f9fbfc);
    box-shadow: 0 10px 24px rgba(24, 39, 52, 0.06);
  }

  .group-card.active {
    background: linear-gradient(180deg, #edf8fb, #fff);
    box-shadow:
      inset 4px 0 0 #0f7f95,
      0 10px 24px rgba(24, 39, 52, 0.08);
  }

  .group-main span {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    white-space: normal;
    color: #334155;
    line-height: 1.45;
  }

  .group-main small:not(.cache-line):not(.exception-line) {
    display: none;
  }

  :deep(.construction-drawer.el-drawer.btt) {
    height: 94dvh !important;
    border-radius: 22px 22px 0 0;
  }

  :deep(.construction-drawer .el-drawer__body) {
    min-height: 0;
    overflow: hidden;
  }

  .collector-sheet {
    height: 100%;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    padding: 12px;
  }

  .field-grid,
  .readonly-grid,
  .slot-grid {
    grid-template-columns: 1fr;
  }

  .slot-preview {
    min-height: 150px;
  }

  .task-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .scanner-backdrop {
    align-items: end;
    padding: 8px;
  }

  .scanner-panel {
    border-radius: 18px 18px 12px 12px;
  }

  .scanner-camera {
    min-height: 56dvh;
  }

  .sheet-actions {
    position: static;
    grid-template-columns: 1fr 1fr;
    margin: 0;
    margin-right: -14px;
    margin-left: -14px;
    padding-right: 14px;
    padding-left: 14px;
  }

  .draft-status {
    grid-column: 1 / -1;
  }
}

@media (max-width: 960px) {
  .construction-v24 {
    background:
      linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(244, 247, 251, 0.98)),
      var(--v2-bg-app, #f5f7fb);
  }

  .construction-workspace {
    padding: 0;
  }

  .construction-workspace.task-select-mode {
    padding: 8px 8px calc(8px + env(safe-area-inset-bottom));
  }

  .construction-workspace.task-select-mode .task-panel {
    max-height: calc(100dvh - 16px - env(safe-area-inset-bottom));
    border-radius: var(--v2-radius-panel, 12px);
  }

  .task-panel .panel-head,
  .group-panel .panel-head {
    display: grid;
    gap: 10px;
    min-height: auto;
    align-items: stretch;
    padding: 12px;
  }

  .task-panel .head-actions,
  .group-panel .head-actions {
    display: grid;
    width: 100%;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .task-panel .head-actions .el-tag,
  .group-panel .head-actions .el-tag {
    display: none;
  }

  .task-panel .head-actions .el-button,
  .group-panel .head-actions .el-button {
    width: 100%;
    min-height: 40px;
  }

  .panel-head h3 {
    font-size: 18px;
  }

  .panel-head span,
  .sheet-head span {
    display: -webkit-box;
    overflow: hidden;
    line-height: 1.42;
    text-overflow: clip;
    white-space: normal;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
  }

  .panel-head h3 .construction-version-inline {
    display: inline-block;
    line-height: 1.2;
    vertical-align: 1px;
    -webkit-line-clamp: unset;
  }

  .task-list {
    max-height: none;
    padding: 10px;
  }

  .task-card,
  .field-task-card {
    gap: 11px;
    padding: 14px;
  }

  .task-title,
  .field-task-title {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .task-title strong,
  .field-task-title strong {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .task-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .task-metrics span,
  .task-metric-button {
    padding: 10px;
  }

  .task-actions {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .task-actions .el-button {
    min-height: 40px;
  }

  .construction-workspace.work-mode,
  .group-panel {
    height: 100dvh;
    min-height: 0;
  }

  .group-panel {
    border-radius: 0;
    background: rgba(247, 250, 253, 0.98);
  }

  .group-panel .panel-head {
    position: relative;
    z-index: 5;
    border-bottom-color: rgba(16, 24, 40, 0.08);
    background: rgba(255, 255, 255, 0.92);
    box-shadow: 0 10px 26px rgba(16, 24, 40, 0.055);
    backdrop-filter: blur(20px) saturate(160%);
    -webkit-backdrop-filter: blur(20px) saturate(160%);
  }

  .group-tools {
    gap: 10px;
    padding: 10px;
    background: rgba(247, 250, 253, 0.92);
  }

  .group-search-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .group-search-row .el-input {
    grid-column: 1 / -1;
  }

  .group-search-row .el-button {
    width: 100%;
    min-width: 0;
    min-height: 42px;
  }

  .group-filter-tabs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .group-filter-tabs button {
    height: 46px;
    padding: 0 11px;
  }

  .cache-inline-actions {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
  }

  .cache-inline-actions .el-button {
    min-height: 38px;
  }

  .group-list {
    gap: 10px;
    padding: 10px 8px calc(14px + env(safe-area-inset-bottom));
  }

  .group-card {
    min-height: 88px;
    border-radius: var(--v2-radius-panel, 12px);
    padding: 14px;
  }

  .group-card.active {
    box-shadow:
      inset 3px 0 0 var(--construction-accent),
      0 14px 30px rgba(10, 114, 216, 0.12);
  }

  .group-name-row {
    align-items: flex-start;
  }

  .group-main span {
    margin-top: 1px;
  }

  :deep(.construction-drawer.el-drawer.btt) {
    height: 95dvh !important;
    border-radius: 18px 18px 0 0;
  }

  .collector-sheet {
    gap: 12px;
    padding: 12px;
  }

  .sheet-head {
    position: sticky;
    top: 0;
    z-index: 4;
    margin: -12px -12px 0;
    padding: 12px;
    border-bottom: 1px solid rgba(16, 24, 40, 0.08);
    background: rgba(255, 255, 255, 0.94);
    backdrop-filter: blur(20px) saturate(160%);
    -webkit-backdrop-filter: blur(20px) saturate(160%);
  }

  .sheet-head h3 {
    font-size: 22px;
  }

  .sheet-head-actions {
    align-items: flex-start;
  }

  .readonly-grid > div,
  .field-grid label,
  .existing-photos,
  .photo-slot {
    border-radius: var(--v2-radius-panel, 12px);
  }

  .field-with-action {
    grid-template-columns: minmax(0, 1fr) 86px;
  }

  .field-with-action .el-button {
    min-height: 42px;
  }

  .slot-grid {
    gap: 10px;
    padding-bottom: calc(74px + env(safe-area-inset-bottom));
  }

  .slot-title {
    gap: 10px;
  }

  .slot-preview {
    min-height: 136px;
    aspect-ratio: 16 / 10;
  }

  .slot-actions {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .slot-actions .el-button {
    min-height: 44px;
  }

  .sheet-actions {
    position: sticky;
    bottom: 0;
    z-index: 5;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 9px;
    margin: 0 -12px;
    border-radius: 12px 12px 0 0;
    background: rgba(255, 255, 255, 0.98);
    box-shadow:
      0 -16px 28px rgba(16, 24, 40, 0.08),
      0 32px 0 rgba(255, 255, 255, 0.98);
    padding: 10px 12px calc(10px + env(safe-area-inset-bottom));
  }

  .sheet-actions .el-button {
    width: 100%;
    min-width: 0;
    min-height: 44px;
    padding-right: 8px;
    padding-left: 8px;
  }

  .draft-status {
    grid-column: 1 / -1;
    text-align: left;
  }

  .scanner-backdrop {
    align-items: end;
    padding: 8px;
  }

  .scanner-panel {
    width: 100%;
    border-radius: 18px 18px 12px 12px;
    padding: 12px;
  }

  .scanner-camera {
    min-height: min(58dvh, 520px);
  }

  .scanner-actions .el-button {
    min-height: 44px;
  }
}

@media (max-width: 720px) {
  .site-checklist-grid {
    grid-template-columns: 1fr;
  }

  .site-checklist-head {
    flex-direction: column;
  }

  .platform-kpi-inputs {
    grid-template-columns: 1fr;
  }

  .platform-kpi-panel-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .unbuilt-dialog-summary {
    grid-template-columns: 1fr;
  }

  .unbuilt-row {
    flex-direction: column;
  }
}

@media (max-width: 420px) {
  .task-panel .head-actions,
  .group-panel .head-actions {
    grid-template-columns: 1fr 1fr;
  }

  .task-title,
  .field-task-title,
  .group-name-row {
    gap: 8px;
  }

  .task-title .el-tag,
  .field-task-title .el-tag,
  .group-name-row .el-tag {
    max-width: 118px;
  }

  .group-filter-tabs button {
    padding: 0 9px;
  }

  .group-filter-tabs strong {
    min-width: 22px;
  }

  .field-with-action {
    grid-template-columns: minmax(0, 1fr) 78px;
  }
}
</style>
