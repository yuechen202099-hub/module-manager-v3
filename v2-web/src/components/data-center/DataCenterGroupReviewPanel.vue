<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { CircleCheck, FolderChecked, Refresh, Warning } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  classifyDataCenterGroupPhoto,
  confirmDataCenterGroupClassification,
  confirmDataCenterGroupBarcode,
  fetchDataCenterDetail,
  fetchGroupPhotoObjectUrl,
  getApiErrorStatus,
  rescanDataCenterGroupPhotoBarcode,
  resetAdminGroupToUnconstructed,
  resetAdminGroupToUnreviewed,
  resolveDataCenterGroupAnomaly,
  returnDataCenterGroupToException,
  reviewDataCenterGroup,
  scanDataCenterGroupPhotoRegion,
  updateDataCenterGroup,
} from '@/api/services'
import type {
  DataCenterDetail,
  GlobalMeterInstallWorkbenchRow,
  RegionScanResult,
} from '@/api/types'
import Code128Barcode from '@/components/Code128Barcode.vue'
import PhotoLightbox from '@/components/PhotoLightbox.vue'
import ReviewImageInspector from '@/components/ReviewImageInspector.vue'

const props = withDefaults(defineProps<{
  groupId: string
  rephotoItem?: GlobalMeterInstallWorkbenchRow | null
  defaultStage?: 'source' | 'rephoto'
  classificationOnly?: boolean
}>(), { rephotoItem: null, defaultStage: 'source', classificationOnly: false })

const emit = defineEmits<{
  (event: 'updated', detail: DataCenterDetail): void
  (event: 'review-decided', status: 'approved' | 'incomplete' | 'exception'): void
}>()

const loading = ref(false)
const saving = ref(false)
const imageLoading = ref(false)
const detail = ref<DataCenterDetail | null>(null)
const selectedPhotoId = ref('')
const errorMessage = ref('')
const photoPreview = ref({ src: '', alt: '' })
const inspector = ref<InstanceType<typeof ReviewImageInspector> | null>(null)
const photoObjectUrls = reactive(new Map<string, string>())
const pendingCategories = reactive<Record<string, string>>({})
const activeStage = ref<'source' | 'rephoto'>(props.rephotoItem ? props.defaultStage : 'source')
let detailAbortController: AbortController | null = null
let photoAbortController: AbortController | null = null
let largePhotoAbortController: AbortController | null = null
let largePhotoObjectUrl = ''
let detailSerial = 0
let photoSerial = 0
let groupSerial = 0
let mutationSerial = 0

type MutationOwner = {
  token: number
  groupId: string
  groupSerial: number
}

let activeMutationOwner: MutationOwner | null = null

const form = reactive({
  meterNo: '',
  collector: '',
  moduleAssetNo: '',
  reason: '',
  exceptionCategory: 'barcode_error',
  exceptionNote: '',
  resetReason: '',
})

const activePhoto = computed(() => detail.value?.photos.find((photo) => photo.id === selectedPhotoId.value) || null)
const activePhotoUrl = computed(() => activePhoto.value ? photoObjectUrls.get(activePhoto.value.id) || '' : '')
const categoryOptions = [
  { value: 'before_box', label: '施工前' },
  { value: 'collector_barcode', label: '采集器条码' },
  { value: 'module_meter', label: '模块表号' },
  { value: 'after_box', label: '施工后' },
  { value: 'other', label: '其他' },
]
const classificationCategoryOptions = [
  { value: 'before_box', label: '表箱整体改造前' },
  { value: 'collector_barcode', label: '采集器条形码' },
  { value: 'module_meter', label: '模块与电能表' },
  { value: 'after_box', label: '表箱整体改造后' },
]
const classificationCategoryValues = new Set(classificationCategoryOptions.map((item) => item.value))
const classificationCompletedCount = computed(() => Object.values(pendingCategories)
  .filter((category) => classificationCategoryValues.has(category)).length)
