<script setup lang="ts">
import { Check, Close, Refresh, Warning } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import StatusTag from '@/components/StatusTag.vue'
import { currentActor, fetchProjectReviewWorkOrders, reviewProjectReviewWorkOrder } from '@/api/services'
import type {
  MaterialGroup,
  PlatformReviewActionPayload,
  PlatformReviewFieldReview,
  PlatformReviewHierarchyGapItem,
  PlatformReviewPhotoSlotReview,
  PlatformReviewWorkOrder,
  ProjectFieldDefinition,
  ReviewPhoto,
  TaskStatus,
} from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const workspace = useWorkspaceStore()
const activePhotoId = ref('')
const photoCategory = ref('表前')
const reviewNote = ref('')
const loadingPlatformReview = ref(false)
const platformReviewStatusFilter = ref<PlatformReviewStatusFilter>('all')
const platformReviewWorkOrders = ref<PlatformReviewWorkOrder[]>([])
const selectedPlatformReviewWorkOrderId = ref('')
const platformReviewStatusCounts = ref<Record<Exclude<PlatformReviewStatusFilter, 'all'>, number>>({
  pending_review: 0,
  approved: 0,
  returned: 0,
  exception: 0,
  not_ready: 0,
})

const terminalReplacementReviewLabels = ['通讯模块（需更换）', '新SIM卡', '改造前照片', '新旧模块照片', '改造后照片']

const reviewActions: Array<{ status: TaskStatus; label: string; type: 'success' | 'warning' | 'danger'; icon: unknown }> = [
  { status: 'complete', label: '完成', type: 'success', icon: Check },
  { status: 'incomplete', label: '不完整', type: 'warning', icon: Warning },
  { status: 'exception', label: '异常', type: 'danger', icon: Close },
]

type PlatformReviewStatusFilter = 'all' | 'pending_review' | 'approved' | 'returned' | 'exception' | 'not_ready'
type ReviewHierarchySection = {
  id:
    | 'task-core'
    | 'main-device-replacement'
    | 'device-replacement'
    | 'accessory-confirmation'
    | 'conditional-accessory-fields'
    | 'supporting-fields'
  title: string
  helper: string
  fields: PlatformReviewFieldReview[]
}
type ReviewPhotoHierarchySection = {
  id: 'photo-evidence' | 'other-photos'
  title: string
  helper: string
  slots: PlatformReviewPhotoSlotReview[]
}
type ReviewEvidenceIntentItem = {
  key?: string
  relationRole?: ProjectFieldDefinition['relationRole']
  requiredWhen?: PlatformReviewFieldReview['requiredWhen']
}
type ReviewKpiEvidenceRow = {
  key: string
  label: string
  value: string
}
const platformReviewActions: Array<{
  action: PlatformReviewActionPayload['action']
  label: string
  type: 'success' | 'warning' | 'danger'
  icon: unknown
}> = [
  { action: 'approved', label: '通过', type: 'success', icon: Check },
  { action: 'returned', label: '退回', type: 'warning', icon: Warning },
  { action: 'exception', label: '标异常', type: 'danger', icon: Close },
]

