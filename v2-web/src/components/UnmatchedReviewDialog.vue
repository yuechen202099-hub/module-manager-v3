<script setup lang="ts">
import { Check, CircleCheck, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'

import {
  confirmUnmatchedReview,
  fetchUnmatchedMatchCandidates,
  fetchUnmatchedReview,
  fetchUnmatchedReviewPhotoObjectUrl,
  finalizeUnmatchedMatch,
  rescanUnmatchedReviewPhoto,
  saveUnmatchedReview,
} from '@/api/services'
import type { UnmatchedMatchCandidate, UnmatchedReviewDetail } from '@/api/types'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{ modelValue: boolean; unmatchedId: string }>()
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
const saving = ref(false)
const rescanning = ref(false)
const confirming = ref(false)
const candidatesLoading = ref(false)
const finalizing = ref(false)
const errorMessage = ref('')
const narrowScreen = ref(false)

let detailRequestSerial = 0
let imageRequestSerial = 0
let loadedUnmatchedId = ''

const isAdmin = computed(() => Boolean(auth.user?.roles?.includes('admin') || auth.user?.role === 'admin'))
const selectedPhoto = computed(() => detail.value?.photos.find((photo) => photo.id === selectedPhotoId.value) || null)
const candidateTotalPages = computed(() => Math.max(1, Math.ceil(candidates.value.length / candidatePageSize)))
const pagedCandidates = computed(() => {
  const start = (candidatePage.value - 1) * candidatePageSize
  return candidates.value.slice(start, start + candidatePageSize)
})

const categoryOptions = [
  { value: 'before_box', label: '施工前' },
  { value: 'after_box', label: '施工后' },
  { value: 'collector_barcode', label: '采集器条码' },
  { value: 'module_meter', label: '模块表号' },
]

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
    selectedPhotoId.value = nextPhotoId
    void loadSelectedPhoto()
  }
}

function isVersionConflict(error: unknown) {
  const message = error instanceof Error ? error.message : String(error || '')
  return message.includes('409') || message.includes('版本') || message.toLowerCase().includes('conflict')
}

async function loadDetail(options: { preserveDraft?: boolean } = {}) {
  if (!props.unmatchedId) return
  const requestSerial = ++detailRequestSerial
  loading.value = true
  errorMessage.value = ''
  try {
    const next = await fetchUnmatchedReview(props.unmatchedId)
    if (requestSerial !== detailRequestSerial || !props.modelValue) return
    applyDetail(next, options.preserveDraft)
    loadedUnmatchedId = props.unmatchedId
  } catch (error) {
    if (requestSerial !== detailRequestSerial) return
    errorMessage.value = error instanceof Error ? error.message : '审阅详情加载失败'
  } finally {
    if (requestSerial === detailRequestSerial) loading.value = false
  }
}

async function reloadAfterConflict() {
  await loadDetail({ preserveDraft: true })
  ElMessage.warning('记录已更新，请确认后重试')
}

async function loadSelectedPhoto() {
  const photoId = selectedPhotoId.value
  const unmatchedId = props.unmatchedId
  const requestSerial = ++imageRequestSerial
  replaceImageObjectUrl()
  if (!photoId || !unmatchedId || !props.modelValue) return
  imageLoading.value = true
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
      errorMessage.value = error instanceof Error ? error.message : '图片加载失败'
    }
  } finally {
    if (requestSerial === imageRequestSerial) imageLoading.value = false
  }
}

