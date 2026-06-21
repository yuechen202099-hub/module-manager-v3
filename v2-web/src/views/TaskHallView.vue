<script setup lang="ts">
import { Finished, Refresh, Select } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'

import {
  classifyPhotoWithGroup,
  currentActor,
  deleteGroupPhoto,
  exportExceptionMeters,
  fetchGroupPhotoObjectUrl,
  fetchGroup,
  fetchTaskGroups,
  fetchTasks,
  groupPhotoContentUrl,
  resetGroupToUnconstructed,
  returnGroupToException,
  saveReview,
  updateGroupMetadata,
  uploadGroupImages,
} from '@/api/services'
import type { MaterialGroup, ReviewPhoto, ReviewTask } from '@/api/types'
import { useAuthStore } from '@/stores/auth'

const categories = [
  { key: 'before_box', label: '表箱整体改造前', hotkey: '1' },
  { key: 'collector_barcode', label: '采集器条形码', hotkey: '2' },
  { key: 'module_meter', label: '模块与电能表', hotkey: '3' },
  { key: 'after_box', label: '表箱整体改造后', hotkey: '4' },
]

const exceptionCategories = [
  { value: 'meter_error', label: '表号错误' },
  { value: 'collector_error', label: '采集器号错误' },
  { value: 'module_error', label: '模块号错误' },
  { value: 'photo_error', label: '照片错误' },
  { value: 'missing_photo', label: '照片缺失' },
  { value: 'site_blocked', label: '现场无法施工' },
  { value: 'device_mismatch', label: '设备不符' },
  { value: 'other', label: '其他' },
]

type GroupFilter = 'reviewable' | 'exception' | 'unconstructed' | 'archived' | 'all'

const auth = useAuthStore()
const actor = computed(() => auth.user?.username || auth.user?.id || currentActor())

const loadingTasks = ref(false)
const loadingGroups = ref(false)
const loadingGroup = ref(false)
const busy = ref(false)
const tasks = ref<ReviewTask[]>([])
const groups = ref<MaterialGroup[]>([])
const selectedTaskId = ref('')
const selectedGroupId = ref('')
const selectedPhotoId = ref('')
const selectedCategory = ref(categories[0].key)
const activeGroup = ref<MaterialGroup | null>(null)
const photos = ref<ReviewPhoto[]>([])
const errorMessage = ref('')
const groupFilter = ref<GroupFilter>('all')
const groupQuery = ref('')
const groupListRef = ref<HTMLElement | null>(null)
const photoFileInput = ref<HTMLInputElement | null>(null)
const imageFailed = ref(false)
const imageUseDirectFallback = ref(false)
const mainImageObjectUrl = ref('')
const imageLoading = ref(false)
const imageLoadError = ref(false)
const imageVersion = ref(0)
const pendingArchivePhotoIds = ref<Set<string>>(new Set())
const imagePreloadCache = new Set<string>()
let archiveQueue = Promise.resolve()
let backgroundRefreshTimer: number | null = null
let lastInteractionAt = Date.now()
let groupRequestSeq = 0
let imageRequestSeq = 0

const metadataDraft = reactive({
  meterNo: '',
  collector: '',
  moduleAssetNo: '',
})
const defaultExceptionCategory = exceptionCategories[0]?.value || 'other'
const exceptionDraft = reactive({
  category: defaultExceptionCategory,
  note: '',
})
const lightbox = reactive({
  open: false,
  scale: 1,
  x: 0,
  y: 0,
  dragging: false,
  startX: 0,
  startY: 0,
  originX: 0,
  originY: 0,
})

const filterOptions: Array<{ label: string; value: GroupFilter }> = [
  { label: '全部', value: 'all' },
  { label: '可审阅', value: 'reviewable' },
  { label: '异常', value: 'exception' },
  { label: '已归档', value: 'archived' },
  { label: '未施工', value: 'unconstructed' },
]