const classificationTotalCount = computed(() => detail.value?.photos.length || 0)
const classificationChanges = computed(() => detail.value?.photos.flatMap((photo) => {
  const category = pendingCategories[photo.id] || 'unclassified'
  return category !== photo.category && classificationCategoryValues.has(category)
    ? [{ photoId: photo.id, category }]
    : []
}) || [])
const hasManualClassificationConfirmation = computed(
  () => Boolean(detail.value?.classificationManualConfirmation),
)
const manualClassificationWarnings = computed(() => {
  if (!detail.value) return []
  if (detail.value.anomalies.length) {
    return detail.value.anomalies
      .filter((anomaly) => anomaly.status === 'open')
      .map((anomaly) => anomaly.message)
  }
  const warnings: string[] = []
  const categories = detail.value.photos.map((photo) => photo.category || 'unclassified')
  const unclassifiedCount = categories.filter((category) => !classificationCategoryValues.has(category)).length
  if (unclassifiedCount) warnings.push(`仍有 ${unclassifiedCount} 张照片未分类`)
  for (const [category, label] of [['module_meter', '电表和模块照片'], ['after_box', '改造完成照片']] as const) {
    const count = categories.filter((value) => value === category).length
    if (count === 0) warnings.push(`缺少${label}`)
    else if (count > 1) warnings.push(`${label}存在重复分类`)
  }
  if (!['passed', 'manual', 'manual_confirmed', 'manual_passed'].includes(detail.value.barcodeStatus)) {
    warnings.push('条码状态未通过')
  }
  for (const [value, label] of [
    [detail.value.terminal, '终端号'],
    [detail.value.meterNo, '表号'],
    [detail.value.moduleAssetNo, '模块号'],
    [detail.value.collector, '采集器号'],
    [detail.value.address, '安装地址'],
  ] as const) {
    if (!value.trim()) warnings.push(`缺少${label}`)
  }
  if (['open', 'exception', 'rejected'].includes(detail.value.exceptionStatus.toLowerCase())) {
    warnings.push('资料存在未关闭异常')
  }
  return warnings
})
const rephotoSlots = computed(() => {
  const definitions: Array<{ slot: 'module_meter' | 'after_box'; label: string }> = [
    { slot: 'module_meter', label: '电表和模块照片' },
    { slot: 'after_box', label: '改造完成照片' },
  ]
  return definitions.map((definition) => ({
    ...definition,
    photo: props.rephotoItem?.photos.find((item) => item.slot === definition.slot)?.photo || null,
  }))
})

function rephotoImageUrl(photo: { image_url?: string; preview_url?: string; thumbnail_url?: string; canonical_image_url?: string } | null) {
  return photo?.preview_url || photo?.image_url || photo?.thumbnail_url || photo?.canonical_image_url || ''
}

function isAbortError(error: unknown) {
  return error instanceof Error && error.name === 'AbortError'
}

function revokeAllPhotoUrls() {
  photoObjectUrls.forEach((url) => URL.revokeObjectURL(url))
  photoObjectUrls.clear()
}

function closePhotoPreview() {
  largePhotoAbortController?.abort()
  largePhotoAbortController = null
  if (largePhotoObjectUrl) URL.revokeObjectURL(largePhotoObjectUrl)
  largePhotoObjectUrl = ''
  photoPreview.value = { src: '', alt: '' }
}

async function openProtectedPhoto(photo: DataCenterDetail['photos'][number]) {
  if (!detail.value) return
  closePhotoPreview()
  const groupId = detail.value.id
  const fallbackUrl = photoObjectUrls.get(photo.id) || ''
  const alt = photo.categoryLabel || photo.name || '待分类照片'
  photoPreview.value = { src: fallbackUrl, alt }
  const controller = new AbortController()
  largePhotoAbortController = controller
  try {
    const originalUrl = await fetchGroupPhotoObjectUrl(groupId, photo.id, 'original', '', controller.signal)
    if (controller.signal.aborted || detail.value?.id !== groupId) {
      if (originalUrl !== fallbackUrl) URL.revokeObjectURL(originalUrl)
      return
    }
    if (originalUrl !== fallbackUrl) largePhotoObjectUrl = originalUrl
    photoPreview.value = { src: originalUrl, alt }
  } catch (error) {
    if (!isAbortError(error) && !fallbackUrl) errorMessage.value = '大图加载失败，请重试'
  }
}

function openRephotoPreview(src: string, alt: string) {
  closePhotoPreview()
  if (src) photoPreview.value = { src, alt }
}

function cleanupDetail() {
  groupSerial += 1
  mutationSerial += 1
  activeMutationOwner = null
  detailSerial += 1
  photoSerial += 1
  detailAbortController?.abort()
  detailAbortController = null
  photoAbortController?.abort()
  photoAbortController = null
  closePhotoPreview()
  revokeAllPhotoUrls()
  detail.value = null
  selectedPhotoId.value = ''
  errorMessage.value = ''
  loading.value = false
  imageLoading.value = false
  saving.value = false
}

function beginMutation(groupId: string): MutationOwner {
  const owner = { token: ++mutationSerial, groupId, groupSerial }
  activeMutationOwner = owner
  saving.value = true
  return owner
}

function isCurrentMutation(owner: MutationOwner) {
  return activeMutationOwner?.token === owner.token
    && props.groupId === owner.groupId
    && groupSerial === owner.groupSerial
}

function finishMutation(owner: MutationOwner) {
  if (!isCurrentMutation(owner)) return
  activeMutationOwner = null
  saving.value = false
}

function showMutationError(owner: MutationOwner, error: unknown, fallback: string) {
  if (isCurrentMutation(owner)) ElMessage.error(error instanceof Error ? error.message : fallback)
}