const actor = computed(() => auth.user?.username || auth.user?.id || currentActor())
const activePlatformProjectId = computed(() => {
  const routeProjectId = Array.isArray(route.query.project_id) ? route.query.project_id[0] : route.query.project_id
  return String(routeProjectId || workspace.activeProject?.id || workspace.activeProjectId || '').trim()
})
const activePhoto = computed<ReviewPhoto | undefined>(() => {
  return workspace.activePhotos.find((photo) => photo.id === activePhotoId.value) || workspace.activePhotos[0]
})
const selectedPlatformReviewWorkOrder = computed(
  () => platformReviewWorkOrders.value.find((item) => item.id === selectedPlatformReviewWorkOrderId.value) || null,
)
const activeReviewFieldReviews = computed(() => {
  const workOrder = selectedPlatformReviewWorkOrder.value
  if (!workOrder) return []
  const values = reviewWorkOrderFieldValues(workOrder)
  return workOrder.fieldReviews.filter((field) => isReviewConditionActiveForValues(field, values))
})
const activeReviewPhotoSlotReviews = computed(() => {
  const workOrder = selectedPlatformReviewWorkOrder.value
  if (!workOrder) return []
  const values = reviewWorkOrderFieldValues(workOrder)
  return workOrder.photoSlotReviews.filter((slot) => isReviewConditionActiveForValues(slot, values))
})
const missingReviewFieldLabels = computed(() => {
  const workOrder = selectedPlatformReviewWorkOrder.value
  if (!workOrder) return []
  const values = reviewWorkOrderFieldValues(workOrder)
  return activeReviewFieldReviews.value
    .filter((field) => isReviewFieldRequiredForValues(field, values) && !String(field.collectedValue || field.initialValue || '').trim())
    .map((field) => field.label || field.key)
})
const missingReviewPhotoLabels = computed(() => {
  const workOrder = selectedPlatformReviewWorkOrder.value
  if (!workOrder) return []
  const values = reviewWorkOrderFieldValues(workOrder)
  return activeReviewPhotoSlotReviews.value
    .filter((slot) => isReviewPhotoRequiredForValues(slot, values) && !slot.covered)
    .map((slot) => slot.label || slot.key)
})
const importedReviewHierarchyGapItems = computed(() => selectedPlatformReviewWorkOrder.value?.reviewHierarchyGapItems || [])
const reviewReturnReasonSuggestion = computed(() => selectedPlatformReviewWorkOrder.value?.suggestedReviewReturnReason || '')
const reviewEvidenceGapGroups = computed(() => {
  const groups: { label: string; items: string[] }[] = []
  if (missingReviewFieldLabels.value.length) groups.push({ label: '缺少字段', items: missingReviewFieldLabels.value })
  if (missingReviewPhotoLabels.value.length) groups.push({ label: '缺少照片', items: missingReviewPhotoLabels.value })
  if (importedReviewHierarchyGapItems.value.length) {
    groups.push({
      label: '导入层级缺口',
      items: importedReviewHierarchyGapItems.value.map(reviewHierarchyGapItemLabel),
    })
  }
  return groups
})
const reviewApproveBlocked = computed(() => reviewEvidenceGapGroups.value.length > 0)
const reviewFieldSections = computed<ReviewHierarchySection[]>(() => {
  const fields = activeReviewFieldReviews.value
  const sections = reviewFieldSectionsBase()
  const sectionById = new Map(sections.map((section) => [section.id, section]))
  for (const field of fields) {
    sectionById.get(reviewFieldSectionId(field))?.fields.push(field)
  }
  return sections.filter((section) => section.fields.length)
})
const reviewPhotoSections = computed<ReviewPhotoHierarchySection[]>(() => {
  const slots = activeReviewPhotoSlotReviews.value
  const sections: ReviewPhotoHierarchySection[] = [
    {
      id: 'photo-evidence',
      title: '照片证据',
      helper: '用于证明改造前、旧新设备和改造后的现场状态。',
      slots: slots.filter((slot) => slot.relationRole === 'evidence_photo'),
    },
    {
      id: 'other-photos',
      title: '其他照片',
      helper: '项目自定义的补充照片槽位。',
      slots: slots.filter((slot) => slot.relationRole !== 'evidence_photo'),
    },
  ]
  return sections.filter((section) => section.slots.length)
})
const reviewKpiEvidenceRows = computed<ReviewKpiEvidenceRow[]>(() => {
  const workOrder = selectedPlatformReviewWorkOrder.value
  if (!workOrder) return []
  const labels: Record<string, string> = {
    installer: '安装人员',
    started_at: '安装时间',
    completed_at: '完成时间',
    uploaded_at: '上传时间',
    online_duration_minutes: '在线时长（分钟）',
    photo_count: '照片数量',
    old_device_recovered: '旧设备回收',
  }
  return Object.entries(workOrder.kpiValues || {})
    .map(([key, value]) => ({ key, label: labels[key] || key, value: String(value || '').trim() }))
    .filter((row) => row.value)
})
const filteredPlatformReviewWorkOrders = computed(() => {
  if (platformReviewStatusFilter.value === 'all') return platformReviewWorkOrders.value
  return platformReviewWorkOrders.value.filter((item) => item.reviewStatus === platformReviewStatusFilter.value)
})
const platformReviewStatusOptions = computed(() => [
  { label: '全部', value: 'all' as const, count: platformReviewWorkOrders.value.length },
  { label: '待审', value: 'pending_review' as const, count: platformReviewStatusCounts.value.pending_review },
  { label: '通过', value: 'approved' as const, count: platformReviewStatusCounts.value.approved },
  { label: '退回', value: 'returned' as const, count: platformReviewStatusCounts.value.returned },
  { label: '异常', value: 'exception' as const, count: platformReviewStatusCounts.value.exception },
  { label: '未就绪', value: 'not_ready' as const, count: platformReviewStatusCounts.value.not_ready },
])