const myTasks = computed(() =>
  tasks.value.filter((task) => task.hasScanInfo && task.claimedBy === actor.value),
)
const selectedTask = computed(() => myTasks.value.find((task) => task.id === selectedTaskId.value) || null)
const selectedPhoto = computed(() => photos.value.find((photo) => photo.id === selectedPhotoId.value) || null)
const selectedPhotoIndex = computed(() => photos.value.findIndex((photo) => photo.id === selectedPhotoId.value))
const selectedPhotoPosition = computed(() => {
  if (!selectedPhoto.value) return '未选择'
  return `${selectedPhotoIndex.value + 1}/${photos.value.length}`
})
const visibleGroups = computed(() =>
  groups.value
    .filter((group) => {
      if (!groupMatchesQuery(group)) return false
      const status = reviewGroupStatus(group)
      if (groupFilter.value !== 'all' && status !== groupFilter.value) return false
      return Boolean(groupQuery.value.trim()) || groupFilter.value !== 'all' || status !== 'unconstructed'
    })
    .sort((left, right) => {
      const leftRank = groupRank(left)
      const rightRank = groupRank(right)
      if (leftRank !== rightRank) return leftRank - rightRank
      return String(left.address || left.meterNo).localeCompare(String(right.address || right.meterNo), 'zh-Hans-CN', {
        numeric: true,
      })
    }),
)
const progress = computed(() => {
  const reviewable = groups.value.filter((group) => Number(group.photoCount || 0) > 0)
  const done = reviewable.filter(isGroupDone).length
  return { total: reviewable.length, done, rate: reviewable.length ? Math.round((done / reviewable.length) * 100) : 0 }
})
const statusCounts = computed<Record<GroupFilter, number>>(() => {
  const counts: Record<GroupFilter, number> = { all: 0, reviewable: 0, exception: 0, unconstructed: 0, archived: 0 }
  groups.value.filter(groupMatchesQuery).forEach((group) => {
    const status = reviewGroupStatus(group)
    counts.all += 1
    counts[status] += 1
  })
  return counts
})
const reviewFilterTabs = computed(() =>
  filterOptions.map((item) => ({
    ...item,
    count: statusCounts.value[item.value],
  })),
)
const foldedUnconstructedCount = computed(() => {
  if (groupQuery.value.trim() || groupFilter.value !== 'all') return 0
  return groups.value.filter((group) => reviewGroupStatus(group) === 'unconstructed').length
})
const visibleGroupCountLabel = computed(() =>
  groupQuery.value.trim() || foldedUnconstructedCount.value ? `${visibleGroups.value.length}/${groups.value.length}` : `${groups.value.length}`,
)
const groupEmptyDescription = computed(() => {
  if (groupQuery.value.trim()) return '没有匹配的资料组'
  if (groupFilter.value === 'all' && foldedUnconstructedCount.value) return '未施工资料组已折叠，可通过搜索打开'
  return '当前筛选暂无资料组'
})
const mainImageUrl = computed(() => {
  if (!activeGroup.value || !selectedPhoto.value || !hasReadablePhotoSource(selectedPhoto.value)) return ''
  const directUrl = photoDirectPreviewUrl(selectedPhoto.value)
  return mainImageObjectUrl.value || (imageUseDirectFallback.value ? directUrl : '')
})
const lightboxStyle = computed(() => ({
  transform: `translate(${lightbox.x}px, ${lightbox.y}px) scale(${lightbox.scale})`,
}))
const lightboxScaleLabel = computed(() => (lightbox.scale <= 1 ? '适屏' : `${Math.round(lightbox.scale * 100)}%`))
function groupSearchText(group: MaterialGroup) {
  return [
    group.meterNo,
    group.address,
    group.terminal,
    group.reviewer,
    group.constructionCollector,
    group.constructionModuleAssetNo,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}

function groupMatchesQuery(group: MaterialGroup) {
  const keyword = groupQuery.value.trim().toLowerCase()
  return !keyword || groupSearchText(group).includes(keyword)
}

function reviewGroupStatus(group: MaterialGroup): GroupFilter {
  if (isExceptionGroup(group)) return 'exception'
  if (isGroupDone(group)) return 'archived'
  if (Number(group.photoCount || 0) === 0) return 'unconstructed'
  return 'reviewable'
}

function isPhotoArchived(photo: ReviewPhoto) {
  return (
    pendingArchivePhotoIds.value.has(photo.id) ||
    photo.archiveStatus === 'archived'
  )
}

function isExceptionGroup(group: MaterialGroup) {
  return group.status === 'exception' || Boolean(group.hasArchiveBlocker)
}

function groupIssueReasons(group: MaterialGroup) {
  const reasons: string[] = []
  const candidates = [
    ...(group.exceptionReasons || []),
    group.exceptionNote,
    group.status === 'exception' ? group.reviewNote : '',
  ]
  for (const value of candidates) {
    const text = String(value || '').trim()
    if (text && !reasons.includes(text)) reasons.push(text)
  }
  return reasons
}

function groupIssueReasonText(group: MaterialGroup) {
  return groupIssueReasons(group).join('；')
}

function isGroupDone(group: MaterialGroup) {
  if (group.status === 'complete' || group.status === 'approved') return true
  const groupPhotos = group.id === activeGroup.value?.id ? photos.value : group.photos || []
  return Boolean(groupPhotos.length) && groupPhotos.every(isPhotoArchived)
}

function isUnfinishedReviewGroup(group: MaterialGroup) {
  if (isExceptionGroup(group) || isGroupDone(group)) return false
  if (['approved', 'complete', 'exception', 'unmatched'].includes(String(group.status))) return false
  return Number(group.photoCount || group.photos?.length || 0) > 0
}

function groupRank(group: MaterialGroup) {
  const status = reviewGroupStatus(group)
  if (status === 'reviewable') return 0
  if (status === 'exception') return 1
  if (status === 'archived') return 2
  return 3
}

function groupStatusLabel(group: MaterialGroup) {
  if (isExceptionGroup(group)) return '异常'
  if (isGroupDone(group)) return '已归档'
  if (Number(group.photoCount || 0) === 0) return '未施工'
  return '待审阅'
}

function groupStatusTag(group: MaterialGroup) {
  const status = reviewGroupStatus(group)
  if (status === 'exception') return { label: '异常', type: 'warning' as const }
  if (status === 'archived') return { label: '已归档', type: 'success' as const }
  if (status === 'unconstructed') return { label: '未施工', type: 'info' as const }
  return { label: '可审阅', type: 'primary' as const }
}

function categoryLabel(key: string | undefined) {
  return categories.find((item) => item.key === key)?.label || '未分类'
}

function isBrowserImageUrl(url: string | undefined) {
  const value = String(url || '').trim()
  if (!value || value.startsWith('oss://')) return false
  if (value.startsWith('/') || value.startsWith('blob:') || value.startsWith('data:')) return true
  try {
    const parsed = new URL(value)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}

function firstBrowserImageUrl(candidates: Array<string | undefined>) {
  return candidates.find(isBrowserImageUrl) || ''
}

function photoDirectPreviewUrl(photo: ReviewPhoto | null | undefined) {
  if (!photo) return ''
  return firstBrowserImageUrl([
    photo.deliveryCacheUrl,
    photo.previewUrl,
    photo.thumbnailUrl,
    photo.imageUrl,
    photo.sourceUrl,
    photo.url,
  ])
}

function photoDirectThumbnailUrl(photo: ReviewPhoto | null | undefined) {
  if (!photo) return ''
  return firstBrowserImageUrl([
    photo.thumbnailUrl,
    photo.deliveryCacheUrl,
    photo.previewUrl,
    photo.imageUrl,
    photo.sourceUrl,
    photo.url,
  ])
}

function hasReadablePhotoSource(photo: ReviewPhoto | null | undefined) {
  if (!photo) return false
  const storageType = String(photo.storageType || '').toLowerCase()
  const hasStorageRef = Boolean(photo.storageKey && ['oss', 'local', 'local_upload', 'external_url'].includes(storageType))
  return Boolean(
    photoDirectPreviewUrl(photo) ||
      photoDirectThumbnailUrl(photo) ||
      hasStorageRef,
  )
}

function photoThumbUrl(photo: ReviewPhoto) {
  if (!hasReadablePhotoSource(photo)) return ''
  if (!activeGroup.value) return photoDirectThumbnailUrl(photo)
  return `${groupPhotoContentUrl(activeGroup.value.id, photo.id, 'thumbnail')}&v=${imageVersion.value}` || photoDirectThumbnailUrl(photo)
}

function replaceMainImageObjectUrl(url = '') {
  if (mainImageObjectUrl.value && mainImageObjectUrl.value !== url) {
    URL.revokeObjectURL(mainImageObjectUrl.value)
  }
  mainImageObjectUrl.value = url
}

function resetImageState() {
  imageFailed.value = false
  imageUseDirectFallback.value = false
  replaceMainImageObjectUrl('')
  imageLoading.value = Boolean(selectedPhoto.value && hasReadablePhotoSource(selectedPhoto.value))
  imageLoadError.value = false
  imageVersion.value += 1
}

async function loadSelectedPhotoImage() {
  const group = activeGroup.value
  const photo = selectedPhoto.value
  const requestSeq = ++imageRequestSeq
  replaceMainImageObjectUrl('')
  imageUseDirectFallback.value = false
  imageLoadError.value = false
  imageFailed.value = false

  if (!group || !photo || !hasReadablePhotoSource(photo)) {
    imageLoading.value = false
    return
  }

  imageLoading.value = true
  try {
    const objectUrl = await fetchGroupPhotoObjectUrl(group.id, photo.id, 'preview', String(imageVersion.value))
    if (requestSeq !== imageRequestSeq || activeGroup.value?.id !== group.id || selectedPhoto.value?.id !== photo.id) {
      URL.revokeObjectURL(objectUrl)
      return
    }
    replaceMainImageObjectUrl(objectUrl)
  } catch {
    if (requestSeq !== imageRequestSeq || activeGroup.value?.id !== group.id || selectedPhoto.value?.id !== photo.id) return
    const directFallback = photoDirectPreviewUrl(photo)
    if (directFallback) {
      imageUseDirectFallback.value = true
      return
    }
    imageLoading.value = false
    imageLoadError.value = true
    imageFailed.value = true
  }
}

function preloadImages(items: ReviewPhoto[]) {
  items.slice(0, 8).forEach((photo) => {
    const url = photoThumbUrl(photo)
    if (!url || imagePreloadCache.has(url)) return
    imagePreloadCache.add(url)
    const image = new Image()
    image.decoding = 'async'
    image.loading = 'eager'
    image.src = url
  })
}

function handleMainImageLoad() {
  imageLoading.value = false
  imageLoadError.value = false
}

function handleMainImageError() {
  if (!selectedPhoto.value) return
  const directFallback = photoDirectPreviewUrl(selectedPhoto.value)
  if (!imageUseDirectFallback.value && directFallback && directFallback !== mainImageUrl.value) {
    replaceMainImageObjectUrl('')
    imageUseDirectFallback.value = true
    imageFailed.value = true
    imageLoading.value = true
    imageLoadError.value = false
    return
  }
  imageLoading.value = false
  imageLoadError.value = true
  imageFailed.value = true
  ElMessage.error('图片加载失败，请切换图片或刷新后重试')
}

function resetLightbox() {
  lightbox.scale = 1
  lightbox.x = 0
  lightbox.y = 0
  lightbox.dragging = false
}

function openLightbox() {
  if (!selectedPhoto.value) return
  resetLightbox()
  lightbox.open = true
}

function closeLightbox() {
  lightbox.open = false
  resetLightbox()
}

function clampLightboxPan() {
  if (lightbox.scale <= 1) {
    lightbox.x = 0
    lightbox.y = 0
    return
  }
  const maxOffset = 420 * (lightbox.scale - 1)
  lightbox.x = Math.max(-maxOffset, Math.min(maxOffset, lightbox.x))
  lightbox.y = Math.max(-maxOffset, Math.min(maxOffset, lightbox.y))
}

function zoomLightbox(delta: number) {
  lightbox.scale = Math.max(1, Math.min(5, Number((lightbox.scale * delta).toFixed(2))))
  clampLightboxPan()
}

function toggleLightboxZoom() {
  if (lightbox.scale <= 1) {
    lightbox.scale = 2
  } else {
    resetLightbox()
  }
  clampLightboxPan()
}

function startPan(event: PointerEvent) {
  if (lightbox.scale <= 1) return
  lightbox.dragging = true
  lightbox.startX = event.clientX
  lightbox.startY = event.clientY
  lightbox.originX = lightbox.x
  lightbox.originY = lightbox.y
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}

function movePan(event: PointerEvent) {
  if (!lightbox.dragging) return
  lightbox.x = lightbox.originX + event.clientX - lightbox.startX
  lightbox.y = lightbox.originY + event.clientY - lightbox.startY
  clampLightboxPan()
}

function endPan() {
  lightbox.dragging = false
  clampLightboxPan()
}

async function loadTasks() {
  loadingTasks.value = true
  errorMessage.value = ''
  try {
    tasks.value = await fetchTasks()
    if (!myTasks.value.some((task) => task.id === selectedTaskId.value)) {
      selectedTaskId.value = myTasks.value[0]?.id || ''
    }
    if (selectedTaskId.value) {
      await loadGroups(selectedTaskId.value)
    } else {
      groups.value = []
      activeGroup.value = null
      photos.value = []
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '任务加载失败'
  } finally {
    loadingTasks.value = false
  }
}

async function loadGroups(taskId: string) {
  selectedTaskId.value = taskId
  loadingGroups.value = true
  selectedGroupId.value = ''
  activeGroup.value = null
  photos.value = []
  resetImageState()
  groupRequestSeq += 1
  try {
    groups.value = await fetchTaskGroups(taskId)
    const first =
      visibleGroups.value.find((group) => Number(group.photoCount || 0) > 0 && !isGroupDone(group)) || visibleGroups.value[0]
    if (first) {
      await loadGroup(first.id)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '资料组加载失败'
  } finally {
    loadingGroups.value = false
  }
}

async function loadGroup(groupId: string, preferredPhotoId = '') {
  const requestSeq = ++groupRequestSeq
  const cachedGroup = groups.value.find((group) => String(group.id) === String(groupId))
  loadingGroup.value = !cachedGroup
  selectedGroupId.value = groupId
  if (cachedGroup) {
    activeGroup.value = { ...cachedGroup, photos: cachedGroup.photos || [] }
    photos.value = cachedGroup.photos || []
    selectPhoto(photos.value.find((photo) => !isPhotoArchived(photo)) || photos.value[0] || null)
  }
  resetImageState()
  try {
    const result = await fetchGroup(groupId)
    if (requestSeq !== groupRequestSeq || selectedGroupId.value !== groupId) return
    activeGroup.value = result.group
    photos.value = result.photos
    syncDraftsFromGroup()
    const preferred = preferredPhotoId ? photos.value.find((photo) => photo.id === preferredPhotoId) : null
    const firstPending = photos.value.find((photo) => !isPhotoArchived(photo))
    const nextPhoto = preferred || firstPending || photos.value[0]
    selectPhoto(nextPhoto || null)
    preloadImages(photos.value)
    syncGroupEntry(result.group)
    await scrollActiveGroupIntoView()
  } catch (error) {
    if (requestSeq !== groupRequestSeq || selectedGroupId.value !== groupId) return
    errorMessage.value = error instanceof Error ? error.message : '资料组详情加载失败'
  } finally {
    if (requestSeq === groupRequestSeq && selectedGroupId.value === groupId) {
      loadingGroup.value = false
    }
  }
}

function syncDraftsFromGroup() {
  const photo = photos.value[0]
  metadataDraft.meterNo = activeGroup.value?.meterNo || photo?.barcode || ''
  metadataDraft.collector = photo?.collector || activeGroup.value?.constructionCollector || ''
  metadataDraft.moduleAssetNo = photo?.moduleAssetNo || activeGroup.value?.constructionModuleAssetNo || ''
  exceptionDraft.category = defaultExceptionCategory
  exceptionDraft.note = activeGroup.value ? groupIssueReasonText(activeGroup.value) : ''
}

async function scrollActiveGroupIntoView() {
  await nextTick()
  await new Promise((resolve) => requestAnimationFrame(resolve))
  const root = groupListRef.value
  const active = root?.querySelector<HTMLElement>('.review-list-card.active')
  if (!root || !active) return
  const rootRect = root.getBoundingClientRect()
  const activeRect = active.getBoundingClientRect()
  const targetTop = root.scrollTop + activeRect.top - rootRect.top - (root.clientHeight - active.offsetHeight) / 2
  const previousScrollBehavior = root.style.scrollBehavior
  root.style.scrollBehavior = 'auto'
  root.scrollTop = Math.max(0, targetTop)
  root.style.scrollBehavior = previousScrollBehavior
}

function syncGroupEntry(group: MaterialGroup) {
  groups.value = groups.value.map((item) => (item.id === group.id ? { ...item, ...group, photos: group.photos || item.photos } : item))
}

function makeGroupVisible(group: MaterialGroup) {
  const status = reviewGroupStatus(group)
  const hiddenByFilter = groupFilter.value !== 'all' && groupFilter.value !== status
  const hiddenBySearch = Boolean(groupQuery.value.trim()) && !groupMatchesQuery(group)
  if (hiddenByFilter || hiddenBySearch) {
    groupFilter.value = 'all'
    groupQuery.value = ''
  }
}

function applyPhotoUpdate(photo: ReviewPhoto) {
  photos.value = photos.value.map((item) => (item.id === photo.id ? { ...item, ...photo } : item))
  if (activeGroup.value) {
    activeGroup.value = { ...activeGroup.value, photos: photos.value, photoCount: photos.value.length }
    syncGroupEntry(activeGroup.value)
  }
}

function setPhotoArchivePending(photoId: string, pending: boolean) {
  const next = new Set(pendingArchivePhotoIds.value)
  if (pending) next.add(photoId)
  else next.delete(photoId)
  pendingArchivePhotoIds.value = next
}

function optimisticArchivedPhoto(photo: ReviewPhoto, category: string): ReviewPhoto {
  return {
    ...photo,
    category,
    archiveStatus: 'archived',
    status: photo.status === 'exception' ? photo.status : 'valid',
  }
}

function selectPhoto(photo: ReviewPhoto | null) {
  selectedPhotoId.value = photo?.id || ''
  selectedCategory.value = photo?.category && photo.category !== 'unclassified' ? photo.category : categories[0].key
  resetImageState()
}

function setSelectedCategory(category: string) {
  selectedCategory.value = category
  if (!selectedPhoto.value || !category) return
  const updated = { ...selectedPhoto.value, category }
  applyPhotoUpdate(updated)
}

function plannedPhotoCategory(photo: ReviewPhoto, index: number, overrides: Record<string, string> = {}) {
  if (overrides[photo.id]) return overrides[photo.id]
  if (photo.category && photo.category !== 'unclassified') return photo.category
  return categories[Math.min(index, categories.length - 1)]?.key || categories[0].key
}

function duplicateCategoryLabels(overrides: Record<string, string> = {}, includeDefaults = false) {
  const counts = new Map<string, number>()
  photos.value.forEach((photo, index) => {
    const key = includeDefaults
      ? plannedPhotoCategory(photo, index, overrides)
      : overrides[photo.id] || (photo.category && photo.category !== 'unclassified' ? photo.category : '')
    if (!key) return
    counts.set(key, (counts.get(key) || 0) + 1)
  })
  return Array.from(counts.entries())
    .filter(([, count]) => count > 1)
    .map(([key]) => categoryLabel(key))
}

function ensureNoDuplicateCategories(overrides: Record<string, string> = {}, includeDefaults = false) {
  const duplicates = duplicateCategoryLabels(overrides, includeDefaults)
  if (!duplicates.length) return true
  ElMessage.warning(`分类重复：${duplicates.join('、')}。请先选中对应照片修改分类后再归档。`)
  return false
}

function markInteraction() {
  lastInteractionAt = Date.now()
}

function shouldDeferBackgroundRefresh() {
  return (
    busy.value ||
    loadingGroup.value ||
    loadingGroups.value ||
    pendingArchivePhotoIds.value.size > 0 ||
    Date.now() - lastInteractionAt < 3200
  )
}

async function refreshGroupsSilently() {
  if (!selectedTaskId.value) return
  const currentTaskId = selectedTaskId.value
  const currentActiveGroupId = activeGroup.value?.id
  const refreshed = await fetchTaskGroups(currentTaskId)
  if (selectedTaskId.value !== currentTaskId) return
  groups.value = refreshed.map((group) => {
    if (currentActiveGroupId && group.id === currentActiveGroupId && activeGroup.value) {
      return { ...group, photos: photos.value }
    }
    return group
  })
}

async function refreshTasksSilently() {
  const currentTaskId = selectedTaskId.value
  const refreshed = await fetchTasks()
  tasks.value = refreshed
  if (currentTaskId && !myTasks.value.some((task) => task.id === currentTaskId)) {
    selectedTaskId.value = myTasks.value[0]?.id || ''
    if (selectedTaskId.value) await loadGroups(selectedTaskId.value)
  }
}

async function externalRefresh() {
  if (shouldDeferBackgroundRefresh()) return
  try {
    await refreshTasksSilently()
    if (selectedTaskId.value) await refreshGroupsSilently()
  } catch {
    // 后台刷新失败不打断当前审阅动作，下一轮刷新再试。
  }
}

function firstUnfinishedGroup(excludeGroupId = '') {
  if (groupFilter.value !== 'all') groupFilter.value = 'all'
  if (groupQuery.value.trim()) groupQuery.value = ''
  const isSelectable = (group: MaterialGroup) => group.id !== excludeGroupId && isUnfinishedReviewGroup(group)
  return visibleGroups.value.find(isSelectable) || groups.value.find(isSelectable)
}

function enqueueArchiveRequest(job: {
  groupId: string
  photoId: string
  category: string
  previousPhoto: ReviewPhoto
  completedGroup: boolean
}) {
  const run = async () => {
    try {
      const result = await classifyPhotoWithGroup(job.groupId, job.photoId, job.category)
      const updatedPhoto = { ...result.photo, archiveStatus: result.photo.archiveStatus || 'archived', category: job.category }
      if (activeGroup.value?.id === job.groupId) {
        applyPhotoUpdate(updatedPhoto)
      }
      if (result.group) syncGroupEntry(result.group)

      if (job.completedGroup) {
        const updated = await saveReview(job.groupId, 'approved')
        if (activeGroup.value?.id === job.groupId) {
          activeGroup.value = { ...activeGroup.value, ...updated, photos: photos.value }
        }
        syncGroupEntry({ ...(updated as MaterialGroup), photos: activeGroup.value?.id === job.groupId ? photos.value : updated.photos })
        await refreshGroupsSilently()
      }
    } catch (error) {
      if (activeGroup.value?.id === job.groupId) {
        applyPhotoUpdate(job.previousPhoto)
        selectPhoto(job.previousPhoto)
      }
      ElMessage.error(error instanceof Error ? error.message : '归档失败')
    } finally {
      setPhotoArchivePending(job.photoId, false)
    }
  }
  archiveQueue = archiveQueue.then(run, run)
  return archiveQueue
}

async function archiveCurrentPhoto() {
  if (!activeGroup.value || !selectedPhoto.value || busy.value || pendingArchivePhotoIds.value.has(selectedPhoto.value.id)) return
  markInteraction()
  const groupId = activeGroup.value.id
  const currentPhotoId = selectedPhoto.value.id
  const category = selectedCategory.value
  if (!ensureNoDuplicateCategories({ [currentPhotoId]: category }, false)) return
  const previousPhoto = { ...selectedPhoto.value }
  const currentIndex = photos.value.findIndex((photo) => photo.id === currentPhotoId)

  setPhotoArchivePending(currentPhotoId, true)
  applyPhotoUpdate(optimisticArchivedPhoto(selectedPhoto.value, category))

  const nextPending =
    photos.value.slice(currentIndex + 1).find((photo) => !isPhotoArchived(photo)) ||
    photos.value.find((photo) => !isPhotoArchived(photo))
  const completedGroup = !nextPending
  if (nextPending) {
    selectPhoto(nextPending)
  } else {
    const nextGroup = firstUnfinishedGroup(groupId)
    if (nextGroup) {
      makeGroupVisible(nextGroup)
      void loadGroup(nextGroup.id)
    }
  }

  void enqueueArchiveRequest({ groupId, photoId: currentPhotoId, category, previousPhoto, completedGroup })
}

async function archiveGroup() {
  if (!activeGroup.value || busy.value) return
  markInteraction()
  if (!ensureNoDuplicateCategories({}, true)) return
  busy.value = true
  try {
    for (let index = 0; index < photos.value.length; index += 1) {
      const photo = photos.value[index]
      if (isPhotoArchived(photo)) continue
      const category = plannedPhotoCategory(photo, index)
      const result = await classifyPhotoWithGroup(activeGroup.value.id, photo.id, category)
      applyPhotoUpdate({ ...result.photo, archiveStatus: result.photo.archiveStatus || 'archived', category })
      if (result.group) syncGroupEntry(result.group)
    }
    await completeGroupIfReady()
    ElMessage.success(activeGroup.value.hasArchiveBlocker ? '资料组已存在异常，处理后再归档' : '当前资料组已归档')
    await selectNextUnfinishedGroup(activeGroup.value.id)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '资料组归档失败')
  } finally {
    busy.value = false
  }
}

async function completeGroupIfReady() {
  if (!activeGroup.value || !photos.value.length || !photos.value.every(isPhotoArchived)) return
  const updated = await saveReview(activeGroup.value.id, 'approved')
  activeGroup.value = { ...activeGroup.value, ...updated, photos: photos.value }
  syncGroupEntry(activeGroup.value)
}

async function saveCurrentGroup() {
  if (!activeGroup.value || busy.value) return
  markInteraction()
  busy.value = true
  try {
    const updated = await updateGroupMetadata(activeGroup.value.id, {
      meter_no: metadataDraft.meterNo.trim(),
      collector: metadataDraft.collector.trim(),
      module_asset_no: metadataDraft.moduleAssetNo.trim(),
    })
    activeGroup.value = { ...activeGroup.value, ...updated, photos: photos.value }
    syncGroupEntry(activeGroup.value)
    await completeGroupIfReady()
    ElMessage.success('资料组已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    busy.value = false
  }
}

async function restorePending() {
  if (!activeGroup.value || busy.value) return
  markInteraction()
  busy.value = true
  try {
    const status = photos.value.length >= 4 ? 'pending' : 'incomplete'
    const updated = await saveReview(activeGroup.value.id, status, { note: '恢复待审', exceptionNote: '' })
    activeGroup.value = { ...activeGroup.value, ...updated, photos: photos.value }
    syncDraftsFromGroup()
    syncGroupEntry(activeGroup.value)
    void refreshTasksSilently().catch(() => undefined)
    void refreshGroupsSilently().catch(() => undefined)
    ElMessage.success('已恢复为待审')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '恢复失败')
  } finally {
    busy.value = false
  }
}

async function resetUnconstructed() {
  if (!activeGroup.value || busy.value) return
  markInteraction()
  try {
    await ElMessageBox.confirm('确认回退到未施工？将清空采集器号、模块号和当前资料组照片，原文件保留审计记录。', '回退未施工', {
      type: 'warning',
      confirmButtonText: '确认回退',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  busy.value = true
  try {
    const result = await resetGroupToUnconstructed(activeGroup.value.id, exceptionDraft.note || '审阅回退未施工')
    if (result.group) {
      activeGroup.value = { ...result.group, photos: [] }
      photos.value = []
      selectedPhotoId.value = ''
      syncDraftsFromGroup()
      syncGroupEntry(activeGroup.value)
    }
    void refreshTasksSilently().catch(() => undefined)
    void refreshGroupsSilently().catch(() => undefined)
    ElMessage.success('已回退未施工，施工端需重新采集')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '回退失败')
  } finally {
    busy.value = false
  }
}

async function markException() {
  if (!activeGroup.value || busy.value) return
  markInteraction()
  const note = exceptionDraft.note.trim() || groupIssueReasonText(activeGroup.value) || '人工标记异常'
  busy.value = true
  try {
    const result = await returnGroupToException(activeGroup.value.id, {
      category: exceptionDraft.category,
      note,
    })
    if (result.group) {
      activeGroup.value = { ...activeGroup.value, ...result.group, photos: photos.value }
      syncDraftsFromGroup()
      syncGroupEntry(activeGroup.value)
    }
    void refreshTasksSilently().catch(() => undefined)
    void refreshGroupsSilently().catch(() => undefined)
    ElMessage.warning('已生成施工异常工单')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '转异常工单失败')
  } finally {
    busy.value = false
  }
}

function choosePhotos() {
  markInteraction()
  photoFileInput.value?.click()
}

async function compressSupplementImage(file: File): Promise<File> {
  if (!file.type.startsWith('image/') || file.type.includes('gif')) return file
  const objectUrl = URL.createObjectURL(file)
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image()
      img.onload = () => resolve(img)
      img.onerror = () => reject(new Error('Image read failed'))
      img.src = objectUrl
    })
    const maxSide = 1600
    const width = image.naturalWidth || image.width
    const height = image.naturalHeight || image.height
    const scale = Math.min(1, maxSide / Math.max(width, height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(width * scale))
    canvas.height = Math.max(1, Math.round(height * scale))
    const context = canvas.getContext('2d', { alpha: false })
    if (!context) return file
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.78))
    if (!blob) return file
    if (blob.size >= file.size && file.type === 'image/jpeg') return file
    const baseName = file.name.replace(/\.[^.]+$/, '') || 'supplement-photo'
    return new File([blob], `${baseName}.jpg`, { type: 'image/jpeg', lastModified: Date.now() })
  } catch {
    return file
  } finally {
    URL.revokeObjectURL(objectUrl)
  }
}