function applyDetail(next: DataCenterDetail) {
  detail.value = next
  form.meterNo = next.meterNo
  form.collector = next.collector
  form.moduleAssetNo = next.moduleAssetNo
  if (!next.photos.some((photo) => photo.id === selectedPhotoId.value)) {
    selectedPhotoId.value = next.photos[0]?.id || ''
  }
  for (const photoId of Object.keys(pendingCategories)) delete pendingCategories[photoId]
  for (const photo of next.photos) pendingCategories[photo.id] = photo.category || 'unclassified'
}

async function loadDetail(): Promise<DataCenterDetail | null> {
  const requestedGroupId = props.groupId
  const current = ++detailSerial
  detailAbortController?.abort()
  const controller = new AbortController()
  detailAbortController = controller
  loading.value = true
  errorMessage.value = ''
  try {
    const next = await fetchDataCenterDetail('group', requestedGroupId, controller.signal)
    if (current !== detailSerial || requestedGroupId !== props.groupId) return null
    applyDetail(next)
    void loadPhotoObjectUrls(next, current)
    return next
  } catch (error) {
    if (current !== detailSerial || isAbortError(error)) return null
    errorMessage.value = error instanceof Error ? error.message : '详情加载失败'
    return null
  } finally {
    if (current === detailSerial) loading.value = false
  }
}

async function loadPhotoObjectUrls(next: DataCenterDetail, ownerSerial: number) {
  const current = ++photoSerial
  photoAbortController?.abort()
  const controller = new AbortController()
  photoAbortController = controller
  imageLoading.value = true
  revokeAllPhotoUrls()
  try {
    await Promise.all(next.photos.map(async (photo) => {
      let objectUrl = ''
      try {
        objectUrl = await fetchGroupPhotoObjectUrl(next.id, photo.id, 'preview', '', controller.signal)
        if (current !== photoSerial || ownerSerial !== detailSerial || props.groupId !== next.id) {
          URL.revokeObjectURL(objectUrl)
          return
        }
        const replaced = photoObjectUrls.get(photo.id)
        if (replaced && replaced !== objectUrl) URL.revokeObjectURL(replaced)
        photoObjectUrls.set(photo.id, objectUrl)
      } catch (error) {
        if (!isAbortError(error) && objectUrl) URL.revokeObjectURL(objectUrl)
      }
    }))
  } finally {
    if (current === photoSerial) imageLoading.value = false
  }
}

async function reloadAfterMutation(owner: MutationOwner) {
  if (!isCurrentMutation(owner)) return null
  const next = await loadDetail()
  if (!next || !isCurrentMutation(owner)) return null
  emit('updated', next)
  return next
}

async function saveFields() {
  if (!detail.value) return
  const currentDetail = detail.value
  const owner = beginMutation(currentDetail.id)
  try {
    const patch: Record<string, string> = {}
    if (form.meterNo.trim() !== currentDetail.meterNo) patch.meter_no = form.meterNo.trim()
    if (form.collector.trim() !== currentDetail.collector) patch.collector = form.collector.trim()
    if (form.moduleAssetNo.trim() !== currentDetail.moduleAssetNo) patch.module_asset_no = form.moduleAssetNo.trim()
    const result = await updateDataCenterGroup(currentDetail.id, patch, form.reason.trim() || '数据中台字段修正')
    if (!isCurrentMutation(owner)) return
    ElMessage.success(result.changedFields.length ? '已保存字段修正' : '没有字段变化')
    await reloadAfterMutation(owner)
  } catch (error) {
    showMutationError(owner, error, '保存失败')
  } finally {
    finishMutation(owner)
  }
}

async function classifyActivePhoto(category: string) {
  if (!detail.value || !activePhoto.value) return
  const groupId = detail.value.id
  const photoId = activePhoto.value.id
  const owner = beginMutation(groupId)
  try {
    await classifyDataCenterGroupPhoto(groupId, photoId, category, form.reason.trim() || '数据中台照片分类')
    if (!isCurrentMutation(owner)) return
    ElMessage.success('已分类')
    await reloadAfterMutation(owner)
  } catch (error) {
    showMutationError(owner, error, '分类失败')
  } finally {
    finishMutation(owner)
  }
}

function setPendingCategory(photoId: string, event: Event) {
  pendingCategories[photoId] = (event.target as HTMLSelectElement).value
}

async function saveClassifications() {
  if (!detail.value || !classificationChanges.value.length) return
  const currentDetail = detail.value
  const changes = [...classificationChanges.value]
  const owner = beginMutation(currentDetail.id)
  try {
    for (const change of changes) {
      await classifyDataCenterGroupPhoto(
        currentDetail.id,
        change.photoId,
        change.category,
        '审阅与翻拍照片分类',
      )
      if (!isCurrentMutation(owner)) return
    }
    ElMessage.success('照片分类已保存')
    await reloadAfterMutation(owner)
  } catch (error) {
    showMutationError(owner, error, '分类保存失败')
  } finally {
    finishMutation(owner)
  }
}