const activeProjectSchema = computed(() => workspace.activeProject?.workItemSchema)
const configuredReviewFields = computed(() => activeProjectSchema.value?.customFields || [])
const requiredReviewFields = computed(() =>
  configuredReviewFields.value.filter((field) => field.source === 'field_collection' && field.dataType !== 'image' && field.required),
)
const schemaPhotoRequirements = computed(() =>
  configuredReviewFields.value.filter((field) => field.source === 'field_collection' && field.dataType === 'image' && field.required),
)
const photoCategoryOptions = computed(() => {
  const schemaLabels = schemaPhotoRequirements.value.map((field) => field.label).filter(Boolean)
  return schemaLabels.length ? schemaLabels : ['表前', '表后', '铭牌', '其他']
})

function groupFieldValue(group: MaterialGroup | null, field: ProjectFieldDefinition) {
  if (!group) return ''
  const dynamicValue = String(group.fieldValues?.[field.key] || '').trim()
  if (dynamicValue) return dynamicValue
  if (field.key === 'collector_no' || field.key === 'collector') return group.constructionCollector || group.collector || ''
  if (field.key === 'module_asset_no' || field.key === 'communication_module_no') {
    return group.constructionModuleAssetNo || group.moduleAssetNo || ''
  }
  return ''
}

function photoMatchesRequirement(photo: ReviewPhoto, field: ProjectFieldDefinition) {
  const text = `${photo.category || ''} ${photo.categoryLabel || ''} ${photo.constructionSlot || ''} ${photo.constructionSlotLabel || ''} ${photo.archiveFilename || ''} ${photo.name || ''}`
  return text.includes(field.key) || text.includes(field.label)
}

function hasRequiredPhoto(field: ProjectFieldDefinition) {
  return workspace.activePhotos.some((photo) => photoMatchesRequirement(photo, field))
}

function reviewFieldSectionsBase(): ReviewHierarchySection[] {
  return [
    { id: 'task-core', title: '任务核心', helper: '确认本工单对象及核心详情。', fields: [] },
    { id: 'main-device-replacement', title: '主设备更换', helper: '核查本次必须更换的主设备安装结果。', fields: [] },
    { id: 'device-replacement', title: '设备/附属设备采集', helper: '核查旧设备拆回、附属新设备和其他设备编码。', fields: [] },
    { id: 'accessory-confirmation', title: '附属设备确认', helper: '核查通讯模块、SIM 卡、采集器等附属设备是否同步更换。', fields: [] },
    { id: 'conditional-accessory-fields', title: '条件补采', helper: '仅核查已触发的附属设备旧件、新件或前置字段。', fields: [] },
    { id: 'supporting-fields', title: '补充字段', helper: '补充审阅、效率统计和施工追溯所需资料。', fields: [] },
  ]
}

function isConditionalReviewField(field: PlatformReviewFieldReview) {
  return Boolean(field.requiredWhen?.fieldKey)
}

function reviewHierarchyGapItemLabel(item: PlatformReviewHierarchyGapItem) {
  const fieldLabel = item.fieldLabel || item.fieldKey || '未命名字段'
  const message = item.message && !item.message.includes(fieldLabel) ? `${fieldLabel}：${item.message}` : item.message || fieldLabel
  return item.row ? `第${item.row}行 ${message}` : message
}

function reviewWorkOrderFieldValues(workOrder: PlatformReviewWorkOrder) {
  const values: Record<string, string> = {
    ...workOrder.fieldValues,
    ...workOrder.collectionFieldValues,
    ...workOrder.kpiValues,
  }
  for (const field of workOrder.fieldReviews) {
    const initialValue = String(field.initialValue || '').trim()
    const collectedValue = String(field.collectedValue || '').trim()
    if (initialValue && !values[field.key]) values[field.key] = initialValue
    if (collectedValue) values[field.key] = collectedValue
  }
  return values
}

function reviewConditionMatches(
  item: Pick<PlatformReviewFieldReview, 'requiredWhen'> | Pick<PlatformReviewPhotoSlotReview, 'requiredWhen'>,
  values: Record<string, string>,
) {
  const requiredWhen = item.requiredWhen
  const fieldKey = requiredWhen?.fieldKey
  const expected = requiredWhen?.equals
  const current = fieldKey ? String(values[fieldKey] || '').trim() : ''
  if (!expected || !current) return false
  return Array.isArray(expected) ? expected.map(String).includes(current) : current === String(expected)
}

function isReviewConditionActiveForValues(
  item: Pick<PlatformReviewFieldReview, 'requiredWhen'> | Pick<PlatformReviewPhotoSlotReview, 'requiredWhen'>,
  values: Record<string, string>,
) {
  if (!item.requiredWhen?.fieldKey) return true
  return reviewConditionMatches(item, values)
}

function isReviewFieldRequiredForValues(field: PlatformReviewFieldReview, values: Record<string, string>) {
  return Boolean(isReviewConditionActiveForValues(field, values) && (field.required || reviewConditionMatches(field, values)))
}