function selectPhoto(photoId: string) {
  if (selectedPhotoId.value === photoId) return
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

async function saveReview(state: 'pending' | 'reviewed' = 'pending') {
  if (!detail.value || saving.value) return false
  saving.value = true
  errorMessage.value = ''
  try {
    const next = await saveUnmatchedReview(props.unmatchedId, savePayload(state))
    applyDetail(next)
    ElMessage.success('已保存')
    emit('updated')
    return true
  } catch (error) {
    if (isVersionConflict(error)) await reloadAfterConflict()
    else errorMessage.value = error instanceof Error ? error.message : '保存失败'
    return false
  } finally {
    saving.value = false
  }
}

async function rescanPhoto() {
  if (!detail.value || !selectedPhoto.value || rescanning.value) return
  const photoId = selectedPhoto.value.id
  rescanning.value = true
  errorMessage.value = ''
  try {
    const next = await rescanUnmatchedReviewPhoto(
      props.unmatchedId,
      photoId,
      detail.value.version,
      photoCategories[photoId] || selectedPhoto.value.category,
    )
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
    if (isVersionConflict(error)) await reloadAfterConflict()
    else errorMessage.value = error instanceof Error ? error.message : '重新扫码失败'
  } finally {
    rescanning.value = false
  }
}

async function confirmReview() {
  if (!detail.value || confirming.value) return
  confirming.value = true
  errorMessage.value = ''
  try {
    const next = await confirmUnmatchedReview(props.unmatchedId, detail.value.version)
    applyDetail(next, true)
    ElMessage.success('已人工确认')
    emit('updated')
  } catch (error) {
    if (isVersionConflict(error)) await reloadAfterConflict()
    else errorMessage.value = error instanceof Error ? error.message : '人工确认失败'
  } finally {
    confirming.value = false
  }
}

async function openMatchMode() {
  const saved = await saveReview('reviewed')
  if (!saved || !detail.value) return
  mode.value = 'match'
  candidatesLoading.value = true
  candidates.value = []
  selectedCandidateKey.value = ''
  candidatePage.value = 1
  errorMessage.value = ''
  try {
    candidates.value = await fetchUnmatchedMatchCandidates(props.unmatchedId)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '候选终端加载失败'
  } finally {
    candidatesLoading.value = false
  }
}

async function finalizeMatch() {
  if (!detail.value || !selectedCandidateKey.value || finalizing.value) return
  finalizing.value = true
  errorMessage.value = ''
  try {
    const selected = candidates.value.find((candidate) => candidate.candidateKey === selectedCandidateKey.value)
    await finalizeUnmatchedMatch(props.unmatchedId, selectedCandidateKey.value, detail.value.version)
    ElMessage.success('已匹配清单')
    emit('matched', selected?.targetGroupId || '')
    emit('updated')
    closeDialog()
  } catch (error) {
    if (isVersionConflict(error)) await reloadAfterConflict()
    else errorMessage.value = error instanceof Error ? error.message : '匹配清单失败'
  } finally {
    finalizing.value = false
  }
}

watch(
  () => [props.modelValue, props.unmatchedId] as const,
  ([visible, unmatchedId]) => {
    if (!visible) {
      detailRequestSerial += 1
      imageRequestSerial += 1
      replaceImageObjectUrl()
      loadedUnmatchedId = ''
      mode.value = 'review'
      candidates.value = []
      selectedCandidateKey.value = ''
      candidatePage.value = 1
      return
    }
    if (unmatchedId !== loadedUnmatchedId) {
      mode.value = 'review'
      candidates.value = []
      selectedCandidateKey.value = ''
      candidatePage.value = 1
      selectedPhotoId.value = ''
    }
    void loadDetail()
  },
  { immediate: true },
)

watch(candidateTotalPages, (totalPages) => {
  if (candidatePage.value > totalPages) candidatePage.value = totalPages
})

onMounted(() => {
  updateNarrowScreen()
  window.addEventListener('resize', updateNarrowScreen)
})

onUnmounted(() => {
  detailRequestSerial += 1
  imageRequestSerial += 1
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
        <strong>{{ mode === 'review' ? '扫码未匹配审阅' : '匹配清单' }}</strong>
        <span>{{ detail?.record.barcode || detail?.record.meterNo || unmatchedId }}</span>
      </div>
    </template>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon />

    <div v-if="loading" class="unmatched-review-loading"><el-skeleton :rows="8" animated /></div>

    <template v-else-if="detail && mode === 'review'">
      <div class="unmatched-review-grid">
        <section class="unmatched-photo-panel">
          <div class="unmatched-photo-stage" :class="{ loading: imageLoading }">
            <img v-if="imageObjectUrl" :src="imageObjectUrl" alt="未匹配照片" />
            <span v-else>{{ detail.photos.length ? '图片加载中' : '暂无照片' }}</span>
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
            <el-form-item label="表号 / 扫码内容"><el-input v-model="draft.meterNo" /></el-form-item>
            <el-form-item label="采集器"><el-input v-model="draft.collector" /></el-form-item>
            <el-form-item label="模块"><el-input v-model="draft.moduleAssetNo" /></el-form-item>
          </el-form>

          <div class="unmatched-category-actions">
            <el-button
              v-for="option in categoryOptions"
              :key="option.value"
              size="small"
              :type="(photoCategories[selectedPhotoId] || selectedPhoto?.category) === option.value ? 'primary' : 'default'"
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
            <el-button :icon="Refresh" :loading="rescanning" :disabled="!selectedPhoto" @click="rescanPhoto">重新扫码</el-button>
            <el-button :icon="Check" :loading="confirming" @click="confirmReview">人工确认</el-button>
            <el-button :loading="saving" @click="saveReview()">保存</el-button>
            <el-button type="primary" :icon="CircleCheck" :loading="saving" @click="openMatchMode">完成审阅并匹配清单</el-button>
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
          <el-table-column prop="targetGroupId" label="已有资料组" min-width="170" show-overflow-tooltip />
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
          <el-button v-if="isAdmin" type="primary" :loading="finalizing" :disabled="!selectedCandidateKey" @click="finalizeMatch">
            确认匹配清单
          </el-button>
        </div>
      </template>
      <el-empty v-else description="暂无候选终端" />
    </template>

    <template #footer>
      <el-button v-if="mode === 'match'" @click="mode = 'review'">返回继续修改</el-button>
      <el-button @click="closeDialog">关闭</el-button>
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
.unmatched-photo-stage { display: grid; min-height: 420px; place-items: center; overflow: hidden; border: 1px solid var(--el-border-color); background: var(--el-fill-color-lighter); }
.unmatched-photo-stage img { display: block; width: 100%; height: 100%; max-height: 620px; object-fit: contain; }
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
  .unmatched-photo-stage { min-height: min(48vh, 420px); }
  .unmatched-review-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .unmatched-review-actions :deep(.el-button) { width: 100%; }
  .unmatched-candidate-footer { align-items: stretch; flex-direction: column; }
}
</style>