function handleExternalRefresh(event: MessageEvent) {
  if (event.data?.type === 'module-manager:data-refresh') {
    void externalRefresh()
  }
}

async function uploadPhotos(event: Event) {
  if (!activeGroup.value || busy.value) return
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (!files.length) return
  busy.value = true
  try {
    const updated = await updateGroupMetadata(activeGroup.value.id, {
      meter_no: metadataDraft.meterNo.trim(),
      collector: metadataDraft.collector.trim(),
      module_asset_no: metadataDraft.moduleAssetNo.trim(),
    })
    activeGroup.value = { ...activeGroup.value, ...updated, photos: photos.value }
    syncGroupEntry(activeGroup.value)
    const compressedFiles = await Promise.all(files.map((file) => compressSupplementImage(file)))
    const result = await uploadGroupImages(activeGroup.value.id, {
      collector: metadataDraft.collector.trim(),
      moduleAssetNo: metadataDraft.moduleAssetNo.trim(),
      creator: actor.value,
      files: compressedFiles,
    })
    if (result.group) {
      activeGroup.value = result.group
      photos.value = result.group.photos || []
      syncGroupEntry(result.group)
      selectPhoto(photos.value.find((photo) => !isPhotoArchived(photo)) || photos.value[0] || null)
    } else {
      await loadGroup(activeGroup.value.id)
    }
    resetImageState()
    ElMessage.success(`已补图 ${result.uploadedUrls.length} 张`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '补图失败')
  } finally {
    busy.value = false
  }
}