function isReviewPhotoRequiredForValues(slot: PlatformReviewPhotoSlotReview, values: Record<string, string>) {
  return Boolean(isReviewConditionActiveForValues(slot, values) && (slot.required || reviewConditionMatches(slot, values)))
}

function reviewFieldSectionId(field: PlatformReviewFieldReview): ReviewHierarchySection['id'] {
  if (field.relationRole === 'task_object' || field.relationRole === 'task_detail') return 'task-core'
  if (isConditionalReviewField(field)) return 'conditional-accessory-fields'
  if (field.relationRole === 'replacement_device') return 'main-device-replacement'
  if (field.relationRole === 'accessory_replace_confirm') return 'accessory-confirmation'
  if (field.relationRole === 'old_device' || field.relationRole === 'accessory_new_device') return 'device-replacement'
  return 'supporting-fields'
}

function reviewRelationRoleLabel(role: ProjectFieldDefinition['relationRole'] | undefined) {
  const labels: Record<NonNullable<ProjectFieldDefinition['relationRole']>, string> = {
    aggregate: '聚合字段',
    task_object: '任务对象',
    task_detail: '核心详情',
    replacement_device: '主设备 · 更换后',
    old_device: '旧设备 · 拆回',
    accessory_replace_confirm: '附属设备 · 是否更换',
    accessory_new_device: '附属设备 · 新设备',
    evidence_photo: '照片证据',
    supporting_field: '补充字段',
  }
  return role ? labels[role] || '补充字段' : '补充字段'
}

function isReviewKpiEvidenceKey(key: string | undefined) {
  return Boolean(
    key &&
      ['installer', 'started_at', 'completed_at', 'uploaded_at', 'online_duration_minutes', 'photo_count', 'old_device_recovered'].includes(key),
  )
}

function reviewEvidenceIntentLabel(item: ReviewEvidenceIntentItem) {
  if (item.requiredWhen?.fieldKey) return '条件补采'
  if (item.relationRole === 'replacement_device') return '主设备本体'
  if (item.relationRole === 'accessory_replace_confirm') return '附属设备确认'
  if (item.relationRole === 'old_device' || item.relationRole === 'accessory_new_device') return '任务对象下的附属设备'
  if (item.relationRole === 'evidence_photo') return '照片证据'
  if (isReviewKpiEvidenceKey(item.key)) return 'KPI资料'
  if (item.relationRole === 'task_object' || item.relationRole === 'task_detail') return '任务核心'
  return '补充资料'
}

function reviewEvidenceIntentType(item: ReviewEvidenceIntentItem): '' | 'success' | 'warning' | 'danger' | 'info' {
  if (item.requiredWhen?.fieldKey) return 'warning'
  if (item.relationRole === 'replacement_device') return 'danger'
  if (item.relationRole === 'accessory_replace_confirm') return 'warning'
  if (item.relationRole === 'old_device' || item.relationRole === 'accessory_new_device') return 'success'
  if (item.relationRole === 'evidence_photo' || isReviewKpiEvidenceKey(item.key)) return 'info'
  return ''
}

function reviewConditionLabel(field: PlatformReviewFieldReview | PlatformReviewPhotoSlotReview) {
  const requiredWhen = field.requiredWhen
  const fieldKey = requiredWhen?.fieldKey
  if (!fieldKey) return ''
  const equals = Array.isArray(requiredWhen.equals) ? requiredWhen.equals.join('/') : requiredWhen.equals
  return `${fieldKey} = ${equals || '指定值'} 时需核查`
}

function platformReviewHistoryActionLabel(action: string) {
  const labels: Record<string, string> = {
    approved: '通过',
    returned: '退回',
    exception: '标异常',
    rework_submitted: '返工重新提交',
  }
  return labels[action] || action || '记录'
}

function platformReviewHistoryDetail(event: PlatformReviewWorkOrder['reviewHistory'][number]) {
  if (event.reason === 'returned_rework_resubmitted') {
    return event.note || '返工补采后重新提交审阅'
  }
  return event.note || event.reason
}

const reviewChecklist = computed(() => {
  const fieldItems = requiredReviewFields.value.map((field) => {
    const value = groupFieldValue(workspace.activeGroup, field)
    return {
      key: field.key,
      label: field.label,
      passed: Boolean(value),
      detail: value || '未采集',
    }
  })
  const photoItems = schemaPhotoRequirements.value.map((field) => ({
    key: field.key,
    label: field.label,
    passed: hasRequiredPhoto(field),
    detail: hasRequiredPhoto(field) ? '已上传' : '缺照片',
  }))
  if (!fieldItems.length && !photoItems.length && workspace.activeProject?.name === '更换终端') {
    return terminalReplacementReviewLabels.map((label) => ({ key: label, label, passed: false, detail: '待配置' }))
  }
  return [...fieldItems, ...photoItems]
})
const missingReviewItems = computed(() => reviewChecklist.value.filter((item) => !item.passed).map((item) => item.label))
const canCompleteReview = computed(() => missingReviewItems.value.length === 0)

