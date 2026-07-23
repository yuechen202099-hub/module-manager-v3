<script setup lang="ts">
import { Check, CircleCheck, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'

import {
  confirmUnmatchedReview,
  fetchUnmatchedMatchCandidates,
  fetchUnmatchedReview,
  fetchUnmatchedReviewPhotoObjectUrl,
  finalizeUnmatchedMatch as finalizeLocalUnmatchedMatch,
  getApiErrorStatus,
  rescanUnmatchedReviewPhoto,
  saveUnmatchedReview,
  scanUnmatchedPhotoRegion,
} from '@/api/services'
import type { BarcodeType, RegionScanRequest, RegionScanResult, UnmatchedMatchCandidate, UnmatchedReviewDetail } from '@/api/types'
import ReviewImageInspector from '@/components/ReviewImageInspector.vue'
import { useAuthStore } from '@/stores/auth'

type FinalizeMatchPayload = {
  unmatchedId: string
  terminal: string
  meterNo: string
  candidateKey: string
  expectedVersion: number
}

const props = defineProps<{
  modelValue: boolean
  unmatchedId: string
  dataCenter?: boolean
  finalizeMatch?: (payload: FinalizeMatchPayload) => Promise<string>
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  matched: [groupId: string]
  updated: []
}>()

const auth = useAuthStore()
const mode = ref<'review' | 'match'>('review')
const detail = ref<UnmatchedReviewDetail | null>(null)
const selectedPhotoId = ref('')
const imageObjectUrl = ref('')
const candidatePage = ref(1)
const candidatePageSize = 20
const candidates = ref<UnmatchedMatchCandidate[]>([])
const selectedCandidateKey = ref('')
const draft = reactive({ meterNo: '', collector: '', moduleAssetNo: '' })
const photoCategories = reactive<Record<string, string>>({})
const loading = ref(false)
const imageLoading = ref(false)
const regionScanLoading = ref(false)
const unmatchedRegionInspector = ref<{ resetSelection: () => void; finishSubmission: () => void } | null>(null)
const unmatchedPreviewImage = ref<HTMLElement | null>(null)
const saving = ref(false)
const rescanning = ref(false)
const confirming = ref(false)
const candidatesLoading = ref(false)
const finalizing = ref(false)
const errorMessage = ref('')
const narrowScreen = ref(false)

let detailRequestSerial = 0
let imageRequestSerial = 0
let candidateRequestSerial = 0
let mutationSessionSerial = 0
let regionScanSerial = 0
let regionScanDialogActive = false
let candidateAbortController: AbortController | null = null
let loadedUnmatchedId = ''

const isAdmin = computed(() => Boolean(auth.user?.roles?.includes('admin') || auth.user?.role === 'admin'))
const selectedPhoto = computed(() => detail.value?.photos.find((photo) => photo.id === selectedPhotoId.value) || null)
const candidateTotalPages = computed(() => Math.max(1, Math.ceil(candidates.value.length / candidatePageSize)))
const pagedCandidates = computed(() => {
  const start = (candidatePage.value - 1) * candidatePageSize
  return candidates.value.slice(start, start + candidatePageSize)
})
const selectedCandidate = computed(() => candidates.value.find((item) => item.candidateKey === selectedCandidateKey.value) || null)

const categoryOptions = [
  { value: 'before_box', label: '施工前' },
  { value: 'after_box', label: '施工后' },
  { value: 'collector_barcode', label: '采集器条码' },
  { value: 'module_meter', label: '模块表号' },
]

const draftFieldByBarcodeType = {
  meter: 'meterNo',
  module: 'moduleAssetNo',
  collector: 'collector',
} as const
const barcodeTypeLabels: Record<BarcodeType, string> = { meter: '表计', module: '模块', collector: '采集器' }
const regionScanDialog = reactive({
  open: false,
  barcodeType: 'meter' as BarcodeType,
  values: [] as string[],
  selectedValue: '',
  method: 'none' as RegionScanResult['method'],
})
const regionScanOriginalValue = computed(() => draft[draftFieldByBarcodeType[regionScanDialog.barcodeType]])
const regionScanMethodLabel = computed(() => ({ barcode: '条码', ocr: 'OCR', none: '未识别' })[regionScanDialog.method])

function replaceImageObjectUrl(next = '') {
  if (imageObjectUrl.value) URL.revokeObjectURL(imageObjectUrl.value)
  imageObjectUrl.value = next
}

function resetDraft(next: UnmatchedReviewDetail) {
  draft.meterNo = next.meterNo
  draft.collector = next.collector
  draft.moduleAssetNo = next.moduleAssetNo
  for (const key of Object.keys(photoCategories)) delete photoCategories[key]
  for (const photo of next.photos) photoCategories[photo.id] = photo.category
}

function applyDetail(next: UnmatchedReviewDetail, preserveDraft = false) {
  detail.value = next
  if (!preserveDraft) resetDraft(next)
  const nextPhotoId = next.photos.some((photo) => photo.id === selectedPhotoId.value)
    ? selectedPhotoId.value
    : next.photos[0]?.id || ''
  if (nextPhotoId !== selectedPhotoId.value) {
    invalidateRegionScan()
    selectedPhotoId.value = nextPhotoId
    void loadSelectedPhoto()
  }
}

function isVersionConflict(error: unknown) {
  return getApiErrorStatus(error) === 409
}

function isCurrentReviewRecord(unmatchedId: string) {
  return Boolean(unmatchedId && props.modelValue && props.unmatchedId === unmatchedId)
}

function resetMutationState() {
  saving.value = false
  rescanning.value = false
  confirming.value = false
  finalizing.value = false
}

function invalidateMutationSession() {
  mutationSessionSerial += 1
  resetMutationState()
}

function isCurrentMutation(mutationSession: number, unmatchedId: string) {
  return mutationSession === mutationSessionSerial && isCurrentReviewRecord(unmatchedId)
}

function resetReviewContent() {
  invalidateRegionScan()
  detail.value = null
  draft.meterNo = ''
  draft.collector = ''
  draft.moduleAssetNo = ''
  for (const key of Object.keys(photoCategories)) delete photoCategories[key]
  selectedPhotoId.value = ''
  errorMessage.value = ''
  replaceImageObjectUrl()
}

function invalidateCandidateRequest() {
  candidateRequestSerial += 1
  candidateAbortController?.abort()
  candidateAbortController = null
}

function isCurrentCandidateRequest(requestSerial: number, unmatchedId: string, controller: AbortController) {
  return (
    requestSerial === candidateRequestSerial &&
    candidateAbortController === controller &&
    props.modelValue &&
    props.unmatchedId === unmatchedId &&
    mode.value === 'match'
  )
}

function clampCandidatePage() {
  candidatePage.value = Math.min(Math.max(1, candidatePage.value), candidateTotalPages.value)
}

function resetCandidateResults() {
  candidates.value = []
  selectedCandidateKey.value = ''
  candidatePage.value = 1
}

function isAbortedRequest(error: unknown) {
  return typeof error === 'object' && error !== null && (error as { name?: unknown }).name === 'AbortError'
}

function handleUnavailableRecord(error: unknown, unmatchedId: string) {
  if (getApiErrorStatus(error) !== 404 || !isCurrentReviewRecord(unmatchedId)) return false
  detailRequestSerial += 1
  imageRequestSerial += 1
  invalidateCandidateRequest()
  invalidateMutationSession()
  resetReviewContent()
  resetCandidateResults()
  loadedUnmatchedId = ''
  mode.value = 'review'
  candidatesLoading.value = false
  emit('updated')
  emit('update:modelValue', false)
  ElMessage.warning('记录已由其他管理员处理，列表已刷新')
  return true
}

async function loadDetail(options: { preserveDraft?: boolean } = {}) {
  if (!props.unmatchedId) return
  const unmatchedId = props.unmatchedId
  const requestSerial = ++detailRequestSerial
  loading.value = true
  errorMessage.value = ''
  try {
    const next = await fetchUnmatchedReview(unmatchedId)
    if (requestSerial !== detailRequestSerial || !isCurrentReviewRecord(unmatchedId)) return
    applyDetail(next, options.preserveDraft)
    loadedUnmatchedId = unmatchedId
  } catch (error) {
    if (requestSerial !== detailRequestSerial) return
    if (handleUnavailableRecord(error, unmatchedId)) return
    errorMessage.value = error instanceof Error ? error.message : '审阅详情加载失败'
  } finally {
    if (requestSerial === detailRequestSerial) loading.value = false
  }
}

async function reloadAfterConflict(unmatchedId: string, mutationSession: number) {
  await loadDetail({ preserveDraft: true })
  if (isCurrentMutation(mutationSession, unmatchedId)) ElMessage.warning('记录已更新，请确认后重试')
}

async function loadSelectedPhoto() {
  const photoId = selectedPhotoId.value
  const unmatchedId = props.unmatchedId
  const requestSerial = ++imageRequestSerial
  replaceImageObjectUrl()
  if (!photoId || !unmatchedId || !props.modelValue) return
  imageLoading.value = true
  errorMessage.value = ''
  try {
    const next = await fetchUnmatchedReviewPhotoObjectUrl(unmatchedId, photoId)
    if (
      requestSerial !== imageRequestSerial ||
      !props.modelValue ||
      props.unmatchedId !== unmatchedId ||
      selectedPhotoId.value !== photoId
    ) {
      URL.revokeObjectURL(next)
      return
    }
    replaceImageObjectUrl(next)
  } catch (error) {
    if (requestSerial === imageRequestSerial) {
      errorMessage.value = getApiErrorStatus(error) === 404
        ? '当前照片无法加载，可继续审阅其他照片'
        : error instanceof Error ? error.message : '图片加载失败'
    }
  } finally {
    if (requestSerial === imageRequestSerial) imageLoading.value = false
  }
}

async function handleRegionScan(request: RegionScanRequest) {
  const inspector = unmatchedRegionInspector.value
  if (regionScanLoading.value) {
    inspector?.finishSubmission()
    return
  }
  const unmatchedId = props.unmatchedId
  const photoId = selectedPhotoId.value
  if (!unmatchedId || !photoId || !props.modelValue) {
    inspector?.finishSubmission()
    return
  }
  const requestSerial = ++regionScanSerial
  regionScanLoading.value = true
  errorMessage.value = ''
  try {
    const result = await scanUnmatchedPhotoRegion(unmatchedId, photoId, request)
    if (
      requestSerial !== regionScanSerial ||
      !props.modelValue ||
      props.unmatchedId !== unmatchedId ||
      selectedPhotoId.value !== photoId
    ) {
      inspector?.resetSelection()
      return
    }
    const values = [...new Set((result.normalizedValues.length ? result.normalizedValues : result.values).filter(Boolean))]
    if (!values.length) {
      ElMessage.warning('当前选区未识别到可用内容')
      return
    }
    regionScanDialog.barcodeType = result.barcodeType
    regionScanDialog.values = values
    regionScanDialog.selectedValue = values.length === 1 ? values[0] : ''
    regionScanDialog.method = result.method
    regionScanDialogActive = true
    regionScanDialog.open = true
  } catch (error) {
    if (
      requestSerial === regionScanSerial &&
      props.modelValue &&
      props.unmatchedId === unmatchedId &&
      selectedPhotoId.value === photoId
    ) {
      errorMessage.value = error instanceof Error ? error.message : '选区识别失败'
    }
  } finally {
    regionScanLoading.value = false
    inspector?.finishSubmission()
  }
}

function replaceRegionScanDraft() {
  if (!regionScanDialog.selectedValue) return
  const field = draftFieldByBarcodeType[regionScanDialog.barcodeType]
  draft[field] = regionScanDialog.selectedValue
  closeRegionScanDialog()
}

function closeRegionScanDialog() {
  if (!regionScanDialogActive) return
  regionScanDialogActive = false
  regionScanSerial += 1
  regionScanDialog.open = false
  regionScanDialog.values = []
  regionScanDialog.selectedValue = ''
  unmatchedRegionInspector.value?.resetSelection()
}

function invalidateRegionScan() {
  regionScanSerial += 1
  regionScanDialogActive = false
  regionScanDialog.open = false
  regionScanDialog.values = []
  regionScanDialog.selectedValue = ''
  unmatchedRegionInspector.value?.resetSelection()
}

function openImagePreview() {
  unmatchedPreviewImage.value?.querySelector<HTMLElement>('.el-image__inner')?.click()
}

function selectPhoto(photoId: string) {
  if (selectedPhotoId.value === photoId) return
  invalidateRegionScan()
  selectedPhotoId.value = photoId
  void loadSelectedPhoto()
}

function closeDialog() {
  emit('update:modelValue', false)
}

function updateNarrowScreen() {
  narrowScreen.value = window.matchMedia('(max-width: 768px)').matches
}

function savePayload(state: 'pending' | 'reviewed') {
  return {
    expectedVersion: detail.value?.version || 0,
    metadata: {
      meterNo: draft.meterNo,
      collector: draft.collector,
      moduleAssetNo: draft.moduleAssetNo,
    },
    photoUpdates: detail.value?.photos.map((photo) => ({ id: photo.id, category: photoCategories[photo.id] || photo.category })) || [],
    state,
  }
}

async function persistReview(
  state: 'pending' | 'reviewed' = 'pending',
  showSuccess = true,
): Promise<UnmatchedReviewDetail | null> {
  if (!detail.value || detail.value.record.unmatchedId !== props.unmatchedId || saving.value) return null
  const unmatchedId = props.unmatchedId
  if (!unmatchedId) return null
  const mutationSession = mutationSessionSerial
  saving.value = true
  errorMessage.value = ''
  try {
    const next = await saveUnmatchedReview(unmatchedId, savePayload(state))
    if (!isCurrentMutation(mutationSession, unmatchedId)) return null
    applyDetail(next)
    if (showSuccess) ElMessage.success('已保存')
    emit('updated')
    return next
  } catch (error) {
    if (!isCurrentMutation(mutationSession, unmatchedId)) return null
    if (handleUnavailableRecord(error, unmatchedId)) return null
    if (isVersionConflict(error)) await reloadAfterConflict(unmatchedId, mutationSession)
    else errorMessage.value = error instanceof Error ? error.message : '保存失败'
    return null
  } finally {
    if (isCurrentMutation(mutationSession, unmatchedId)) saving.value = false
  }
}

async function saveReview(state: 'pending' | 'reviewed' = 'pending') {
  return Boolean(await persistReview(state))
}

async function rescanPhoto() {
  if (!detail.value || !selectedPhoto.value || saving.value || rescanning.value || confirming.value) return
  const unmatchedId = props.unmatchedId
  const photoId = selectedPhoto.value.id
  const mutationSession = mutationSessionSerial
  rescanning.value = true
  errorMessage.value = ''
  try {
    const saved = await persistReview(detail.value.state, false)
    if (!saved || !isCurrentMutation(mutationSession, unmatchedId)) return
    const savedPhoto = saved.photos.find((photo) => photo.id === photoId)
    const next = await rescanUnmatchedReviewPhoto(
      unmatchedId,
      photoId,
      saved.version,
      savedPhoto?.category || '',
    )
    if (!isCurrentMutation(mutationSession, unmatchedId)) return
    const refreshedPhoto = next.photos.find((photo) => photo.id === photoId)
    detail.value = {
      ...detail.value,
      version: next.version,
      manualConfirmed: next.manualConfirmed,
      reviewer: next.reviewer,
      photos: detail.value.photos.map((photo) => (photo.id === photoId && refreshedPhoto ? refreshedPhoto : photo)),
    }
    if (refreshedPhoto) photoCategories[photoId] = refreshedPhoto.category
    ElMessage.success('重新扫码完成')
    emit('updated')
  } catch (error) {
    if (!isCurrentMutation(mutationSession, unmatchedId)) return
    if (handleUnavailableRecord(error, unmatchedId)) return
    if (isVersionConflict(error)) await reloadAfterConflict(unmatchedId, mutationSession)
    else errorMessage.value = error instanceof Error ? error.message : '重新扫码失败'
  } finally {
    if (isCurrentMutation(mutationSession, unmatchedId)) rescanning.value = false
  }
}

async function confirmReview() {
  if (!detail.value || saving.value || rescanning.value || confirming.value) return
  const unmatchedId = props.unmatchedId
  const mutationSession = mutationSessionSerial
  confirming.value = true
  errorMessage.value = ''
  try {
    const saved = await persistReview(detail.value.state, false)
    if (!saved || !isCurrentMutation(mutationSession, unmatchedId)) return
    const next = await confirmUnmatchedReview(unmatchedId, saved.version)
    if (!isCurrentMutation(mutationSession, unmatchedId)) return
    applyDetail(next, true)
    ElMessage.success('已人工确认')
    emit('updated')
  } catch (error) {
    if (!isCurrentMutation(mutationSession, unmatchedId)) return
    if (handleUnavailableRecord(error, unmatchedId)) return
    if (isVersionConflict(error)) await reloadAfterConflict(unmatchedId, mutationSession)
    else errorMessage.value = error instanceof Error ? error.message : '人工确认失败'
  } finally {
    if (isCurrentMutation(mutationSession, unmatchedId)) confirming.value = false
  }
}

async function openMatchMode() {
  const unmatchedId = props.unmatchedId
  const saved = await persistReview('reviewed')
  if (!saved || !detail.value || !props.modelValue || props.unmatchedId !== unmatchedId) return
  if (!saved.manualConfirmed) {
    ElMessage.warning('请先完成人工确认')
    return
  }
  mode.value = 'match'
  await loadMatchCandidates()
}

async function loadMatchCandidates() {
  if (!props.modelValue || mode.value !== 'match' || !props.unmatchedId) return
  invalidateCandidateRequest()
  resetCandidateResults()
  const requestSerial = candidateRequestSerial
  const unmatchedId = props.unmatchedId
  const controller = new AbortController()
  candidateAbortController = controller
  candidatesLoading.value = true
  errorMessage.value = ''
  try {
    const next = await fetchUnmatchedMatchCandidates(unmatchedId, controller.signal)
    if (!isCurrentCandidateRequest(requestSerial, unmatchedId, controller)) return
    candidates.value = next
    selectedCandidateKey.value = next.length === 1 ? next[0].candidateKey : ''
    clampCandidatePage()
  } catch (error) {
    if (!isCurrentCandidateRequest(requestSerial, unmatchedId, controller) || isAbortedRequest(error)) return
    if (handleUnavailableRecord(error, unmatchedId)) return
    errorMessage.value = error instanceof Error ? error.message : '候选终端加载失败'
  } finally {
    if (isCurrentCandidateRequest(requestSerial, unmatchedId, controller)) {
      candidatesLoading.value = false
      candidateAbortController = null
    }
  }
}

async function finalizeSelectedMatch() {
  if (!isAdmin.value || !detail.value || !selectedCandidateKey.value || finalizing.value) return
  const unmatchedId = props.unmatchedId
  const candidateKey = selectedCandidateKey.value
  const expectedVersion = detail.value.version
  const candidate = selectedCandidate.value
  const mutationSession = mutationSessionSerial
  finalizing.value = true
  errorMessage.value = ''
  try {
    const groupId = props.finalizeMatch
      ? await props.finalizeMatch({
        unmatchedId,
        terminal: candidate?.terminal || detail.value.record.terminal || '',
        meterNo: candidate?.meterNo || detail.value.meterNo || '',
        candidateKey,
        expectedVersion,
      })
      : await finalizeLocalUnmatchedMatch(unmatchedId, candidateKey, expectedVersion)
    if (!isCurrentMutation(mutationSession, unmatchedId)) return
    ElMessage.success('已匹配清单')
    emit('matched', groupId)
    emit('updated')
    closeDialog()
  } catch (error) {
    if (!isCurrentMutation(mutationSession, unmatchedId)) return
    if (handleUnavailableRecord(error, unmatchedId)) return
    if (isVersionConflict(error)) await reloadAfterConflict(unmatchedId, mutationSession)
    else errorMessage.value = error instanceof Error ? error.message : '匹配清单失败'
  } finally {
    if (isCurrentMutation(mutationSession, unmatchedId)) finalizing.value = false
  }
}

function returnToReview() {
  mode.value = 'review'
  invalidateCandidateRequest()
  candidatesLoading.value = false
}

watch(
  () => [props.modelValue, props.unmatchedId] as const,
  ([visible, unmatchedId]) => {
    if (!visible) {
      detailRequestSerial += 1
      imageRequestSerial += 1
      invalidateCandidateRequest()
      resetReviewContent()
      loadedUnmatchedId = ''
      mode.value = 'review'
      candidates.value = []
      selectedCandidateKey.value = ''
      candidatePage.value = 1
      candidatesLoading.value = false
      invalidateMutationSession()
      return
    }
    if (unmatchedId !== loadedUnmatchedId) {
      resetReviewContent()
      loadedUnmatchedId = ''
      invalidateCandidateRequest()
      mode.value = 'review'
      candidates.value = []
      selectedCandidateKey.value = ''
      candidatePage.value = 1
      candidatesLoading.value = false
      invalidateMutationSession()
    }
    void loadDetail()
  },
  { immediate: true },
)

watch(candidateTotalPages, (totalPages) => {
  clampCandidatePage()
})

onMounted(() => {
  updateNarrowScreen()
  window.addEventListener('resize', updateNarrowScreen)
})

onUnmounted(() => {
  invalidateRegionScan()
  detailRequestSerial += 1
  imageRequestSerial += 1
  invalidateMutationSession()
  invalidateCandidateRequest()
  replaceImageObjectUrl()
  window.removeEventListener('resize', updateNarrowScreen)
})
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :fullscreen="narrowScreen"
    width="min(1180px, 96vw)"
    class="unmatched-review-dialog"
    append-to-body
    :close-on-click-modal="false"
    @update:model-value="closeDialog"
  >
    <template #header>
      <div class="unmatched-review-title">
        <strong>{{ mode === 'review' ? (props.dataCenter ? '数据中台未匹配审阅' : '扫码未匹配审阅') : '匹配清单' }}</strong>
        <span>{{ detail?.record.barcode || detail?.record.meterNo || unmatchedId }}</span>
      </div>
    </template>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon />

    <div v-if="loading" class="unmatched-review-loading"><el-skeleton :rows="8" animated /></div>

    <template v-else-if="detail && mode === 'review'">
      <div class="unmatched-review-grid">
        <section class="unmatched-photo-panel">
          <div class="unmatched-photo-stage" :class="{ loading: imageLoading }">
            <ReviewImageInspector
              v-if="imageObjectUrl"
              ref="unmatchedRegionInspector"
              :src="imageObjectUrl"
              alt="未匹配照片"
              :loading="imageLoading || regionScanLoading"
              :disabled="saving || rescanning || confirming || finalizing"
              @scan="handleRegionScan"
              @open="openImagePreview"
            />
            <span v-else>{{ detail.photos.length ? '图片加载中' : '暂无照片' }}</span>
            <div v-if="imageObjectUrl" ref="unmatchedPreviewImage" class="unmatched-preview-trigger">
              <el-image
                :src="imageObjectUrl"
                :preview-src-list="[imageObjectUrl]"
                preview-teleported
                hide-on-click-modal
                fit="contain"
                alt="未匹配照片大图"
              />
            </div>
          </div>
          <div class="unmatched-photo-indexes">
            <button
              v-for="(photo, index) in detail.photos"
              :key="photo.id"
              class="unmatched-photo-index"
              :class="{ active: photo.id === selectedPhotoId }"
              type="button"
              @click="selectPhoto(photo.id)"
            >
              {{ index + 1 }}
            </button>
          </div>
        </section>

        <section class="unmatched-review-form">
          <el-form label-position="top">
            <el-form-item label="表号 / 扫码内容"><el-input v-model="draft.meterNo" :disabled="saving || rescanning || confirming" /></el-form-item>
            <el-form-item label="采集器"><el-input v-model="draft.collector" :disabled="saving || rescanning || confirming" /></el-form-item>
            <el-form-item label="模块"><el-input v-model="draft.moduleAssetNo" :disabled="saving || rescanning || confirming" /></el-form-item>
          </el-form>

          <div class="unmatched-category-actions">
            <el-button
              v-for="option in categoryOptions"
              :key="option.value"
              size="small"
              :type="(photoCategories[selectedPhotoId] || selectedPhoto?.category) === option.value ? 'primary' : 'default'"
              :disabled="saving || rescanning || confirming"
              @click="selectedPhotoId && (photoCategories[selectedPhotoId] = option.value)"
            >
              {{ option.label }}
            </el-button>
          </div>

          <div class="unmatched-photo-status">
            <el-tag v-if="selectedPhoto" effect="plain">{{ selectedPhoto.barcodeCheckStatus || '未扫描' }}</el-tag>
            <span v-if="selectedPhoto?.barcodeCheckValues.length">{{ selectedPhoto.barcodeCheckValues.join(' / ') }}</span>
          </div>

          <div class="unmatched-review-actions">
            <el-button :icon="Refresh" :loading="rescanning" :disabled="!selectedPhoto || saving || confirming" @click="rescanPhoto">重新扫码</el-button>
            <el-button :icon="Check" :loading="confirming" :disabled="saving || rescanning" @click="confirmReview">人工确认</el-button>
            <el-button :loading="saving" :disabled="rescanning || confirming" @click="saveReview()">保存</el-button>
            <el-button type="primary" :icon="CircleCheck" :loading="saving" :disabled="rescanning || confirming" @click="openMatchMode">完成审阅并匹配清单</el-button>
          </div>
        </section>
      </div>
    </template>

    <template v-else-if="detail">
      <div v-if="candidatesLoading" class="unmatched-review-loading"><el-skeleton :rows="6" animated /></div>
      <template v-else-if="candidates.length">
        <el-table :data="pagedCandidates" size="small" border class="unmatched-candidate-table">
          <el-table-column width="56" align="center">
            <template #default="{ row }"><el-radio v-model="selectedCandidateKey" :value="row.candidateKey" /></template>
          </el-table-column>
          <el-table-column prop="terminal" label="终端" min-width="130" />
          <el-table-column prop="meterNo" label="表号" min-width="150" />
          <el-table-column prop="address" label="地址" min-width="240" show-overflow-tooltip />
          <el-table-column label="已有资料组" width="110" align="center">
            <template #default="{ row }"><el-tag effect="plain">{{ row.hasExistingGroup ? '是' : '否' }}</el-tag></template>
          </el-table-column>
          <el-table-column label="匹配依据" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ row.matchReasons.join('；') || '-' }}</template>
          </el-table-column>
        </el-table>
        <div class="unmatched-candidate-footer">
          <el-pagination
            v-model:current-page="candidatePage"
            background
            small
            layout="total, prev, pager, next"
            :total="candidates.length"
            :page-size="candidatePageSize"
          />
          <el-button v-if="isAdmin" type="primary" :loading="finalizing" :disabled="!selectedCandidateKey" @click="finalizeSelectedMatch">
            确认匹配清单
          </el-button>
        </div>
      </template>
      <el-empty v-else description="暂无候选终端" />
    </template>

    <template #footer>
      <el-button v-if="mode === 'match'" @click="returnToReview">返回继续修改</el-button>
      <el-button @click="closeDialog">关闭</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="regionScanDialog.open" title="识别结果确认" width="480px" append-to-body @closed="closeRegionScanDialog">
    <el-descriptions :column="1" border>
      <el-descriptions-item label="类别">{{ barcodeTypeLabels[regionScanDialog.barcodeType] }}</el-descriptions-item>
      <el-descriptions-item label="原值">{{ regionScanOriginalValue || '-' }}</el-descriptions-item>
      <el-descriptions-item label="识别值">
        <el-radio-group v-if="regionScanDialog.values.length > 1" v-model="regionScanDialog.selectedValue">
          <el-radio v-for="value in regionScanDialog.values" :key="value" :value="value">{{ value }}</el-radio>
        </el-radio-group>
        <span v-else>{{ regionScanDialog.selectedValue }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="识别方式">{{ regionScanMethodLabel }}</el-descriptions-item>
    </el-descriptions>
    <template #footer>
      <el-button @click="closeRegionScanDialog">取消</el-button>
      <el-button type="primary" :disabled="!regionScanDialog.selectedValue" @click="replaceRegionScanDraft">替换</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.unmatched-review-title {
  display: flex;
  min-width: 0;
  align-items: baseline;
  gap: 12px;
}

.unmatched-review-title strong { font-size: 18px; }
.unmatched-review-title span { min-width: 0; overflow: hidden; color: var(--el-text-color-secondary); text-overflow: ellipsis; white-space: nowrap; }
.unmatched-review-loading { min-height: 340px; padding: 24px; }
.unmatched-review-grid { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(340px, .9fr); gap: 24px; }
.unmatched-photo-panel, .unmatched-review-form { min-width: 0; }
.unmatched-photo-stage { display: grid; grid-template-rows: minmax(0, 1fr); height: clamp(420px, 58vh, 620px); min-height: 420px; place-items: stretch; overflow: hidden; border: 1px solid var(--el-border-color); background: var(--el-fill-color-lighter); }
.unmatched-photo-stage :deep(.review-image-inspector) { width: 100%; min-width: 0; min-height: 0; height: 100%; grid-template-rows: auto minmax(0, 1fr); }
.unmatched-photo-stage :deep(.review-image-inspector__stage) { min-height: 0; }
.unmatched-photo-stage :deep(.el-image) { display: block; width: 100%; height: 100%; }
.unmatched-photo-stage :deep(.el-image__inner) { display: block; width: 100%; height: 100%; object-fit: contain; }
.unmatched-preview-trigger { display: none; }
.unmatched-photo-stage span { color: var(--el-text-color-secondary); }
.unmatched-photo-indexes { display: flex; flex-wrap: wrap; gap: 8px; padding-top: 12px; }
.unmatched-photo-index { width: 34px; height: 34px; border: 1px solid var(--el-border-color); border-radius: 4px; background: var(--el-bg-color); color: var(--el-text-color-regular); cursor: pointer; }
.unmatched-photo-index.active { border-color: var(--el-color-primary); background: var(--el-color-primary); color: #fff; }
.unmatched-category-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-bottom: 16px; }
.unmatched-category-actions :deep(.el-button) { width: 100%; margin: 0; }
.unmatched-photo-status { display: grid; gap: 6px; min-height: 54px; margin-bottom: 16px; color: var(--el-text-color-secondary); font-size: 13px; overflow-wrap: anywhere; }
.unmatched-review-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.unmatched-review-actions :deep(.el-button) { margin: 0; }
.unmatched-candidate-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-top: 14px; }

@media (max-width: 768px) {
  .unmatched-review-title { gap: 8px; }
  .unmatched-review-title strong { font-size: 16px; }
  .unmatched-review-grid { grid-template-columns: minmax(0, 1fr); gap: 16px; }
  .unmatched-photo-stage { height: min(48vh, 420px); min-height: 280px; }
  .unmatched-review-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .unmatched-review-actions :deep(.el-button) { width: 100%; }
  .unmatched-candidate-footer { align-items: stretch; flex-direction: column; }
}
</style>