async function deleteCurrentPhoto() {
  if (!activeGroup.value || !selectedPhoto.value || busy.value) return
  markInteraction()
  try {
    await ElMessageBox.confirm('确认删除当前图片？删除后资料组会回到待审状态。', '删除图片', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  busy.value = true
  try {
    const groupId = activeGroup.value.id
    const currentIndex = selectedPhotoIndex.value
    await deleteGroupPhoto(groupId, selectedPhoto.value.id)
    await loadGroup(groupId, photos.value[currentIndex + 1]?.id || photos.value[currentIndex - 1]?.id || '')
    void refreshTasksSilently().catch(() => undefined)
    void refreshGroupsSilently().catch(() => undefined)
    ElMessage.success('已删除当前图')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '删除失败')
  } finally {
    busy.value = false
  }
}

async function exportExceptions() {
  markInteraction()
  try {
    await exportExceptionMeters()
    ElMessage.success('异常表计已导出')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '导出失败')
  }
}

async function selectNextUnfinishedGroup(completedGroupId = '') {
  await loadGroups(selectedTaskId.value)
  const next = firstUnfinishedGroup(completedGroupId)
  if (next) {
    makeGroupVisible(next)
    await loadGroup(next.id)
  }
}

function movePhoto(delta: number) {
  markInteraction()
  if (!photos.value.length) return
  const index = selectedPhotoIndex.value >= 0 ? selectedPhotoIndex.value : 0
  const next = Math.max(0, Math.min(photos.value.length - 1, index + delta))
  selectPhoto(photos.value[next])
}

