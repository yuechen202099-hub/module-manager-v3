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
import { useRouter } from 'vue-router'

import {
  assignConstructionTask,
  closeConstructionTask,
  currentActor,
  currentTeamId,
  fetchConstructionExceptionOrders,
  fetchConstructionTaskGroups,
  fetchConstructionTasks,
  fetchGroup,
  openConstructionTask,
  submitConstructionExceptionOrder,
  unassignConstructionTask,
  uploadConstructionBatch,
} from '@/api/services'
import type {
  ConstructionExceptionOrder,
  ConstructionPhotoSlot,
  MaterialGroup,
  ReviewPhoto,
  ReviewTask,
} from '@/api/types'
import { useAuthStore } from '@/stores/auth'

type GroupFilter = 'unbuilt' | 'cached' | 'exception' | 'all'
type PhotoSource = 'camera' | 'album'
type ScannerTarget = 'quickMeter' | 'collector' | 'module'

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
  photos?: DraftPhoto[]
  status?: string
  created_at?: string
  updated_at?: string
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
  kind: 'group' | 'cached' | 'exception'
  group: MaterialGroup
  order?: ConstructionExceptionOrder
  draft?: CacheDraft
}

const slots: ConstructionPhotoSlot[] = [
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
const collator = new Intl.Collator('zh-Hans-CN', { numeric: true, sensitivity: 'base' })

const auth = useAuthStore()
const router = useRouter()
const actor = computed(() => auth.user?.username || auth.user?.id || currentActor())
const teamId = computed(() => auth.user?.teamId || currentTeamId())
const isAdmin = computed(() => auth.user?.role === 'admin' || auth.user?.roles?.includes('admin'))

const loadingTasks = ref(false)
const loadingGroups = ref(false)
const uploading = ref(false)
const cacheBusy = ref(false)
const offlineMode = ref(false)
const tasks = ref<ReviewTask[]>([])
const groups = ref<MaterialGroup[]>([])
const exceptionOrders = ref<ConstructionExceptionOrder[]>([])
const drafts = ref<CacheDraft[]>([])
const selectedTaskId = ref('')
const selectedItemKey = ref('')
const taskPickerOpen = ref(false)
const groupFilter = ref<GroupFilter>('all')
const groupQuery = ref('')
const quickMeter = ref('')
const errorMessage = ref('')
const collectOpen = ref(false)
const scannerOpen = ref(false)
const scannerTarget = ref<ScannerTarget>('quickMeter')
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
let suspendDraftAutoPersist = false

const form = reactive({
  collector: '',
  moduleAssetNo: '',
  note: '',
})

const QUAGGA_READERS = [
  'code_128_reader',
  'code_39_reader',
  'code_93_reader',
  'i2of5_reader',
  'ean_reader',
  'ean_8_reader',
  'codabar_reader',
]

const visibleTasks = computed(() => {
  const source = isAdmin.value
    ? tasks.value
    : tasks.value.filter((task) => task.constructionClaimedBy === actor.value || task.assignedConstructor === actor.value)
  return [...source].sort((left, right) => {
    const leftUploaded = Number(left.constructionUploadedCount || left.uploadedCount || 0)
    const rightUploaded = Number(right.constructionUploadedCount || right.uploadedCount || 0)
    if (isAdmin.value && leftUploaded !== rightUploaded) return rightUploaded - leftUploaded
    return collator.compare(String(left.terminal || left.id), String(right.terminal || right.id))
  })
})

const selectedTask = computed(() => visibleTasks.value.find((task) => task.id === selectedTaskId.value) || null)
const inTaskPicker = computed(() => !selectedTask.value || taskPickerOpen.value)
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
const cachedTaskDrafts = computed(() => taskDrafts.value.filter((draft) => !isExceptionDraft(draft)))
const readyCachedDrafts = computed(() => cachedTaskDrafts.value.filter((draft) => draftReady(draft)))
const draftByGroupId = computed(() => {
  const map = new Map<string, CacheDraft>()
  for (const draft of taskDrafts.value) {
    const groupId = draftGroupId(draft)
    if (groupId) map.set(groupId, draft)
  }
  return map
})

const groupFilterCounts = computed(() => {
  const keyword = normalizeSearch(groupQuery.value)
  const cachedGroupIds = new Set(cachedTaskDrafts.value.map((draft) => draftGroupId(draft)).filter(Boolean))
  const exceptionGroupIds = exceptionGroupIdSet.value
  const byQuery = groups.value.filter((group) => matchesGroupQuery(group, keyword) && !group.exceptionOrderId && !exceptionGroupIds.has(String(group.id)))
  const exceptionGroups = exceptionOrders.value
    .map((order) => order.group || orderToGroup(order))
    .filter((group) => matchesGroupQuery(group, keyword))
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
    const draft = draftByGroupId.value.get(group.id)
    items.push({ key: `group-${group.id}`, kind: draft ? 'cached' : 'group', group, draft })
    seen.add(group.id)
  }

  for (const order of exceptionOrders.value) {
    const group = order.group || groupMap.get(order.groupId) || orderToGroup(order)
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

  for (const draft of taskDrafts.value) {
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
      const rank: Record<WorkItem['kind'], number> = { group: 0, cached: 1, exception: 2 }
      if (rank[left.kind] !== rank[right.kind]) return rank[left.kind] - rank[right.kind]
      return collator.compare(left.group.address || left.group.meterNo || left.key, right.group.address || right.group.meterNo || right.key)
    })
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
  return slots.filter((slot) => slot.required && !hasSlotPhoto(activeGroup.value, slot.key)).map((slot) => slot.label)
})