watch(
  () => route.params.groupId,
  async (groupId) => {
    await workspace.loadReviewGroup(String(groupId || 'g-001'))
    activePhotoId.value = workspace.activePhotos[0]?.id || ''
  },
  { immediate: true },
)

onMounted(() => {
  workspace.selectRouteProject(route.query.project_id)
  if (!workspace.groups.length) {
    void workspace.bootstrap()
  }
})

watch(
  activePlatformProjectId,
  () => {
    void loadPlatformReviewWorkOrders()
  },
  { immediate: true },
)

async function save(status: TaskStatus) {
  if (status === 'complete' && !canCompleteReview.value) {
    ElMessage.warning(`仍缺少：${missingReviewItems.value.join('、')}`)
    return
  }
  await workspace.saveReview(status)
  ElMessage.success('审阅状态已保存到占位接口')
}

function openGroup(group: MaterialGroup) {
  void router.push(`/review/${group.id}`)
}

async function loadPlatformReviewWorkOrders() {
  const projectId = activePlatformProjectId.value
  if (!projectId) return
  loadingPlatformReview.value = true
  try {
    const payload = await fetchProjectReviewWorkOrders(projectId)
    platformReviewWorkOrders.value = payload.items
    platformReviewStatusCounts.value = payload.statusCounts
    if (!filteredPlatformReviewWorkOrders.value.some((item) => item.id === selectedPlatformReviewWorkOrderId.value)) {
      selectedPlatformReviewWorkOrderId.value = filteredPlatformReviewWorkOrders.value[0]?.id || ''
    }
  } catch (error) {
    platformReviewWorkOrders.value = []
    selectedPlatformReviewWorkOrderId.value = ''
    ElMessage.error(error instanceof Error ? error.message : '平台审阅工单加载失败')
  } finally {
    loadingPlatformReview.value = false
  }
}

function selectPlatformReviewWorkOrder(workOrder: PlatformReviewWorkOrder) {
  selectedPlatformReviewWorkOrderId.value = workOrder.id
}

function selectPlatformReviewStatus(status: PlatformReviewStatusFilter) {
  platformReviewStatusFilter.value = status
  if (!filteredPlatformReviewWorkOrders.value.some((item) => item.id === selectedPlatformReviewWorkOrderId.value)) {
    selectedPlatformReviewWorkOrderId.value = filteredPlatformReviewWorkOrders.value[0]?.id || ''
  }
}

function applyReviewReturnReasonSuggestion() {
  if (!reviewReturnReasonSuggestion.value) return
  reviewNote.value = reviewReturnReasonSuggestion.value
}

async function submitPlatformReviewAction(action: PlatformReviewActionPayload['action']) {
  const projectId = activePlatformProjectId.value
  const workOrder = selectedPlatformReviewWorkOrder.value
  if (!projectId || !workOrder) return
  if (action === 'approved' && reviewApproveBlocked.value) {
    ElMessage.warning(`仍缺少：${reviewEvidenceGapGroups.value.map((group) => `${group.label} ${group.items.join('、')}`).join('；')}`)
    return
  }
  const note = reviewNote.value.trim() || (action === 'returned' ? reviewReturnReasonSuggestion.value : '')
  await reviewProjectReviewWorkOrder(projectId, workOrder.id, {
    actor: actor.value,
    action,
    note,
    reason: action === 'approved' ? '' : note,
  })
  ElMessage.success('平台审阅状态已更新')
  selectedPlatformReviewWorkOrderId.value = workOrder.id
  await loadPlatformReviewWorkOrders()
}
</script>