async function moveGroup(delta: number) {
  markInteraction()
  if (!visibleGroups.value.length) return
  const index = visibleGroups.value.findIndex((group) => group.id === selectedGroupId.value)
  const next = Math.max(0, Math.min(visibleGroups.value.length - 1, (index >= 0 ? index : 0) + delta))
  await loadGroup(visibleGroups.value[next].id)
}

function handleKeydown(event: KeyboardEvent) {
  if (lightbox.open && event.key === 'Escape') {
    closeLightbox()
    event.preventDefault()
    return
  }
  if (lightbox.open && (event.key === '+' || event.key === '=')) {
    zoomLightbox(1.25)
    event.preventDefault()
    return
  }
  if (lightbox.open && event.key === '-') {
    zoomLightbox(0.8)
    event.preventDefault()
    return
  }
  if (lightbox.open && event.key === '0') {
    resetLightbox()
    event.preventDefault()
    return
  }
  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement) return
  const category = categories.find((item) => item.hotkey === event.key)
  if (category) {
    markInteraction()
    setSelectedCategory(category.key)
    event.preventDefault()
    return
  }
  if (event.key === 'Enter') {
    void archiveCurrentPhoto()
    event.preventDefault()
    return
  }
  if (event.key === 'ArrowLeft') {
    movePhoto(-1)
    event.preventDefault()
  }
  if (event.key === 'ArrowRight') {
    movePhoto(1)
    event.preventDefault()
  }
  if (event.key === 'ArrowUp') {
    void moveGroup(-1)
    event.preventDefault()
  }
  if (event.key === 'ArrowDown') {
    void moveGroup(1)
    event.preventDefault()
  }
}