async function confirmClassificationComplete() {
  if (!detail.value || classificationChanges.value.length) return
  const currentDetail = detail.value
  const warnings = [...manualClassificationWarnings.value]
  const owner = beginMutation(currentDetail.id)
  try {
    if (warnings.length) {
      try {
        await ElMessageBox.confirm(
          `检测到以下异常：\n${warnings.map((warning) => `• ${warning}`).join('\n')}\n\n是否仍由人工确认分类完成？`,
          '异常分类确认',
          {
            type: 'warning',
            confirmButtonText: '确认分类完成',
            cancelButtonText: '返回检查',
          },
        )
      } catch {
        return
      }
    }
    if (!isCurrentMutation(owner)) return
    await confirmDataCenterGroupClassification(
      currentDetail.id,
      warnings.length > 0,
      currentDetail.classificationConfirmationFingerprint,
    )
    if (!isCurrentMutation(owner)) return
    const next = await reloadAfterMutation(owner)
    if (!next) return
    emit('review-decided', 'approved')
    ElMessage.success(warnings.length ? '已人工确认分类完成并记录异常' : '已人工确认分类完成')
  } catch (error) {
    if (getApiErrorStatus(error) === 409) await reloadAfterMutation(owner)
    showMutationError(owner, error, '人工确认分类完成失败')
  } finally {
    finishMutation(owner)
  }
}

async function resolveAnomaly(anomaly: DataCenterDetail['anomalies'][number]) {
  if (!detail.value || anomaly.status !== 'open') return
  const groupId = detail.value.id
  const owner = beginMutation(groupId)
  try {
    try {
      await ElMessageBox.confirm(
        `请人工确认异常“${anomaly.message}”已经修复。确认后将保留处理人员和时间；资料再次变化时，该异常会重新打开。`,
        '确认异常已修复',
        {
          type: 'warning',
          confirmButtonText: '确认已修复',
          cancelButtonText: '取消',
        },
      )
    } catch {
      return
    }
    if (!isCurrentMutation(owner)) return
    await resolveDataCenterGroupAnomaly(groupId, anomaly.code, anomaly.evidenceFingerprint)
    if (!isCurrentMutation(owner)) return
    const next = await reloadAfterMutation(owner)
    if (!next) return
    ElMessage.success('异常已人工确认修复并留痕')
  } catch (error) {
    if (getApiErrorStatus(error) === 409) await reloadAfterMutation(owner)
    showMutationError(owner, error, '确认异常修复失败')
  } finally {
    finishMutation(owner)
  }
}

async function rescanActivePhoto() {
  if (!detail.value || !activePhoto.value) return
  const groupId = detail.value.id
  const photo = activePhoto.value
  const owner = beginMutation(groupId)
  try {
    await rescanDataCenterGroupPhotoBarcode(
      groupId,
      photo.id,
      photo.category || '',
      form.reason.trim() || '数据中台重新扫码',
    )
    if (!isCurrentMutation(owner)) return
    ElMessage.success('重新扫码完成')
    await reloadAfterMutation(owner)
  } catch (error) {
    showMutationError(owner, error, '重新扫码失败')
  } finally {
    finishMutation(owner)
  }
}

function targetField(type: RegionScanResult['barcodeType']) {
  return type === 'collector' ? 'collector' : type === 'module' ? 'moduleAssetNo' : 'meterNo'
}

async function handleRegionScan(request: { barcodeType: RegionScanResult['barcodeType']; region: RegionScanResult['region'] }) {
  if (!detail.value || !activePhoto.value) return
  const groupId = detail.value.id
  const photoId = activePhoto.value.id
  const owner = beginMutation(groupId)
  try {
    const result = await scanDataCenterGroupPhotoRegion(
      groupId,
      photoId,
      request,
      form.reason.trim() || '数据中台框选扫码',
    )
    if (!isCurrentMutation(owner)) return
    const value = (result.normalizedValues[0] || result.values[0] || '').trim()
    if (!value) {
      ElMessage.warning('当前选区未识别到可用内容')
      return
    }
    await ElMessageBox.confirm(`确认写入识别值 ${value}？`, '识别结果确认', {
      type: 'warning',
      confirmButtonText: '确认写入',
      cancelButtonText: '取消',
    })
    if (!isCurrentMutation(owner)) return
    form[targetField(result.barcodeType)] = value
    inspector.value?.finishSubmission()
  } catch (error) {
    if (error !== 'cancel') showMutationError(owner, error, '框选扫码失败')
  } finally {
    finishMutation(owner)
  }
}