<template>
  <div class="review-grid" v-loading="workspace.loading">
    <section class="panel review-column">
      <div class="panel-header">
        <h3>资料组队列</h3>
        <ElButton :icon="Refresh" circle size="small" :loading="loadingPlatformReview" @click="loadPlatformReviewWorkOrders" />
      </div>
      <div class="panel-body review-list">
        <div v-if="activePlatformProjectId" class="platform-review-block">
          <div class="platform-review-title">
            <strong>平台接入审阅</strong>
            <ElTag size="small" effect="plain">{{ filteredPlatformReviewWorkOrders.length }}</ElTag>
          </div>
          <div class="platform-review-filter">
            <button
              v-for="status in platformReviewStatusOptions"
              :key="status.value"
              type="button"
              :class="{ active: platformReviewStatusFilter === status.value }"
              @click="selectPlatformReviewStatus(status.value)"
            >
              <span>{{ status.label }}</span>
              <strong>{{ status.count }}</strong>
            </button>
          </div>
          <div
            v-for="workOrder in filteredPlatformReviewWorkOrders"
            :key="workOrder.id"
            class="platform-review-work-order"
            :class="{ active: workOrder.id === selectedPlatformReviewWorkOrderId }"
            @click="selectPlatformReviewWorkOrder(workOrder)"
          >
            <strong>{{ workOrder.primaryValue || workOrder.id }}</strong>
            <p class="muted">{{ workOrder.aggregateValue || '未填写聚合字段' }}</p>
            <ElTag size="small" effect="plain">{{ workOrder.reviewStatus || 'not_ready' }}</ElTag>
          </div>
          <ElEmpty v-if="!loadingPlatformReview && !filteredPlatformReviewWorkOrders.length" description="暂无平台审阅工单" />
        </div>
        <div
          v-for="group in workspace.groups"
          :key="group.id"
          class="queue-item"
          :class="{ active: group.id === workspace.activeGroup?.id }"
          @click="openGroup(group)"
        >
          <strong>{{ group.meterNo }}</strong>
          <p class="muted">{{ group.address }}</p>
          <StatusTag :status="group.status" />
        </div>
      </div>
    </section>

    <section class="image-stage">
      <img v-if="activePhoto" :src="activePhoto.url" :alt="activePhoto.name" />
      <ElEmpty v-else description="暂无照片" />
    </section>

    <section class="panel review-column">
      <div class="panel-header">
        <h3>审阅信息</h3>
        <StatusTag v-if="workspace.activeGroup" :status="workspace.activeGroup.status" />
      </div>
      <div class="panel-body page-stack">
        <div v-if="selectedPlatformReviewWorkOrder" class="platform-review-detail">
          <div class="platform-review-detail-header">
            <div>
              <h3>{{ selectedPlatformReviewWorkOrder.primaryValue || selectedPlatformReviewWorkOrder.id }}</h3>
              <p class="muted">{{ selectedPlatformReviewWorkOrder.aggregateValue || '未填写聚合字段' }}</p>
            </div>
            <ElTag effect="light">{{ selectedPlatformReviewWorkOrder.reviewStatus || 'not_ready' }}</ElTag>
          </div>

          <ElDescriptions :column="1" border size="small">
            <ElDescriptionsItem label="采集状态">{{ selectedPlatformReviewWorkOrder.collectionStatus || '-' }}</ElDescriptionsItem>
            <ElDescriptionsItem label="采集人员">{{ selectedPlatformReviewWorkOrder.collectedBy || '-' }}</ElDescriptionsItem>
            <ElDescriptionsItem label="采集时间">{{ selectedPlatformReviewWorkOrder.collectedAt || '-' }}</ElDescriptionsItem>
            <ElDescriptionsItem label="照片数">{{ selectedPlatformReviewWorkOrder.collectionPhotos.length }}</ElDescriptionsItem>
          </ElDescriptions>

          <div v-if="reviewEvidenceGapGroups.length" class="platform-review-gap">
            <strong>审阅证据缺口</strong>
            <span v-for="group in reviewEvidenceGapGroups" :key="group.label">{{ group.label }}：{{ group.items.join('、') }}</span>
          </div>

          <div class="platform-review-actions">
            <ElButton
              v-for="{ action, label, type, icon } in platformReviewActions"
              :key="action"
              :type="type"
              :icon="icon"
              :disabled="action === 'approved' && (selectedPlatformReviewWorkOrder.reviewStatus === 'approved' || reviewApproveBlocked)"
              @click="submitPlatformReviewAction(action)"
            >
              {{ label }}
            </ElButton>
          </div>

          <div class="platform-review-history">
            <h3>审阅记录</h3>
            <div v-for="event in selectedPlatformReviewWorkOrder.reviewHistory" :key="event.id" class="platform-review-history-row">
              <span>{{ platformReviewHistoryActionLabel(event.action) }}</span>
              <small>{{ event.actor }} / {{ event.reviewedAt }}</small>
              <p v-if="platformReviewHistoryDetail(event)">{{ platformReviewHistoryDetail(event) }}</p>
            </div>
            <ElEmpty v-if="!selectedPlatformReviewWorkOrder.reviewHistory.length" description="暂无审阅记录" />
          </div>

          <div class="platform-review-fields">
            <h3>字段审阅</h3>
            <section
              v-for="section in reviewFieldSections"
              :key="section.id"
              class="platform-review-section"
              :class="`platform-review-section-${section.id}`"
            >
              <div class="platform-review-section-head">
                <h4>{{ section.title }}</h4>
                <p>{{ section.helper }}</p>
              </div>
              <div v-for="field in section.fields" :key="field.key" class="platform-review-field">
                <span class="platform-review-field-title">
                  {{ field.label }}
                  <ElTag class="platform-review-role-tag" size="small" effect="plain">
                    {{ reviewRelationRoleLabel(field.relationRole) }}
                  </ElTag>
                  <ElTag
                    class="platform-review-intent-tag"
                    size="small"
                    :type="reviewEvidenceIntentType(field)"
                    effect="light"
                    title="审阅证据意图"
                  >
                    {{ reviewEvidenceIntentLabel(field) }}
                  </ElTag>
                  <small v-if="field.requiredWhen?.fieldKey" class="platform-review-condition-hint">
                    {{ reviewConditionLabel(field) }}
                  </small>
                </span>
                <strong>{{ field.collectedValue || field.initialValue || '-' }}</strong>
              </div>
            </section>
          </div>

          <div class="platform-review-fields">
            <h3>照片槽位</h3>
            <section v-for="photoSection in reviewPhotoSections" :key="photoSection.id" class="platform-review-section">
              <div class="platform-review-section-head">
                <h4>{{ photoSection.title }}</h4>
                <p>{{ photoSection.helper }}</p>
              </div>
              <div v-for="slot in photoSection.slots" :key="slot.key" class="platform-review-field">
                <span class="platform-review-field-title">
                  {{ slot.label }}
                  <ElTag class="platform-review-role-tag" size="small" effect="plain">
                    {{ reviewRelationRoleLabel(slot.relationRole) }}
                  </ElTag>
                  <ElTag
                    class="platform-review-intent-tag"
                    size="small"
                    :type="reviewEvidenceIntentType(slot)"
                    effect="light"
                    title="审阅证据意图"
                  >
                    {{ reviewEvidenceIntentLabel(slot) }}
                  </ElTag>
                  <small v-if="slot.requiredWhen?.fieldKey" class="platform-review-condition-hint">
                    {{ reviewConditionLabel(slot) }}
                  </small>
                </span>
                <ElTag size="small" :type="slot.covered ? 'success' : slot.required ? 'danger' : 'info'">
                  {{ slot.covered ? `已上传 ${slot.photoCount}` : slot.required ? '缺照片' : '非必填' }}
                </ElTag>
              </div>
            </section>
          </div>

          <div v-if="reviewKpiEvidenceRows.length" class="platform-review-fields">
            <h3>KPI资料</h3>
            <section class="platform-review-section platform-review-section-kpi-evidence">
              <div class="platform-review-section-head">
                <h4>施工效率资料</h4>
                <p>核查安装人员、安装时间、在线时长和旧设备回收等效率计算资料。</p>
              </div>
              <div v-for="row in reviewKpiEvidenceRows" :key="row.key" class="platform-review-field">
                <span class="platform-review-field-title">
                  {{ row.label }}
                  <ElTag
                    class="platform-review-intent-tag"
                    size="small"
                    :type="reviewEvidenceIntentType(row)"
                    effect="light"
                    title="审阅证据意图"
                  >
                    {{ reviewEvidenceIntentLabel(row) }}
                  </ElTag>
                </span>
                <strong>{{ row.value }}</strong>
              </div>
            </section>
          </div>
        </div>

        <ElDescriptions v-if="workspace.activeGroup" :column="1" border size="small">
          <ElDescriptionsItem label="安装地址">{{ workspace.activeGroup.address }}</ElDescriptionsItem>
          <ElDescriptionsItem label="原始表号">{{ workspace.activeGroup.meterNo }}</ElDescriptionsItem>
          <ElDescriptionsItem label="终端">{{ workspace.activeGroup.terminal }}</ElDescriptionsItem>
          <ElDescriptionsItem label="照片数">{{ workspace.activeGroup.photoCount }}</ElDescriptionsItem>
        </ElDescriptions>

        <div v-if="reviewChecklist.length" class="schema-review">
          <h3>资料完整性</h3>
          <div class="schema-check-list">
            <div v-for="item in reviewChecklist" :key="item.key" class="schema-check-item" :class="{ passed: item.passed }">
              <span>{{ item.label }}</span>
              <ElTag size="small" :type="item.passed ? 'success' : 'danger'">{{ item.detail }}</ElTag>
            </div>
          </div>
        </div>

        <div>
          <h3>照片分类</h3>
          <ElSegmented
            v-model="activePhotoId"
            :options="workspace.activePhotos.map((photo) => ({ label: photo.name, value: photo.id }))"
            block
          />
        </div>

        <ElRadioGroup v-model="photoCategory">
          <ElRadioButton v-for="label in photoCategoryOptions" :key="label" :label="label" />
        </ElRadioGroup>

        <div v-if="reviewReturnReasonSuggestion" class="platform-review-return-suggestion">
          <span>建议退回原因：{{ reviewReturnReasonSuggestion }}</span>
          <ElButton size="small" text type="warning" @click="applyReviewReturnReasonSuggestion">采用缺口原因</ElButton>
        </div>

        <ElInput v-model="reviewNote" type="textarea" :rows="4" placeholder="异常说明或补充备注" />

        <div class="toolbar">
          <ElButton
            v-for="{ status, label, type, icon } in reviewActions"
            :key="status"
            :type="type"
            :icon="icon"
            :disabled="status === 'complete' && !canCompleteReview"
            @click="save(status)"
          >
            {{ label }}
          </ElButton>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.platform-review-block,