watch(
  [selectedGroupId, selectedPhotoId, imageVersion],
  () => {
    void loadSelectedPhotoImage()
  },
  { flush: 'post' },
)

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  window.addEventListener('message', handleExternalRefresh)
  backgroundRefreshTimer = window.setInterval(() => {
    void externalRefresh()
  }, 10000)
  void loadTasks()
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('message', handleExternalRefresh)
  imageRequestSeq += 1
  replaceMainImageObjectUrl('')
  if (backgroundRefreshTimer) {
    window.clearInterval(backgroundRefreshTimer)
    backgroundRefreshTimer = null
  }
})
</script>

<template>
  <section class="taskhall-workbench-page">
    <section class="native-review-page review-workbench-v24">
      <ElAlert v-if="errorMessage" type="error" :closable="false" :title="errorMessage" />

    <aside class="panel review-task-panel">
      <div class="review-panel-head">
        <div>
          <h3>任务</h3>
          <p class="muted">仅显示我已领取的终端</p>
        </div>
        <ElButton :icon="Refresh" circle :loading="loadingTasks" @click="loadTasks" />
      </div>
      <div class="review-progress">
        <span>{{ progress.done }}/{{ progress.total }}</span>
        <ElProgress :percentage="progress.rate" :show-text="false" />
      </div>
      <div class="review-task-list">
        <button
          v-for="task in myTasks"
          :key="task.id"
          class="review-list-card task-card-simple"
          :class="{ active: task.id === selectedTaskId }"
          type="button"
          @click="loadGroups(task.id)"
        >
          <strong>终端 {{ task.terminal || task.id }}</strong>
          <span>{{ task.claimedBy ? `已由 ${task.claimedBy} 领取` : '未领取' }}</span>
          <div class="task-mini-metrics">
            <b>改造 {{ task.renovationCount || task.totalGroups || 0 }}</b>
            <b>未审 {{ task.unreviewedCount || 0 }}</b>
          </div>
        </button>
        <ElEmpty v-if="!loadingTasks && !myTasks.length" description="暂无已领取任务" />
      </div>
    </aside>

    <aside class="panel review-group-panel">
      <div class="review-panel-head">
        <div>
          <h3>{{ selectedTask ? `终端 ${selectedTask.terminal || selectedTask.id}` : '资料组' }}</h3>
          <p class="muted">{{ selectedTask ? '按状态分类筛选' : '领取任务后显示资料组' }}</p>
        </div>
        <ElTag effect="plain">{{ visibleGroupCountLabel }}</ElTag>
      </div>
      <div class="review-filter-row">
        <div class="review-status-tabs" role="group" aria-label="资料组状态筛选">
          <button
            v-for="item in reviewFilterTabs"
            :key="item.value"
            class="review-status-tab"
            :class="[`status-${item.value}`, { active: groupFilter === item.value }]"
            type="button"
            @click="groupFilter = item.value"
          >
            <span>{{ item.label }}</span>
            <strong>{{ item.count }}</strong>
          </button>
        </div>
        <el-input v-model="groupQuery" placeholder="搜索表号、地址、终端、采集器或模块号" clearable />
      </div>
      <ElSkeleton v-if="loadingGroups" :rows="8" animated />
      <div v-else ref="groupListRef" class="review-group-list">
        <div v-if="foldedUnconstructedCount" class="folded-note">
          已折叠 {{ foldedUnconstructedCount }} 个未施工资料组。如需人工补完施工，可搜索表号、终端、地址、采集器或模块号打开。
        </div>
        <button
          v-for="group in visibleGroups"
          :key="group.id"
          class="review-list-card"
          :class="[
            `status-${reviewGroupStatus(group)}`,
            {
              active: group.id === selectedGroupId,
              done: isGroupDone(group),
              exception: isExceptionGroup(group),
            },
          ]"
          type="button"
          @click="markInteraction(); loadGroup(group.id)"
        >
          <div class="review-card-main">
            <div class="review-card-title">
              <strong>{{ group.meterNo || group.id }}</strong>
              <ElTag :type="groupStatusTag(group).type" effect="light">{{ groupStatusTag(group).label }}</ElTag>
            </div>
            <span>{{ group.terminal }} / {{ group.address || '未匹配地址' }}</span>
            <small>
              {{ Number(group.photoCount || group.photos?.length || 0) }} 张
              <template v-if="group.reviewer"> / 审阅人 {{ group.reviewer }}</template>
            </small>
            <small v-if="groupIssueReasonText(group)" class="warn-text">{{ groupIssueReasonText(group) }}</small>
          </div>
        </button>
        <ElEmpty v-if="!visibleGroups.length" :description="groupEmptyDescription" />
      </div>
    </aside>

    <main class="panel review-stage-panel">
      <div class="review-panel-head">
        <div>
          <h3>图片审阅</h3>
          <p class="muted">1-4 分类，方向键切换，Enter 归档；双击图片看完整大图</p>
        </div>
        <ElTag effect="plain">{{ selectedPhotoPosition }}</ElTag>
      </div>

      <ElSkeleton v-if="loadingGroup" :rows="10" animated />
      <template v-else-if="activeGroup">
        <div
          v-if="selectedPhoto"
          class="review-image-box review-image-viewer"
          :class="{ loading: imageLoading, error: imageLoadError }"
          @dblclick="openLightbox"
        >
          <img
            v-if="mainImageUrl"
            :key="mainImageUrl"
            :src="mainImageUrl"
            alt="审阅图片"
            loading="eager"
            decoding="async"
            fetchpriority="high"
            @load="handleMainImageLoad"
            @error="handleMainImageError"
          />
          <div v-else-if="imageLoading" class="image-placeholder">图片加载中，请稍候</div>
          <div v-else class="image-placeholder">当前图片没有可用地址</div>
          <div v-if="imageLoadError" class="image-error-tip">图片加载失败，请切换图片或刷新后重试</div>
        </div>
        <div v-else class="empty-review-block">
          <strong>{{ Number(activeGroup.photoCount || 0) === 0 ? '未施工资料组' : '暂无可审阅图片' }}</strong>
          <span>可以先修正表号、采集器、模块号，或通过补图加入照片。</span>
        </div>

        <div v-if="photos.length" class="review-photo-strip">
          <button
            v-for="(photo, index) in photos"
            :key="photo.id"
            class="photo-chip"
            :class="{ active: photo.id === selectedPhotoId, done: isPhotoArchived(photo) }"
            type="button"
            @click="markInteraction(); selectPhoto(photo)"
            @dblclick="openLightbox"
          >
            <img v-if="photoThumbUrl(photo)" :src="photoThumbUrl(photo)" alt="" loading="lazy" decoding="async" />
            <span v-else class="photo-thumb-empty" aria-hidden="true"></span>
            <span>#{{ index + 1 }} {{ categoryLabel(photo.category) }}</span>
          </button>
        </div>

        <div class="review-meta-grid editable-meta-grid">
          <label>
            <span>表号 / 扫码内容</span>
            <input v-model="metadataDraft.meterNo" />
          </label>
          <label>
            <span>采集器</span>
            <input v-model="metadataDraft.collector" />
          </label>
          <label>
            <span>模块</span>
            <input v-model="metadataDraft.moduleAssetNo" />
          </label>
          <div>
            <span>安装人员</span>
            <strong>{{ selectedPhoto?.creator || activeGroup.reviewer || '-' }}</strong>
          </div>
        </div>

        <div class="category-grid review-category-grid">
          <button
            v-for="item in categories"
            :key="item.key"
            class="category-key"
            :class="{ active: selectedCategory === item.key }"
            type="button"
            @click="markInteraction(); setSelectedCategory(item.key)"
          >
            <span class="category-hotkey">{{ item.hotkey }}</span>
            {{ item.label }}
          </button>
        </div>

        <section class="inline-exception-panel">
          <div class="exception-fields">
            <el-select v-model="exceptionDraft.category" placeholder="异常类型">
              <el-option v-for="item in exceptionCategories" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-input v-model="exceptionDraft.note" placeholder="异常说明，可选" clearable />
          </div>
          <p class="muted">地址来自总清单，不在审阅页修改。这里只处理表号、采集器、模块号和照片问题。</p>
        </section>

        <input ref="photoFileInput" class="hidden-file-input" type="file" accept="image/*" multiple @change="uploadPhotos" />
        <div class="review-action-row review-action-grid">
          <ElButton :loading="busy" @click="saveCurrentGroup">保存资料组</ElButton>
          <ElButton :loading="busy" @click="choosePhotos">补图</ElButton>
          <ElButton :loading="busy" @click="restorePending">恢复待审</ElButton>
          <ElButton type="danger" plain :loading="busy" @click="resetUnconstructed">回退未施工</ElButton>
          <ElButton type="danger" plain :loading="busy" @click="markException">转异常工单</ElButton>
          <ElButton type="danger" plain :disabled="!selectedPhoto" :loading="busy" @click="deleteCurrentPhoto">删除当前图</ElButton>
          <ElButton :icon="Finished" :disabled="!photos.length" :loading="busy" @click="archiveGroup">归档当前资料组</ElButton>
          <ElButton type="primary" :icon="Select" :disabled="!selectedPhoto" :loading="busy" @click="archiveCurrentPhoto">
            Enter 归档当前图
          </ElButton>
          <ElButton @click="exportExceptions">导出异常表计</ElButton>
        </div>
      </template>
      <ElEmpty v-else description="请选择资料组开始审阅" />
    </main>

    <Teleport to="body">
      <div v-if="lightbox.open && selectedPhoto" class="review-lightbox" @click.self="closeLightbox">
        <header>
          <div>
            <strong>{{ activeGroup?.meterNo || selectedPhoto.barcode || '大图审阅' }}</strong>
            <span>{{ categoryLabel(selectedPhoto.category) }} · 滚轮缩放，拖动查看，Esc 关闭</span>
          </div>
          <div class="lightbox-tools">
            <button type="button" @click="zoomLightbox(0.8)">-</button>
            <button type="button" @click="resetLightbox">适屏</button>
            <button type="button" @click="zoomLightbox(1.25)">+</button>
            <span class="lightbox-scale">{{ lightboxScaleLabel }}</span>
            <button type="button" @click="closeLightbox">Esc</button>
          </div>
        </header>
        <main
          class="lightbox-stage"
          :class="{ panning: lightbox.dragging }"
          @wheel.prevent="zoomLightbox($event.deltaY > 0 ? 0.9 : 1.1)"
          @dblclick.stop="toggleLightboxZoom"
          @pointerdown="startPan"
          @pointermove="movePan"
          @pointerup="endPan"
          @pointercancel="endPan"
        >
          <div class="lightbox-pan" :style="lightboxStyle">
            <img :src="mainImageUrl || selectedPhoto.url" alt="完整大图" draggable="false" />
          </div>
        </main>
        <footer class="lightbox-foot">
          <div class="lightbox-categories" role="group" aria-label="大图分类">
            <button
              v-for="(item, index) in categories"
              :key="item.key"
              type="button"
              class="lightbox-category"
              :class="{ active: selectedCategory === item.key }"
              @click.stop="setSelectedCategory(item.key)"
            >
              <span>{{ index + 1 }}</span>{{ item.label }}
            </button>
          </div>
          <span class="lightbox-hint">双击切换 2x/适屏，滚轮缩放，拖动查看，1-4 分类，Enter 归档，Esc 关闭</span>
        </footer>
      </div>
      </Teleport>
    </section>

  </section>