const activeExistingPhotos = computed(() => activeGroup.value?.photos?.filter((photo) => photoUrl(photo)) || [])

const canUploadCurrent = computed(() => {
  if (!activeGroup.value) return false
  if (!form.moduleAssetNo.trim()) return false
  if (missingRequiredSlots.value.length) return false
  return Boolean(Object.values(selectedFiles.value).some(Boolean) || activeOrder.value)
})
const canShowCurrentUpload = computed(() => groupFilter.value === 'cached' && Boolean(activeGroup.value && draftByGroupId.value.get(activeGroup.value.id)))

const scannerTitle = computed(() => {
  if (scannerTarget.value === 'collector') return '扫描采集器'
  if (scannerTarget.value === 'module') return '扫描模块号'
  return '扫描表号'
})

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
  return normalized.length > 2 ? normalized.slice(2) : normalized
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

function taskStatus(task: ReviewTask) {
  if (task.constructionClaimedBy === actor.value || task.assignedConstructor === actor.value) return '已指派给我'
  if (task.constructionClaimedBy || task.assignedConstructor) return `已指派 ${task.constructionClaimedBy || task.assignedConstructor}`
  if (task.constructionEnabled) return '待指派'
  return '未开放'
}

function taskProgress(task: ReviewTask) {
  const total = Number(task.renovationCount || task.totalGroups || 0)
  const uploaded = Number(task.constructionUploadedCount || task.uploadedCount || 0)
  return total ? Math.round((uploaded / total) * 100) : 0
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
  return {
    id: order.groupId || order.id,
    taskId: order.taskId || '',
    address: order.address || '',
    meterNo: order.meterNo || '',
    terminal: order.terminal || '',
    status: 'exception',
    photoCount: order.group?.photoCount || order.group?.photos?.length || 0,
    constructionCollector: order.group?.constructionCollector || '',
    constructionModuleAssetNo: order.group?.constructionModuleAssetNo || '',
    constructionStatus: 'exception',
    exceptionOrderId: order.id,
    exceptionNote: order.note,
    photos: order.group?.photos || [],
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

function existingPhotoForSlot(group: MaterialGroup | null, slotKey: string) {
  if (!group?.photos?.length) return null
  const aliases = slotAliases[slotKey] || [slotKey]
  return (
    group.photos.find((photo) => photo.category === slotKey) ||
    group.photos.find((photo) => {
      const text = `${photo.category || ''} ${photo.categoryLabel || ''} ${photo.archiveFilename || ''} ${photo.name || ''}`
      return aliases.some((alias) => text.includes(alias))
    }) ||
    null
  )
}

function hasSlotPhoto(group: MaterialGroup | null, slotKey: string) {
  return Boolean(selectedFiles.value[slotKey] || existingPhotoForSlot(group, slotKey))
}

function coveredSlotsForGroup(group: MaterialGroup | null) {
  return slots.filter((slot) => existingPhotoForSlot(group, slot.key)).map((slot) => slot.key)
}

function clearPreviews() {
  for (const url of Object.values(previewUrls.value)) URL.revokeObjectURL(url)
  previewUrls.value = {}
}

function resetCollectorForm() {
  form.collector = ''
  form.moduleAssetNo = ''
  form.note = ''
  activeGroup.value = null
  activeOrder.value = null
  selectedFiles.value = {}
  selectedItemKey.value = ''
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
}

async function startScanner(target: ScannerTarget) {
  scannerTarget.value = target
  scannerOpen.value = true
  scanCandidate = ''
  scanCandidateHits = 0
  scanLocked = false
  scannerStatus.value = '正在启动相机，请允许浏览器使用摄像头。'
  scannerHint.value =
    target === 'collector'
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
  const current =
    scannerTarget.value === 'collector'
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
    drafts.value = await withStore<CacheDraft[]>(DRAFT_STORE, 'readonly', (store) => store.getAll())
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
  return slots.filter((slot) => slot.required && !covered.has(slot.key)).map((slot) => slot.label)
}

function draftReady(draft: CacheDraft) {
  return Boolean((draft.groupId || draft.group_id) && draft.module_asset_no && missingSlotsForDraft(draft).length === 0)
}

async function loadDraftIntoForm(group: MaterialGroup) {
  suspendDraftAutoPersist = true
  try {
    selectedFiles.value = {}
    clearPreviews()
    const draft = await getDraft(draftKey(selectedTaskId.value, group.id))
    form.collector = draft?.collector ?? group.constructionCollector ?? group.photos?.[0]?.collector ?? ''
    form.moduleAssetNo = draft?.module_asset_no ?? group.constructionModuleAssetNo ?? group.photos?.[0]?.moduleAssetNo ?? ''
    form.note = draft?.exception_note ?? group.exceptionNote ?? activeOrder.value?.note ?? ''
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
  const photos = Object.entries(selectedFiles.value)
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
  return {
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
    photos,
    status: 'queued',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }
}

async function persistCurrentDraft() {
  if (!activeGroup.value || !selectedTask.value) return
  const draft = buildCurrentDraft()
  if (draftHasContent(draft)) await putDraft(draft)
  else await deleteDraft(draft.client_batch_id)
  await loadDrafts()
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
  if (!draft.module_asset_no?.trim()) throw new Error('模块资产编号为必填项')
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
      collector: draft.collector || '',
      moduleAssetNo: draft.module_asset_no || '',
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

async function handleTaskAdminAction(task: ReviewTask, action: 'assign' | 'unassign' | 'open' | 'close') {
  try {
    if (action === 'assign') {
      const { value } = await ElMessageBox.prompt('请输入施工员账号', task.constructionClaimedBy || task.assignedConstructor || '', {
        confirmButtonText: '指派',
        cancelButtonText: '取消',
        inputValue: task.constructionClaimedBy || task.assignedConstructor || '',
      })
      const constructor = String(value || '').trim()
      if (!constructor) return
      await assignConstructionTask(task.id, constructor)
      ElMessage.success('已指派施工终端')
    }
    if (action === 'unassign') {
      await unassignConstructionTask(task.id)
      ElMessage.success('已取消指派')
    }
    if (action === 'open') {
      await openConstructionTask(task.id)
      ElMessage.success('已开放施工')
    }
    if (action === 'close') {
      await closeConstructionTask(task.id)
      ElMessage.success('已关闭施工')
    }
    await loadTasks()
  } catch (error) {
    if (error === 'cancel') return
    ElMessage.error(error instanceof Error ? error.message : '操作失败')
  }
}

async function selectTask(task: ReviewTask) {
  await flushCurrentDraftPersist()
  selectedTaskId.value = task.id
  selectedItemKey.value = ''
  groupQuery.value = ''
  quickMeter.value = ''
  groupFilter.value = 'all'
  taskPickerOpen.value = false
  resetCollectorForm()
  await loadGroups()
}

async function useSnapshot(taskId: string, reason = '') {
  const snapshot = await getTerminalSnapshot(taskId)
  if (!snapshot) throw new Error(reason || '当前终端没有可用离线包，请先在有网时打开一次')
  offlineMode.value = true
  groups.value = sortGroupsByAddress(snapshot.groups || [])
  exceptionOrders.value = snapshot.exceptionOrders || []
  const exists = tasks.value.some((task) => task.id === snapshot.task.id)
  if (!exists) tasks.value = [snapshot.task, ...tasks.value]
}

async function loadTasks() {
  loadingTasks.value = true
  errorMessage.value = ''
  try {
    await loadDrafts()
    if (!online()) throw new Error('offline')
    tasks.value = await fetchConstructionTasks(isAdmin.value)
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
    if (!selectedTaskId.value || !visibleTasks.value.some((task) => task.id === selectedTaskId.value)) {
      selectedTaskId.value = visibleTasks.value[0]?.id || ''
      taskPickerOpen.value = isAdmin.value || visibleTasks.value.length !== 1
    }
    loadingTasks.value = false
  }
  if (selectedTaskId.value) await loadGroups()
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
    groups.value = sortGroupsByAddress(taskGroups)
    exceptionOrders.value = orders
    offlineMode.value = false
    if (selectedTask.value) await putTerminalSnapshot(selectedTask.value, taskGroups, orders)
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
  selectedItemKey.value = item.key
  activeOrder.value = item.order || null
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
    ElMessage.warning('当前终端未找到该表号，可切换终端后再试')
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
  taskPickerOpen.value = true
}

watch(
  () => [form.collector, form.moduleAssetNo, form.note],
  () => {
    if (suspendDraftAutoPersist || !activeGroup.value) return
    scheduleCurrentDraftPersist()
  },
)

onMounted(() => {
  window.addEventListener('message', handleExternalRefresh)
  void loadTasks()
})

watch(collectOpen, (open, oldOpen) => {
  if (!open && oldOpen) void flushCurrentDraftPersist()
})

onBeforeUnmount(() => {
  window.removeEventListener('message', handleExternalRefresh)
  window.clearTimeout(draftPersistTimer)
  void flushCurrentDraftPersist()
  closeScanner()
  clearPreviews()
})
</script>

<template>
  <section class="construction-v24" :class="{ 'is-work-mode': !inTaskPicker, 'is-task-mode': inTaskPicker }">
    <header class="construction-top panel">
      <div>
        <p class="eyebrow">施工采集</p>
        <h2>按终端指派施工，按地址快速采集</h2>
        <p class="muted">先缓存，后上传；弱网现场也能连续施工。</p>
      </div>
      <div class="top-actions">
        <el-tag v-if="offlineMode" type="warning" effect="light">离线包</el-tag>
        <el-button :icon="Refresh" :loading="loadingTasks || loadingGroups" @click="loadTasks">刷新</el-button>
        <el-button
          v-if="groupFilter === 'cached' && cachedTaskDrafts.length"
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
            <h3>开放终端</h3>
            <span>管理员指派后施工员可进入施工</span>
          </div>
          <div class="head-actions">
            <el-tag v-if="offlineMode" type="warning" effect="light">离线包</el-tag>
            <el-tag effect="light">{{ visibleTasks.length }}</el-tag>
            <el-button size="small" :icon="Refresh" :loading="loadingTasks" @click="loadTasks">刷新</el-button>
            <el-button size="small" class="construction-panel-logout" @click="logoutConstruction">退出</el-button>
          </div>
        </div>
        <div v-loading="loadingTasks" class="task-list">
          <button
            v-for="task in visibleTasks"
            :key="task.id"
            class="task-card"
            :class="{ active: task.id === selectedTaskId }"
            @click="selectTask(task)"
          >
            <div class="task-title">
              <strong>终端 {{ task.terminal || task.id }}</strong>
              <el-tag :type="task.constructionClaimedBy || task.assignedConstructor ? 'success' : 'info'" effect="light">
                {{ taskStatus(task) }}
              </el-tag>
            </div>
            <div class="task-metrics">
              <span><em>改造数</em><strong>{{ task.renovationCount || task.totalGroups || 0 }}</strong></span>
              <span><em>已上传</em><strong>{{ task.constructionUploadedCount || task.uploadedCount || 0 }}</strong></span>
              <span><em>未施工</em><strong>{{ task.constructionUnbuiltCount || Math.max((task.renovationCount || task.totalGroups || 0) - (task.constructionUploadedCount || task.uploadedCount || 0), 0) }}</strong></span>
              <span><em>异常</em><strong>{{ task.constructionExceptionCount || 0 }}</strong></span>
            </div>
            <div class="task-progress">
              <i :style="{ width: `${taskProgress(task)}%` }" />
              <b>{{ taskProgress(task) }}%</b>
            </div>
            <div v-if="isAdmin" class="task-actions" @click.stop>
              <el-button size="small" @click="handleTaskAdminAction(task, 'assign')">
                {{ task.constructionClaimedBy || task.assignedConstructor ? '改派' : '指派' }}
              </el-button>
              <el-button
                v-if="task.constructionClaimedBy || task.assignedConstructor"
                size="small"
                @click="handleTaskAdminAction(task, 'unassign')"
              >
                取消
              </el-button>
              <el-button
                size="small"
                :type="task.constructionEnabled ? 'warning' : 'primary'"
                @click="handleTaskAdminAction(task, task.constructionEnabled ? 'close' : 'open')"
              >
                {{ task.constructionEnabled ? '关闭' : '开放' }}
              </el-button>
            </div>
          </button>
          <el-empty v-if="!loadingTasks && !visibleTasks.length" description="暂无指派施工终端" />
        </div>
      </aside>

      <main v-show="!inTaskPicker" class="panel group-panel">
        <div class="panel-head group-head">
          <div>
            <h3>{{ selectedTask ? `终端 ${selectedTask.terminal || selectedTask.id}` : '施工区' }}</h3>
            <span>未施工也会显示，便于现场逐户核对</span>
          </div>
          <div class="head-actions">
            <el-button size="small" @click="returnToTaskPicker">返回任务区</el-button>
            <el-tag effect="light">{{ groupSummary.total }}</el-tag>
            <el-button size="small" :icon="Refresh" :loading="loadingGroups" @click="loadGroups">刷新</el-button>
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
            </article>
            <el-empty
              v-if="!loadingGroups && selectedTask && !visibleWorkItems.length"
              description="当前筛选下没有资料组，可切换分类或搜索表号"
            />
            <el-empty v-if="!loadingGroups && !selectedTask" description="请先选择一个终端任务" />
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
                <p class="eyebrow">{{ activeOrder ? '异常工单处理' : '施工采集单' }}</p>
                <h3>{{ activeGroup.meterNo || activeGroup.id }}</h3>
                <span>{{ activeGroup.terminal || selectedTask?.terminal || '-' }} / {{ activeGroup.address || '未填写地址' }}</span>
              </div>
              <el-tag v-if="activeOrder" type="danger" effect="light">{{ activeOrder.category || '异常' }}</el-tag>
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

            <div class="field-grid">
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

            <section class="slot-grid">
              <article v-for="(slot, index) in slots" :key="slot.key" class="photo-slot">
                <div class="slot-title">
                  <strong>{{ index + 1 }}. {{ slot.label }} <b v-if="slot.required">*</b></strong>
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
                    <span>{{ slot.required ? '必填照片' : '可选照片' }}</span>
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
            </section>

            <div v-if="missingRequiredSlots.length || !form.moduleAssetNo.trim()" class="sheet-warning">
              <span v-if="!form.moduleAssetNo.trim()">模块资产编号必填。</span>
              <span v-if="missingRequiredSlots.length">缺少：{{ missingRequiredSlots.join('、') }}</span>
            </div>

            <footer class="sheet-actions">
              <span class="draft-status">{{ Object.values(selectedFiles).filter(Boolean).length }} 张本地待上传</span>
              <el-button size="large" :loading="cacheBusy" @click="saveCurrentDraft()">保存缓存</el-button>
              <el-button v-if="canShowCurrentUpload" size="large" type="primary" :loading="uploading" :disabled="!canUploadCurrent" @click="uploadCurrentDraft">
                上传当前组
              </el-button>
            </footer>
          </div>
        </div>
      </aside>
    </div>

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

        <div class="field-grid">
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

        <section class="slot-grid">
          <article v-for="(slot, index) in slots" :key="slot.key" class="photo-slot">
            <div class="slot-title">
              <strong>{{ index + 1 }}. {{ slot.label }} <b v-if="slot.required">*</b></strong>
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
                <span>{{ slot.required ? '必填照片' : '可选照片' }}</span>
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
        </section>

        <div v-if="missingRequiredSlots.length || !form.moduleAssetNo.trim()" class="sheet-warning">
          <span v-if="!form.moduleAssetNo.trim()">模块资产编号必填。</span>
          <span v-if="missingRequiredSlots.length">缺少：{{ missingRequiredSlots.join('、') }}</span>
        </div>

        <footer class="sheet-actions">
          <span class="draft-status">{{ Object.values(selectedFiles).filter(Boolean).length }} 张本地待上传</span>
          <el-button size="large" :loading="cacheBusy" @click="saveCurrentDraft()">保存缓存</el-button>
          <el-button v-if="canShowCurrentUpload" size="large" type="primary" :loading="uploading" :disabled="!canUploadCurrent" @click="uploadCurrentDraft">
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

.task-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
}

.task-metrics span {
  min-width: 0;
  border-radius: 9px;
  background: #f7fafc;
  padding: 8px;
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

.task-progress b {
  color: #667085;
  font-size: 12px;
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
</style>