.platform-review-detail,
.platform-review-fields,
.platform-review-history,
.platform-review-section {
  display: grid;
  gap: 10px;
}

.platform-review-block {
  padding-bottom: 12px;
  border-bottom: 1px solid #e5e7eb;
}

.platform-review-title,
.platform-review-detail-header,
.platform-review-field,
.platform-review-history-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.platform-review-detail-header h3,
.platform-review-fields h3,
.platform-review-history h3 {
  margin: 0;
}

.platform-review-section {
  padding: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fbfcfe;
}

.platform-review-section-main-device-replacement {
  border-color: #f4b4aa;
  background: #fff8f6;
}

.platform-review-section-device-replacement {
  border-color: #bddfd0;
  background: #f7fcf9;
}

.platform-review-section-accessory-confirmation {
  border-color: #f3d28f;
  background: #fffaf0;
}

.platform-review-section-conditional-accessory-fields {
  border-color: #f3d28f;
  background: #fffdf7;
}

.platform-review-section-task-core {
  border-color: #d8c9f7;
  background: #fbf9ff;
}

.platform-review-section-head {
  display: grid;
  gap: 2px;
}

.platform-review-section-head h4,
.platform-review-section-head p {
  margin: 0;
}

.platform-review-section-head h4 {
  font-size: 14px;
  color: #1f2937;
}