</template>

<style scoped>
.taskhall-workbench-page {
  display: grid;
  grid-template-rows: minmax(0, 1fr);
  gap: 8px;
  min-height: calc(100dvh - 96px);
}

.review-workbench-v24 {
  grid-template-columns: minmax(220px, 250px) minmax(300px, 360px) minmax(0, 1fr);
}

.task-card-simple {
  gap: 8px;
}

.task-mini-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.task-mini-metrics b {
  padding: 6px 8px;
  border-radius: var(--v2-radius-sm);
  background: var(--v2-bg-subtle);
  color: var(--v2-text-strong);
  font-size: 12px;
  white-space: nowrap;
}

.review-filter-row {
  display: grid;
  gap: 8px;
  padding: 10px;
  border-bottom: 1px solid var(--v2-border-soft);
}

.review-status-tabs {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 6px;
}

.review-status-tab {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-width: 0;
  min-height: 40px;
  padding: 0 5px;
  overflow: hidden;
  border: 1px solid var(--v2-border-soft);
  border-radius: 9px;
  background: #fff;
  color: var(--v2-text-muted);
  cursor: pointer;
  font-size: 11px;
  font-weight: 800;
}

.review-status-tab.active {
  border-color: rgba(15, 111, 143, 0.45);
  background: var(--v2-accent-soft);
  color: var(--v2-accent-strong);
}