async function manualConfirm() {
  if (!detail.value) return
  const currentDetail = detail.value
  const reason = form.reason.trim()
  if (!reason) {
    ElMessage.warning('请填写人工确认原因')
    return
  }
  const owner = beginMutation(currentDetail.id)
  try {
    try {
      await ElMessageBox.confirm('确认以当前字段和照片证据人工通过扫码？', '人工确认', {
        type: 'warning',
        confirmButtonText: '人工确认',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
    if (!isCurrentMutation(owner)) return
    const result = await confirmDataCenterGroupBarcode(currentDetail.id, {
      meterNo: form.meterNo.trim(),
      moduleAssetNo: form.moduleAssetNo.trim(),
      collector: form.collector.trim(),
      reason,
      photoIds: currentDetail.photos.map((photo) => photo.id),
    })
    if (!isCurrentMutation(owner)) return
    ElMessage.success(result.deliveryPackageJobStatus ? '已人工确认并排队' : '已人工确认')
    await reloadAfterMutation(owner)
  } catch (error) {
    showMutationError(owner, error, '人工确认失败')
  } finally {
    finishMutation(owner)
  }
}

async function returnException() {
  if (!detail.value) return
  const groupId = detail.value.id
  const owner = beginMutation(groupId)
  try {
    await returnDataCenterGroupToException(groupId, {
      category: form.exceptionCategory,
      note: form.exceptionNote.trim() || form.reason.trim() || '数据中台退回异常',
      reason: form.reason.trim() || form.exceptionNote.trim() || '数据中台退回异常',
    })
    if (!isCurrentMutation(owner)) return
    ElMessage.success('已退回异常')
    await reloadAfterMutation(owner)
  } catch (error) {
    showMutationError(owner, error, '退回异常失败')
  } finally {
    finishMutation(owner)
  }
}

async function resetGroup(kind: 'unreviewed' | 'unconstructed') {
  if (!detail.value) return
  const groupId = detail.value.id
  const owner = beginMutation(groupId)
  try {
    try {
      await ElMessageBox.confirm(kind === 'unreviewed' ? '确认回退至未审阅？' : '确认回退至未施工？', '回退', {
        type: kind === 'unconstructed' ? 'error' : 'warning',
        confirmButtonText: '确认回退',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
    if (!isCurrentMutation(owner)) return
    if (kind === 'unreviewed') await resetAdminGroupToUnreviewed(groupId, form.resetReason)
    else await resetAdminGroupToUnconstructed(groupId, form.resetReason)
    if (!isCurrentMutation(owner)) return
    ElMessage.success('已回退')
    await reloadAfterMutation(owner)
  } catch (error) {
    showMutationError(owner, error, '回退失败')
  } finally {
    finishMutation(owner)
  }
}

async function decideReview(status: 'approved' | 'incomplete') {
  if (!detail.value) return
  const requestedGroupId = detail.value.id
  const owner = beginMutation(requestedGroupId)
  try {
    await reviewDataCenterGroup(
      requestedGroupId,
      status,
      form.reason.trim(),
      status === 'incomplete' ? form.exceptionNote.trim() : '',
    )
    if (!isCurrentMutation(owner)) return
    const next = await reloadAfterMutation(owner)
    if (!next) return
    emit('review-decided', status)
    ElMessage.success(status === 'approved' ? '已正式通过' : '已标记资料不全')
  } catch (error) {
    showMutationError(owner, error, '审阅决定失败')
  } finally {
    finishMutation(owner)
  }
}

watch(
  () => props.groupId,
  () => {
    cleanupDetail()
    void loadDetail()
  },
  { immediate: true },
)

watch(
  () => [props.rephotoItem, props.defaultStage] as const,
  ([item, defaultStage]) => {
    activeStage.value = item ? defaultStage : 'source'
  },
)

onBeforeUnmount(cleanupDetail)
</script>

<template>
  <section class="data-center-group-review-panel" :aria-busy="loading || saving">
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />
    <el-skeleton v-if="loading" :rows="8" animated />

    <section v-else-if="detail && props.classificationOnly" class="classification-only-panel">
      <header class="classification-heading">
        <strong>
          照片分类 {{ classificationCompletedCount }}/{{ classificationTotalCount }}
          <em v-if="hasManualClassificationConfirmation">已人工确认分类完成</em>
        </strong>
        <span>将未分类照片归入已有的四种资料类型</span>
      </header>
      <section v-if="detail.anomalies.length" class="anomaly-snapshot" aria-label="异常快照">
        <header><strong>异常原因</strong><span>人工确认后保留绿色处理记录</span></header>
        <article
          v-for="anomaly in detail.anomalies"
          :key="anomaly.code"
          :class="{ resolved: anomaly.status === 'resolved' }"
          :data-testid="`anomaly-${anomaly.code}`"
        >
          <div>
            <strong>{{ anomaly.message }}</strong>
            <span v-if="anomaly.status === 'resolved'">
              已确认修复 · {{ anomaly.resolvedBy || '未知人员' }} · {{ anomaly.resolvedAt || '未记录时间' }}
            </span>
            <span v-else>当前异常</span>
          </div>
          <el-button
            v-if="anomaly.status === 'open'"
            size="small"
            type="success"
            plain
            :loading="saving"
            :data-testid="`resolve-anomaly-${anomaly.code}`"
            @click="resolveAnomaly(anomaly)"
          >确认已修复</el-button>
        </article>
      </section>
      <div class="classification-photo-grid">
        <article v-for="photo in detail.photos" :key="photo.id" class="classification-photo-card">
          <div class="classification-photo-frame">
            <button
              v-if="photoObjectUrls.get(photo.id)"
              type="button"
              :data-testid="`preview-classification-${photo.id}`"
              :aria-label="`查看${photo.categoryLabel || photo.name || '待分类照片'}大图`"
              @click="openProtectedPhoto(photo)"
            ><img :src="photoObjectUrls.get(photo.id)" :alt="photo.categoryLabel || photo.name || '待分类照片'" /></button>
            <span v-else>图片加载中</span>
          </div>
          <select
            :value="pendingCategories[photo.id] || 'unclassified'"
            :aria-label="`照片 ${photo.name || photo.id} 分类`"
            :data-testid="`photo-category-${photo.id}`"
            :disabled="saving"
            @change="setPendingCategory(photo.id, $event)"
          >
            <option value="unclassified" disabled>请选择照片类型</option>
            <option v-for="item in classificationCategoryOptions" :key="item.value" :value="item.value">
              {{ item.label }}
            </option>
          </select>
          <span :class="classificationCategoryValues.has(pendingCategories[photo.id]) ? 'classified' : 'unclassified'">
            {{ classificationCategoryValues.has(pendingCategories[photo.id]) ? '已分类' : '未分类' }}
          </span>
        </article>
      </div>
      <div class="classification-actions">
        <button
          type="button"
          class="save-classifications"
          data-testid="save-photo-classifications"
          :disabled="saving || !classificationChanges.length"
          @click="saveClassifications"
        >{{ saving ? '保存中…' : '保存分类' }}</button>
        <button
          type="button"
          class="confirm-classification-complete"
          data-testid="confirm-classification-complete"
          :disabled="saving || classificationChanges.length > 0"
          @click="confirmClassificationComplete"
        >{{ saving ? '确认中…' : hasManualClassificationConfirmation ? '重新确认分类完成' : '人工确认分类完成' }}</button>
      </div>
    </section>

    <div v-else-if="detail" class="review-layout">
      <section class="photo-pane">
        <div v-if="props.rephotoItem" class="stage-switch" aria-label="资料位置">
          <button type="button" :class="{ active: activeStage === 'source' }" @click="activeStage = 'source'">源资料</button>
          <button type="button" :class="{ active: activeStage === 'rephoto' }" @click="activeStage = 'rephoto'">翻拍位置</button>
        </div>

        <div v-if="activeStage === 'source'" data-stage="source" class="source-stage">
          <div class="photo-stage">
            <ReviewImageInspector
              v-if="activePhotoUrl"
              ref="inspector"
              :src="activePhotoUrl"
              :alt="activePhoto?.categoryLabel || activePhoto?.category || '资料组照片'"
              :loading="imageLoading || saving"
              :disabled="saving"
              @scan="handleRegionScan"
            />
            <div v-else class="photo-placeholder">图片加载中</div>
          </div>
          <div class="photo-tabs">
            <button
              v-for="photo in detail.photos"
              :key="photo.id"
              type="button"
              :class="{ active: photo.id === selectedPhotoId }"
              @click="selectedPhotoId = photo.id"
            >
              {{ photo.categoryLabel || photo.category || photo.id }}
            </button>
          </div>
        </div>

        <section v-else-if="props.rephotoItem" data-stage="rephoto" class="rephoto-stage">
          <div class="rephoto-identifiers">
            <div><strong>表号</strong><span>{{ props.rephotoItem.meter_no }}</span></div>
            <Code128Barcode :value="props.rephotoItem.meter_barcode" label="表号条码" />
            <div><strong>模块号</strong><span>{{ props.rephotoItem.module_no }}</span></div>
            <Code128Barcode :value="props.rephotoItem.module_barcode" label="模块号条码" />
          </div>
          <div class="rephoto-slots">
            <figure v-for="slot in rephotoSlots" :key="slot.slot" :data-rephoto-slot="slot.slot">
              <figcaption>{{ slot.label }}</figcaption>
              <button
                v-if="rephotoImageUrl(slot.photo)"
                type="button"
                class="rephoto-preview-trigger"
                :data-testid="`preview-rephoto-${slot.slot}`"
                :aria-label="`查看${slot.label}大图`"
                @click="openRephotoPreview(rephotoImageUrl(slot.photo), slot.label)"
              ><img :src="rephotoImageUrl(slot.photo)" :alt="slot.label" /></button>
              <span v-else>暂无照片</span>
            </figure>
          </div>
        </section>
      </section>

      <section class="review-pane">
        <header class="group-summary">
          <strong>{{ detail.meterNo || detail.id }}</strong>
          <span>{{ detail.terminal }}</span>
          <span>审阅状态：{{ detail.reviewStatus }}</span>
        </header>
        <el-form label-position="top" class="field-grid">
          <el-form-item label="表号"><el-input v-model="form.meterNo" /></el-form-item>
          <el-form-item label="模块"><el-input v-model="form.moduleAssetNo" /></el-form-item>
          <el-form-item label="采集器"><el-input v-model="form.collector" /></el-form-item>
          <el-form-item label="原因" class="wide-field"><el-input v-model="form.reason" /></el-form-item>
        </el-form>

        <div class="action-strip">
          <el-button :icon="Refresh" :loading="saving" :disabled="!activePhoto" @click="rescanActivePhoto">重新扫码</el-button>
          <el-button type="primary" :icon="CircleCheck" :loading="saving" @click="manualConfirm">人工确认</el-button>
          <el-button :icon="FolderChecked" :loading="saving" @click="saveFields">字段修正</el-button>
        </div>

        <div class="category-grid">
          <el-button
            v-for="item in categoryOptions"
            :key="item.value"
            :type="activePhoto?.category === item.value ? 'primary' : 'default'"
            :disabled="!activePhoto || saving"
            @click="classifyActivePhoto(item.value)"
          >{{ item.label }}</el-button>
        </div>

        <div class="decision-strip">
          <el-button type="success" :loading="saving" @click="decideReview('approved')">正式通过</el-button>
          <el-button type="warning" :loading="saving" @click="decideReview('incomplete')">资料不全</el-button>
        </div>

        <div class="exception-box">
          <div><el-icon><Warning /></el-icon><strong>异常 / 回退</strong></div>
          <section v-if="detail.anomalies.length" class="anomaly-snapshot" aria-label="异常快照">
            <header><strong>异常原因</strong><span>人工确认后保留绿色处理记录</span></header>
            <article
              v-for="anomaly in detail.anomalies"
              :key="anomaly.code"
              :class="{ resolved: anomaly.status === 'resolved' }"
              :data-testid="`anomaly-${anomaly.code}`"
            >
              <div>
                <strong>{{ anomaly.message }}</strong>
                <span v-if="anomaly.status === 'resolved'">
                  已确认修复 · {{ anomaly.resolvedBy || '未知人员' }} · {{ anomaly.resolvedAt || '未记录时间' }}
                </span>
                <span v-else>当前异常</span>
              </div>
              <el-button
                v-if="anomaly.status === 'open'"
                size="small"
                type="success"
                plain
                :loading="saving"
                :data-testid="`resolve-anomaly-${anomaly.code}`"
                @click="resolveAnomaly(anomaly)"
              >确认已修复</el-button>
            </article>
          </section>
          <el-select v-model="form.exceptionCategory">
            <el-option label="条码异常" value="barcode_error" />
            <el-option label="模块异常" value="module_error" />
            <el-option label="采集器异常" value="collector_error" />
            <el-option label="照片异常" value="photo_error" />
          </el-select>
          <el-input v-model="form.exceptionNote" />
          <div class="action-strip">
            <el-button type="warning" plain :loading="saving" @click="returnException">退回异常</el-button>
            <el-input v-model="form.resetReason" />
            <el-button :loading="saving" @click="resetGroup('unreviewed')">回退未审阅</el-button>
            <el-button type="danger" plain :loading="saving" @click="resetGroup('unconstructed')">回退未施工</el-button>
          </div>
        </div>

        <el-table :data="detail.audit" size="small" height="180" class="audit-table">
          <el-table-column prop="action" label="审计" min-width="160" show-overflow-tooltip />
          <el-table-column prop="actor" label="人员" width="110" show-overflow-tooltip />
          <el-table-column prop="created_at" label="时间" min-width="170" show-overflow-tooltip />
        </el-table>
      </section>
    </div>
    <PhotoLightbox :src="photoPreview.src" :alt="photoPreview.alt" @close="closePhotoPreview" />
  </section>
</template>

<style scoped>
.data-center-group-review-panel { min-width: 0; }
.classification-only-panel { display: grid; gap: 14px; min-width: 0; }
.classification-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.classification-heading strong { color: var(--v2-text-strong, #172033); font-size: 15px; }
.classification-heading strong em { margin-left: 8px; color: var(--el-color-success-dark-2, #529b2e); font-size: 12px; font-style: normal; font-weight: 600; }
.classification-heading span { color: var(--v2-text-muted, #7a8798); font-size: 13px; }
.classification-photo-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; }
.anomaly-snapshot { display: grid; gap: 8px; padding: 10px; border: 1px solid #f3c6c6; border-radius: 8px; background: #fffafa; }
.anomaly-snapshot > header { display: flex; justify-content: space-between; gap: 10px; color: var(--v2-text-muted, #7a8798); font-size: 12px; }
.anomaly-snapshot > header strong { color: #b42318; font-size: 14px; }
.anomaly-snapshot > article { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 10px; border: 1px solid #ffd7d2; border-radius: 6px; background: #fff; }
.anomaly-snapshot > article > div { display: grid; gap: 3px; min-width: 0; }
.anomaly-snapshot > article > div > strong { color: #b42318; }
.anomaly-snapshot > article > div > span { color: var(--v2-text-muted, #7a8798); font-size: 12px; }
.anomaly-snapshot > article.resolved { border-color: #b7e4c7; background: #f0fdf4; }
.anomaly-snapshot > article.resolved > div > strong, .anomaly-snapshot > article.resolved > div > span { color: #217a3c; }
.classification-photo-card { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; align-items: center; min-width: 0; }
.classification-photo-frame { grid-column: 1 / -1; display: grid; place-items: center; aspect-ratio: 4 / 2.35; overflow: hidden; border: 1px solid var(--v2-border, #dce3ec); border-radius: 6px; background: var(--v2-surface-soft, #f6f8fb); color: var(--v2-text-muted, #7a8798); }
.classification-photo-frame button, .rephoto-preview-trigger { display: block; width: 100%; height: 100%; padding: 0; border: 0; background: transparent; cursor: zoom-in; }
.classification-photo-frame img { display: block; width: 100%; height: 100%; object-fit: cover; }
.classification-photo-card select { width: 100%; min-width: 0; height: 34px; padding: 0 30px 0 10px; border: 1px solid var(--v2-border, #dce3ec); border-radius: 6px; background: #fff; color: var(--v2-text, #2f3a4a); font: inherit; }
.classification-photo-card > span { white-space: nowrap; font-size: 12px; }
.classification-photo-card > span.classified { color: var(--el-color-success, #67c23a); }
.classification-photo-card > span.unclassified { color: var(--el-color-warning, #e6a23c); }
.save-classifications { justify-self: center; min-width: 92px; min-height: 36px; padding: 0 18px; border: 1px solid var(--v2-accent, #1677ff); border-radius: 6px; background: var(--v2-accent, #1677ff); color: #fff; cursor: pointer; }
.classification-actions { display: flex; justify-content: center; flex-wrap: wrap; gap: 10px; }
.confirm-classification-complete { min-width: 154px; min-height: 36px; padding: 0 18px; border: 1px solid var(--el-color-success, #67c23a); border-radius: 6px; background: #fff; color: var(--el-color-success-dark-2, #529b2e); cursor: pointer; }
.save-classifications:disabled, .confirm-classification-complete:disabled { cursor: not-allowed; opacity: .55; }
.review-layout { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(360px, .9fr); gap: 14px; min-height: 640px; }
.photo-pane, .review-pane { display: grid; align-content: start; gap: 10px; min-width: 0; }
.source-stage { display: grid; grid-template-rows: minmax(0, 1fr) auto; gap: 10px; }
.photo-stage { min-height: 0; border: 1px solid var(--v2-border); border-radius: 8px; overflow: hidden; }
.photo-stage :deep(.review-image-inspector) { width: 100%; height: 100%; min-height: 520px; grid-template-rows: auto minmax(0, 1fr); }
.photo-stage :deep(.review-image-inspector__stage) { min-height: 0; }
.photo-placeholder { display: grid; min-height: 520px; place-items: center; color: var(--v2-text-muted); background: var(--v2-surface-soft); }
.photo-tabs { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.photo-tabs button, .stage-switch button { min-width: 0; padding: 8px; border: 1px solid var(--v2-border); border-radius: 8px; background: #fff; color: var(--v2-text); cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.photo-tabs button.active, .stage-switch button.active { border-color: var(--v2-accent); color: var(--v2-accent); }
.stage-switch, .action-strip, .decision-strip { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.rephoto-stage, .rephoto-identifiers, .rephoto-slots { display: grid; gap: 12px; }
.rephoto-identifiers { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.rephoto-identifiers > div { display: flex; justify-content: space-between; gap: 8px; padding: 10px; border: 1px solid var(--v2-border); border-radius: 8px; }
.rephoto-slots { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.rephoto-slots figure { display: grid; gap: 8px; min-height: 260px; margin: 0; padding: 10px; border: 1px solid var(--v2-border); border-radius: 8px; }
.rephoto-slots img { display: block; width: 100%; height: 240px; object-fit: contain; }
.group-summary { display: flex; flex-wrap: wrap; gap: 10px; color: var(--v2-text-muted); }
.group-summary strong { color: var(--v2-text-strong); }
.field-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0 10px; }
.wide-field { grid-column: 1 / -1; }
.category-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }
.exception-box { display: grid; gap: 10px; padding: 12px; border: 1px solid #f3c6c6; border-radius: 8px; background: #fff7f7; }
.exception-box > div:first-child { display: flex; align-items: center; gap: 8px; }
.audit-table { width: 100%; }
@media (max-width: 900px) {
  .review-layout, .field-grid, .category-grid, .rephoto-identifiers, .rephoto-slots { grid-template-columns: 1fr; }
  .classification-photo-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 560px) {
  .classification-heading { align-items: flex-start; flex-direction: column; }
  .classification-photo-grid { grid-template-columns: 1fr; }
}
</style>