.platform-review-section-head p {
  font-size: 12px;
  color: #667085;
}

.platform-review-condition-hint {
  display: block;
  margin-top: 3px;
  color: #9a6700;
  font-size: 12px;
  font-weight: 800;
  line-height: 1.35;
}

.platform-review-filter {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.platform-review-filter button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 34px;
  padding: 6px 8px;
  border: 1px solid #d7dde8;
  border-radius: 6px;
  background: #fff;
  color: #344054;
  cursor: pointer;
}

.platform-review-filter button.active {
  border-color: #409eff;
  background: #ecf5ff;
  color: #1d4ed8;
}

.platform-review-gap {
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid #ffd5d2;
  border-radius: 6px;
  background: #fff5f4;
  color: #b42318;
  font-size: 13px;
  line-height: 1.5;
}

.platform-review-gap strong,
.platform-review-gap span {
  overflow-wrap: anywhere;
}

.platform-review-return-suggestion {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #f5d29a;
  border-radius: 6px;
  background: #fff8ec;
  color: #92400e;
  font-size: 13px;
  line-height: 1.5;
}

.platform-review-return-suggestion span {
  overflow-wrap: anywhere;
}

.platform-review-work-order {
  display: grid;
  gap: 5px;
  padding: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
}

.platform-review-work-order.active {
  border-color: #409eff;
  background: #f5f9ff;
}

.platform-review-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.platform-review-field,
.platform-review-history-row {
  min-height: 34px;
  padding: 8px 10px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
}

.platform-review-field span,
.platform-review-history-row span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.platform-review-field-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.platform-review-role-tag,
.platform-review-intent-tag {
  flex: 0 0 auto;
}

.platform-review-field strong {
  text-align: right;
  overflow-wrap: anywhere;
}

.platform-review-history-row {
  align-items: flex-start;
  flex-direction: column;
}

.platform-review-history-row p {
  margin: 0;
}

.schema-review {
  display: grid;
  gap: 10px;
}

.schema-review h3 {
  margin: 0;
  font-size: 15px;
}

.schema-check-list {
  display: grid;
  gap: 8px;
}

.schema-check-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 34px;
  padding: 8px 10px;
  border: 1px solid #f1c4c4;
  border-radius: 6px;
  background: #fff8f8;
}

.schema-check-item.passed {
  border-color: #b8dfc5;
  background: #f6fbf7;
}

.schema-check-item span {
  min-width: 0;
  font-size: 13px;
  overflow-wrap: anywhere;
}
</style>