.review-status-tab span {
  flex: 0 0 auto;
  white-space: nowrap;
}

.review-status-tab strong {
  flex: 0 0 auto;
  color: inherit;
  font-size: 12px;
  font-weight: 900;
}

.review-list-card.status-unconstructed {
  border-style: dashed;
}

.review-list-card.status-exception {
  border-color: rgba(180, 83, 9, 0.35);
}

.review-card-main {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.review-card-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.review-card-title strong,
.review-card-main span,
.review-card-main small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.folded-note {
  margin-bottom: 8px;
  padding: 10px;
  border: 1px dashed var(--v2-border);
  border-radius: var(--v2-radius-md);
  background: #fbfdff;
  color: var(--v2-text-muted);
  font-size: 12px;
  line-height: 1.45;
}

.warn-text {
  color: var(--v2-warning);
}

.review-image-viewer {
  position: relative;
  min-height: 430px;
  cursor: zoom-in;
}

.review-image-viewer img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  object-position: center;
  transition: opacity 0.12s ease;
}

.review-image-viewer.loading::after {
  position: absolute;
  right: 14px;
  bottom: 14px;
  padding: 7px 10px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.82);
  color: #e6f0f7;
  content: "图片加载中";
  font-size: 12px;
  font-weight: 800;
}

.review-image-viewer.error img {
  opacity: 0.35;
}

.image-error-tip {
  position: absolute;
  right: 14px;
  bottom: 14px;
  max-width: min(420px, calc(100% - 28px));
  padding: 8px 10px;
  border-radius: 999px;
  background: rgba(164, 38, 31, 0.92);
  color: #fff;
  font-size: 12px;
  font-weight: 800;
}

.image-placeholder,
.empty-review-block {
  display: grid;
  place-items: center;
  min-height: 280px;
  padding: 24px;
  color: var(--v2-text-muted);
  text-align: center;
}

.empty-review-block {
  align-content: center;
  gap: 8px;
  margin: 10px;
  border: 1px dashed var(--v2-border);
  border-radius: var(--v2-radius-panel);
  background: var(--v2-bg-subtle);
}

.editable-meta-grid label,
.editable-meta-grid div {
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--v2-border-soft);
  border-radius: var(--v2-radius-md);
  background: var(--v2-bg-subtle);
}

.editable-meta-grid input {
  width: 100%;
  min-width: 0;
  margin-top: 4px;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--v2-text-strong);
  font: inherit;
  font-weight: 800;
}

.inline-exception-panel {
  display: grid;
  gap: 6px;
  padding: 0 10px 10px;
}

.exception-fields {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 8px;
}

.hidden-file-input {
  display: none;
}

.review-action-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.review-lightbox {
  position: fixed;
  inset: 0;
  z-index: 4000;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 10px;
  padding: 14px;
  background: rgba(5, 12, 19, 0.94);
}

.review-lightbox header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  color: #eaf4fb;
}

.review-lightbox header div:first-child {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.review-lightbox strong,
.review-lightbox span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-lightbox span {
  color: #9fb0be;
  font-size: 12px;
}

.lightbox-tools {
  display: flex;
  gap: 6px;
}

.lightbox-tools button {
  min-width: 44px;
  height: 34px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.08);
  color: #eaf4fb;
  cursor: pointer;
}

.lightbox-scale {
  display: inline-grid;
  min-width: 52px;
  height: 34px;
  place-items: center;
  color: #9fb0be;
  font-family: var(--v2-font-mono);
  font-size: 12px;
  font-weight: 800;
}

.lightbox-stage {
  display: grid;
  place-items: center;
  min-height: 0;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  background: #050b12;
  cursor: grab;
}

.lightbox-stage.panning {
  cursor: grabbing;
}

.lightbox-pan {
  display: grid;
  place-items: center;
  width: 100%;
  height: 100%;
  transform-origin: center;
}

.lightbox-pan img {
  display: block;
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  user-select: none;
}

.lightbox-foot {
  display: grid;
  gap: 8px;
}

.lightbox-categories {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.lightbox-category {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 38px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.06);
  color: #dcebf3;
  cursor: pointer;
  font-weight: 800;
}

.lightbox-category.active {
  border-color: rgba(34, 211, 238, 0.7);
  background: rgba(34, 211, 238, 0.14);
  color: #ffffff;
}

.lightbox-category span {
  display: inline-grid;
  width: 22px;
  height: 22px;
  margin-right: 8px;
  place-items: center;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
  font-family: var(--v2-font-mono);
  font-size: 12px;
}

.lightbox-hint {
  color: #9fb0be;
  font-size: 12px;
  text-align: right;
}

@media (max-width: 1180px) {
  .taskhall-workbench-page {
    min-height: auto;
  }

  .review-workbench-v24 {
    grid-template-columns: 1fr;
  }

  .review-task-list,
  .review-group-list {
    max-height: 260px;
  }

  .review-image-viewer {
    min-height: 48dvh;
  }
}

@media (max-width: 640px) {
  .review-status-tabs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .exception-fields,
  .editable-meta-grid {
    grid-template-columns: 1fr;
  }

  .review-category-grid {
    grid-template-columns: 1fr 1fr;
  }

  .review-lightbox {
    padding: 8px;
  }

  .review-lightbox header {
    align-items: stretch;
    flex-direction: column;
  }

  .lightbox-categories {
    grid-template-columns: 1fr 1fr;
  }

  .lightbox-hint {
    text-align: left;
  }
}
</style>

