<script setup lang="ts">
import { BrowserMultiFormatReader } from '@zxing/browser'
import { Camera, CopyDocument, EditPen, Refresh, Search, Warning } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, nextTick, onUnmounted, reactive, ref } from 'vue'

import {
  bulkArchiveAdminGroups,
  fetchGroupPhotoObjectUrl,
  resetAdminGroupToUnconstructed,
  resetAdminGroupToUnreviewed,
  searchGroups,
  updateAdminGroupMetadata,
} from '@/api/services'
import type { MaterialGroup, ReviewPhoto, TaskStatus } from '@/api/types'

type EditableGroupForm = {
  meterNo: string
  meterMatchKey: string
  terminal: string
  address: string
  status: TaskStatus
  reviewer: string
  reviewNote: string
  exceptionNote: string
  collector: string
  moduleAssetNo: string
  constructionCollector: string
  constructionModuleAssetNo: string
}

type BarcodeDetectorInstance = {
  detect: (source: HTMLVideoElement) => Promise<Array<{ rawValue?: string }>>
}

type BarcodeDetectorConstructor = new (options?: { formats?: string[] }) => BarcodeDetectorInstance

const query = ref('')
const terminal = ref('')
const loading = ref(false)
const searched = ref(false)
const saving = ref(false)
const total = ref(0)
const terminals = ref<string[]>([])
const groups = ref<MaterialGroup[]>([])
const selectedGroups = ref<MaterialGroup[]>([])
const errorMessage = ref('')
const editOpen = ref(false)
const activeGroup = ref<MaterialGroup | null>(null)
const photoDialogOpen = ref(false)
const photoDialogLoading = ref(false)
const photoGroup = ref<MaterialGroup | null>(null)
const groupPhotoObjectUrls = reactive<Record<string, string>>({})
const groupPhotoErrors = reactive<Record<string, string>>({})
const groupPhotoPreviewOpen = ref(false)
const activeGroupPhotoUrl = ref('')
const activeGroupPhotoTitle = ref('')
const resetReason = ref('')
const scannerOpen = ref(false)
const scannerStatus = ref('将条形码放入取景框，识别后会自动搜索。')
const scannerManual = ref('')
const scannerVideo = ref<HTMLVideoElement | null>(null)
const scannerFileInput = ref<HTMLInputElement | null>(null)
let scannerStream: MediaStream | null = null
let scannerTimer = 0
let scannerLocked = false
let zxingControls: { stop: () => void } | null = null
const zxingReader = new BrowserMultiFormatReader()
let groupPhotoLoadSerial = 0

const editForm = reactive<EditableGroupForm>({
  meterNo: '',
  meterMatchKey: '',
  terminal: '',
  address: '',
  status: 'pending',
  reviewer: '',
  reviewNote: '',
  exceptionNote: '',
  collector: '',
  moduleAssetNo: '',
  constructionCollector: '',
  constructionModuleAssetNo: '',
})

const trimmedQuery = computed(() => query.value.trim())
const canSearch = computed(() => Boolean(trimmedQuery.value || terminal.value))
const selectedCount = computed(() => selectedGroups.value.length)

const statusLabels: Record<string, string> = {
  pending: '待审阅',
  unreviewed: '待审阅',
  incomplete: '需补充',
  exception: '异常',
  rejected: '异常',
  approved: '已通过',
  complete: '已完成',
  locked: '已锁定',
  released: '已释放',
  published: '已发布',
}

const statusOptions: Array<{ label: string; value: TaskStatus }> = [
  { label: '待审阅', value: 'pending' },
  { label: '需补充', value: 'incomplete' },
  { label: '已通过', value: 'approved' },
  { label: '异常', value: 'exception' },
]

async function runSearch() {
  if (!canSearch.value) {
    ElMessage.warning('请输入表号、模块号、采集器号、地址，或选择终端')
    return
  }
  loading.value = true
  searched.value = true
  errorMessage.value = ''
  try {
    const result = await searchGroups({
      query: trimmedQuery.value,
      terminal: terminal.value,
      limit: 80,
      offset: 0,
    })
    total.value = result.total
    terminals.value = result.terminals
    groups.value = result.items
    selectedGroups.value = []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '搜索失败'
    groups.value = []
    selectedGroups.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function resetSearch() {
  query.value = ''
  terminal.value = ''
  searched.value = false
  errorMessage.value = ''
  groups.value = []
  selectedGroups.value = []
  total.value = 0
}

function statusLabel(status: string) {
  return statusLabels[status] || status || '未知'
}

function barcodeProgress(row: MaterialGroup) {
  const totalCount = Number(row.groupBarcodeTotalCount || 3)
  const passedCount = Math.max(0, Math.min(totalCount, Number(row.groupBarcodePassedCount || 0)))
  return { passedCount, totalCount }
}

function barcodeProgressLabel(row: MaterialGroup) {
  const { passedCount, totalCount } = barcodeProgress(row)
  return `扫码通过${passedCount}/${totalCount}`
}

function barcodeProgressType(row: MaterialGroup) {
  const { passedCount, totalCount } = barcodeProgress(row)
  if (totalCount > 0 && passedCount >= totalCount) return 'success'
  if (passedCount > 0) return 'warning'
  return 'danger'
}

function photoCategoryLabel(row: MaterialGroup) {
  const classified = Number(row.photoCategoryClassifiedCount || 0)
  const totalCount = Number(row.photoCategoryTotalCount || row.photoCount || 0)
  if (row.photoCategoryComplete) return `已分类${classified}/${totalCount}`
  return `未完成${classified}/${totalCount}`
}

function groupPhotoKey(groupId: string, photoId: string) {
  return `${groupId}:${photoId}`
}

function groupPhotoUrl(groupId: string, photoId: string) {
  return groupPhotoObjectUrls[groupPhotoKey(groupId, photoId)] || ''
}

function clearGroupPhotoObjectUrls(invalidateLoads = true) {
  if (invalidateLoads) {
    groupPhotoLoadSerial += 1
  }
  for (const [key, url] of Object.entries(groupPhotoObjectUrls)) {
    URL.revokeObjectURL(url)
    delete groupPhotoObjectUrls[key]
  }
  for (const key of Object.keys(groupPhotoErrors)) {
    delete groupPhotoErrors[key]
  }
}

function isGroupPhotoLoadCurrent(loadSerial: number, groupId: string) {
  return photoDialogOpen.value && groupPhotoLoadSerial === loadSerial && photoGroup.value?.id === groupId
}

function openGroupPhotoPreview(group: MaterialGroup | null, photo: ReviewPhoto) {
  const url = group ? groupPhotoUrl(group.id, photo.id) : ''
  if (!url) return
  activeGroupPhotoUrl.value = url
  activeGroupPhotoTitle.value = `${photo.categoryLabel || photo.category || '资料组照片'} - ${group?.meterNo || group?.id || ''}`
  groupPhotoPreviewOpen.value = true
}

function handleGroupPhotoRenderedError(group: MaterialGroup | null, photo: ReviewPhoto) {
  if (!group) return
  const key = groupPhotoKey(group.id, photo.id)
  const url = groupPhotoObjectUrls[key]
  if (url) {
    URL.revokeObjectURL(url)
    delete groupPhotoObjectUrls[key]
  }
  groupPhotoErrors[key] = '图片加载失败'
  if (activeGroupPhotoUrl.value === url) {
    activeGroupPhotoUrl.value = ''
    groupPhotoPreviewOpen.value = false
  }
}

async function openGroupPhotos(group: MaterialGroup) {
  photoGroup.value = group
  photoDialogOpen.value = true
  photoDialogLoading.value = true
  clearGroupPhotoObjectUrls()
  const loadSerial = groupPhotoLoadSerial
  try {
    await Promise.all(
      (group.photos || []).map((photo) =>
        (async () => {
          const key = groupPhotoKey(group.id, photo.id)
          let objectUrl = ''
          try {
            try {
              objectUrl = await fetchGroupPhotoObjectUrl(group.id, photo.id, 'preview')
            } catch {
              if (!isGroupPhotoLoadCurrent(loadSerial, group.id)) return
              objectUrl = await fetchGroupPhotoObjectUrl(group.id, photo.id, 'original')
            }
            if (!objectUrl) return
            if (!isGroupPhotoLoadCurrent(loadSerial, group.id)) {
              URL.revokeObjectURL(objectUrl)
              return
            }
            const previousUrl = groupPhotoObjectUrls[key]
            if (previousUrl && previousUrl !== objectUrl) {
              URL.revokeObjectURL(previousUrl)
            }
            groupPhotoObjectUrls[key] = objectUrl
          } catch (error) {
            if (objectUrl) URL.revokeObjectURL(objectUrl)
            if (isGroupPhotoLoadCurrent(loadSerial, group.id)) {
              groupPhotoErrors[key] = error instanceof Error ? error.message : '图片加载失败'
            }
          }
        })(),
      ),
    )
  } finally {
    if (isGroupPhotoLoadCurrent(loadSerial, group.id)) {
      photoDialogLoading.value = false
    }
  }
}

function handlePhotoDialogClosed() {
  photoGroup.value = null
  photoDialogLoading.value = false
  groupPhotoPreviewOpen.value = false
  activeGroupPhotoUrl.value = ''
  activeGroupPhotoTitle.value = ''
  clearGroupPhotoObjectUrls()
}

function firstPhotoField(group: MaterialGroup, field: 'collector' | 'moduleAssetNo') {
  return group.photos?.find((photo) => photo[field])?.[field] || ''
}

function groupEditableValues(group: MaterialGroup): Record<string, string> {
  return {
    meter_no: group.meterNo || '',
    meter_match_key: group.meterMatchKey || '',
    terminal: group.terminal || '',
    address: group.address || '',
    status: group.status || 'pending',
    reviewer: group.reviewer || '',
    review_note: group.reviewNote || '',
    exception_note: group.exceptionNote || '',
    collector: group.collector || firstPhotoField(group, 'collector'),
    module_asset_no: group.moduleAssetNo || firstPhotoField(group, 'moduleAssetNo'),
    construction_collector: group.constructionCollector || '',
    construction_module_asset_no: group.constructionModuleAssetNo || '',
  }
}

function openEdit(group: MaterialGroup) {
  activeGroup.value = group
  const values = groupEditableValues(group)
  editForm.meterNo = values.meter_no
  editForm.meterMatchKey = values.meter_match_key
  editForm.terminal = values.terminal
  editForm.address = values.address
  editForm.status = values.status as TaskStatus
  editForm.reviewer = values.reviewer
  editForm.reviewNote = values.review_note
  editForm.exceptionNote = values.exception_note
  editForm.collector = values.collector
  editForm.moduleAssetNo = values.module_asset_no
  editForm.constructionCollector = values.construction_collector
  editForm.constructionModuleAssetNo = values.construction_module_asset_no
  resetReason.value = ''
  editOpen.value = true
}

function replaceGroup(updated: MaterialGroup) {
  groups.value = groups.value.map((item) => (item.id === updated.id ? updated : item))
  selectedGroups.value = selectedGroups.value.map((item) => (item.id === updated.id ? updated : item))
  activeGroup.value = updated
}

function handleSelectionChange(selection: MaterialGroup[]) {
  selectedGroups.value = selection
}

async function archiveSelectedGroups() {
  if (!selectedGroups.value.length) {
    ElMessage.warning('请先勾选需要归档的资料组')
    return
  }
  const ids = selectedGroups.value.map((item) => item.id)
  try {
    await ElMessageBox.confirm(`确认批量归档已勾选的 ${ids.length} 个资料组？系统会写入审计记录。`, '批量归档', {
      type: 'warning',
      confirmButtonText: '确认归档',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  saving.value = true
  try {
    const result = await bulkArchiveAdminGroups(ids, '管理员后台批量归档')
    const updatedById = new Map(result.groups.map((item) => [item.id, item]))
    groups.value = groups.value.map((item) => updatedById.get(item.id) || item)
    selectedGroups.value = selectedGroups.value
      .map((item) => updatedById.get(item.id) || item)
      .filter((item) => !updatedById.has(item.id))
    const skippedText = result.skipped.length ? `，跳过 ${result.skipped.length} 个` : ''
    ElMessage.success(`已归档 ${result.archivedCount} 个资料组${skippedText}`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '批量归档失败')
  } finally {
    saving.value = false
  }
}

async function saveEdit() {
  if (!activeGroup.value) return
  saving.value = true
  try {
    const before = groupEditableValues(activeGroup.value)
    const next: Record<string, string> = {
      meter_no: editForm.meterNo,
      meter_match_key: editForm.meterMatchKey,
      terminal: editForm.terminal,
      address: editForm.address,
      status: editForm.status,
      reviewer: editForm.reviewer,
      review_note: editForm.reviewNote,
      exception_note: editForm.exceptionNote,
      collector: editForm.collector,
      module_asset_no: editForm.moduleAssetNo,
      construction_collector: editForm.constructionCollector,
      construction_module_asset_no: editForm.constructionModuleAssetNo,
    }
    const updates = Object.fromEntries(
      Object.entries(next).filter(([field, value]) => String(value || '').trim() !== String(before[field] || '').trim()),
    )
    const result = await updateAdminGroupMetadata(activeGroup.value.id, updates)
    replaceGroup(result.group)
    ElMessage.success(result.changedFields.length ? `已保存 ${result.changedFields.length} 项变更` : '没有字段变化')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function resetUnreviewed() {
  if (!activeGroup.value) return
  try {
    await ElMessageBox.confirm('确认将该资料组回退至未审阅？照片会保留，审阅状态和异常状态会清空。', '回退至未审阅', {
      type: 'warning',
      confirmButtonText: '确认回退',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  saving.value = true
  try {
    const result = await resetAdminGroupToUnreviewed(activeGroup.value.id, resetReason.value)
    replaceGroup(result.group)
    ElMessage.success('已回退至未审阅')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '回退失败')
  } finally {
    saving.value = false
  }
}

async function resetUnconstructed() {
  if (!activeGroup.value) return
  try {
    await ElMessageBox.confirm('确认将该资料组回退至未施工？当前照片会被软删除，采集器号、模块号、扫码通过标记、施工与审阅状态都会清空。', '回退至未施工', {
      type: 'error',
      confirmButtonText: '确认回退',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  saving.value = true
  try {
    const result = await resetAdminGroupToUnconstructed(activeGroup.value.id, resetReason.value)
    replaceGroup(result.group)
    ElMessage.success(`已回退至未施工，软删除照片 ${result.softDeletedPhotos} 张`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '回退失败')
  } finally {
    saving.value = false
  }
}

async function copyValue(value: string | number | undefined, label: string) {
  const text = String(value || '').trim()
  if (!text) {
    ElMessage.warning(`${label}为空`)
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(`已复制${label}`)
  } catch {
    const input = document.createElement('textarea')
    input.value = text
    input.setAttribute('readonly', 'readonly')
    input.style.position = 'fixed'
    input.style.left = '-9999px'
    document.body.appendChild(input)
    input.select()
    document.execCommand('copy')
    document.body.removeChild(input)
    ElMessage.success(`已复制${label}`)
  }
}

function applyScannedValue(value: string) {
  const text = value.trim()
  if (!text || scannerLocked) return
  scannerLocked = true
  query.value = text
  closeScanner()
  void runSearch()
}

function stopScanner() {
  if (scannerTimer) window.clearInterval(scannerTimer)
  scannerTimer = 0
  zxingControls?.stop()
  zxingControls = null
  scannerStream?.getTracks().forEach((track) => track.stop())
  scannerStream = null
  if (scannerVideo.value) scannerVideo.value.srcObject = null
}

onUnmounted(() => {
  stopScanner()
  clearGroupPhotoObjectUrls()
})

function closeScanner() {
  stopScanner()
  scannerOpen.value = false
}

async function startScanner() {
  scannerOpen.value = true
  scannerManual.value = ''
  scannerLocked = false
  scannerStatus.value = '正在启动相机，请允许浏览器使用摄像头。'
  await nextTick()
  const Detector = (window as typeof window & { BarcodeDetector?: BarcodeDetectorConstructor }).BarcodeDetector
  if (!window.isSecureContext || typeof navigator.mediaDevices?.getUserMedia !== 'function') {
    scannerStatus.value = '浏览器只允许 HTTPS 页面打开摄像头。请使用 https:// 地址访问，或拍照/选图后识别，也可手动输入。'
    return
  }
  try {
    if (!scannerVideo.value) return
    if (!Detector) {
      zxingControls = await zxingReader.decodeFromConstraints(
        { video: { facingMode: { ideal: 'environment' } }, audio: false },
        scannerVideo.value,
        (result, error) => {
          if (result?.getText()) applyScannedValue(result.getText())
          if (error && error.name !== 'NotFoundException') scannerStatus.value = '识别失败，请保持条码清晰或拍照后识别。'
        },
      )
      scannerStatus.value = '正在识别条码...'
      return
    }
    scannerStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' } },
      audio: false,
    })
    scannerVideo.value.srcObject = scannerStream
    await scannerVideo.value.play()
    const detector = new Detector({ formats: ['code_128', 'code_39', 'ean_13', 'qr_code'] })
    scannerStatus.value = '正在识别条码...'
    scannerTimer = window.setInterval(async () => {
      if (!scannerVideo.value || scannerLocked) return
      try {
        const codes = await detector.detect(scannerVideo.value)
        const value = codes.find((item) => item.rawValue)?.rawValue || ''
        if (value) applyScannedValue(value)
      } catch {
        scannerStatus.value = '识别失败，请保持条码清晰或手动输入。'
      }
    }, 500)
  } catch {
    scannerStatus.value = '相机启动失败，请检查浏览器权限后重试，或拍照/选图后识别。'
  }
}

function applyManualScan() {
  applyScannedValue(scannerManual.value)
}

function openScannerFilePicker() {
  scannerFileInput.value?.click()
}

async function decodeScannerFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const image = new Image()
  const url = URL.createObjectURL(file)
  try {
    image.src = url
    await image.decode()
    const result = await zxingReader.decodeFromImageElement(image)
    applyScannedValue(result.getText())
  } catch {
    scannerStatus.value = '照片未识别到条码，请换一张更清晰的照片或手动输入。'
  } finally {
    URL.revokeObjectURL(url)
    input.value = ''
  }
}
</script>

<template>
  <section class="global-search-page">
    <div class="panel search-panel">
      <div class="search-heading">
        <div>
          <p class="eyebrow">管理员后台</p>
          <h2>数据中台</h2>
        </div>
        <el-tag type="warning" effect="plain">管理员</el-tag>
      </div>

      <div class="search-bar">
        <el-input
          v-model="query"
          clearable
          size="large"
          placeholder="输入表号、模块号、采集器号、地址"
          :prefix-icon="Search"
          @keyup.enter="runSearch"
        />
        <el-select v-model="terminal" clearable filterable size="large" placeholder="终端">
          <el-option v-for="item in terminals" :key="item" :label="item" :value="item" />
        </el-select>
        <el-button size="large" :icon="Camera" @click="startScanner">扫码</el-button>
        <el-button type="primary" size="large" :icon="Search" :loading="loading" @click="runSearch">搜索</el-button>
        <el-button size="large" :icon="Refresh" @click="resetSearch">重置</el-button>
      </div>
    </div>

    <div class="panel result-panel">
      <div class="result-heading">
        <div>
          <h3>资料组字段</h3>
          <span v-if="searched">共 {{ total }} 条，支持横向滚动查看字段</span>
          <span v-else>等待输入条件</span>
        </div>
        <div class="result-actions">
          <el-button type="primary" :disabled="!selectedCount" :loading="saving" @click="archiveSelectedGroups">
            批量归档<span v-if="selectedCount">（{{ selectedCount }}）</span>
          </el-button>
        </div>
      </div>

      <el-alert v-if="errorMessage" type="error" :title="errorMessage" show-icon :closable="false" />

      <el-empty v-if="!loading && searched && !groups.length && !errorMessage" description="没有找到资料组" />
      <el-empty v-else-if="!loading && !searched" description="输入条件后开始定位资料组" />

      <el-table
        v-else
        v-loading="loading"
        :data="groups"
        row-key="id"
        height="calc(100vh - 330px)"
        class="result-table"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="48" fixed="left" />
        <el-table-column prop="id" label="资料组ID" min-width="170" show-overflow-tooltip />
        <el-table-column label="表号" min-width="150">
          <template #default="{ row }">
            <button class="plain-link" @click="copyValue(row.meterNo, '表号')">{{ row.meterNo || '-' }}</button>
          </template>
        </el-table-column>
        <el-table-column prop="meterMatchKey" label="匹配键" min-width="140" show-overflow-tooltip />
        <el-table-column prop="terminal" label="终端" min-width="130" />
        <el-table-column prop="installer" label="安装人员" min-width="120" show-overflow-tooltip />
        <el-table-column label="任务ID" width="90">
          <template #default="{ row }">#{{ row.taskId || '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="扫码状态" width="130">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="barcodeProgressType(row)">
              {{ barcodeProgressLabel(row) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="图片分类" width="120">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="row.photoCategoryComplete ? 'success' : 'warning'">
              {{ photoCategoryLabel(row) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="photoCount" label="照片数" width="82" />
        <el-table-column label="照片" width="116">
          <template #default="{ row }">
            <el-button v-if="row.photos?.length" link type="primary" @click="openGroupPhotos(row)">查看 {{ row.photoCount }} 张</el-button>
            <span v-else class="empty-cell">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="reviewer" label="审阅员" min-width="110" />
        <el-table-column prop="reviewNote" label="审阅备注" min-width="180" show-overflow-tooltip />
        <el-table-column prop="exceptionNote" label="异常备注" min-width="180" show-overflow-tooltip />
        <el-table-column prop="collector" label="扫码采集器号" min-width="140" show-overflow-tooltip />
        <el-table-column prop="moduleAssetNo" label="扫码模块号" min-width="140" show-overflow-tooltip />
        <el-table-column prop="creator" label="创建人" min-width="110" show-overflow-tooltip />
        <el-table-column prop="constructionCollector" label="施工采集器号" min-width="150" show-overflow-tooltip />
        <el-table-column prop="constructionModuleAssetNo" label="施工模块号" min-width="150" show-overflow-tooltip />
        <el-table-column prop="address" label="地址" min-width="300" show-overflow-tooltip />
        <el-table-column label="操作" width="128" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-tooltip content="复制资料组ID" placement="top">
                <el-button :icon="CopyDocument" circle @click="copyValue(row.id, '资料组ID')" />
              </el-tooltip>
              <el-tooltip content="编辑资料组" placement="top">
                <el-button type="primary" :icon="EditPen" circle @click="openEdit(row)" />
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="scannerOpen" title="扫码定位资料组" width="min(420px, 92vw)" class="scanner-dialog" @closed="stopScanner">
      <div class="scanner-box">
        <video ref="scannerVideo" class="scanner-video" playsinline muted />
        <p>{{ scannerStatus }}</p>
        <input ref="scannerFileInput" type="file" accept="image/*" capture="environment" class="scanner-file-input" @change="decodeScannerFile" />
        <el-input v-model="scannerManual" placeholder="无法扫码时可手动输入" @keyup.enter="applyManualScan" />
      </div>
      <template #footer>
        <el-button @click="closeScanner">取消</el-button>
        <el-button @click="openScannerFilePicker">拍照识别</el-button>
        <el-button type="primary" @click="applyManualScan">使用输入内容</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="photoDialogOpen"
      :title="`资料组照片 - ${photoGroup?.meterNo || photoGroup?.id || ''}`"
      width="960px"
      class="group-photo-dialog"
      append-to-body
      @closed="handlePhotoDialogClosed"
    >
      <div v-loading="photoDialogLoading" class="group-photo-grid">
        <article v-for="photo in photoGroup?.photos || []" :key="photo.id" class="group-photo-card">
          <button
            v-if="groupPhotoUrl(photoGroup?.id || '', photo.id)"
            type="button"
            class="group-photo-image group-photo-image-button"
            :aria-label="`查看${photo.categoryLabel || photo.category || '资料组'}照片`"
            @click="openGroupPhotoPreview(photoGroup, photo)"
          >
            <img
              :src="groupPhotoUrl(photoGroup?.id || '', photo.id)"
              :alt="photo.categoryLabel || photo.category || '资料组照片'"
              @error="handleGroupPhotoRenderedError(photoGroup, photo)"
            />
          </button>
          <div v-else class="group-photo-image photo-thumb-error">
            {{ groupPhotoErrors[groupPhotoKey(photoGroup?.id || '', photo.id)] || '图片加载中' }}
          </div>
          <div class="group-photo-meta">
            <strong>{{ photo.categoryLabel || photo.category || '未分类' }}</strong>
            <span>{{ photo.archiveFilename || photo.name || photo.id }}</span>
          </div>
        </article>
      </div>
    </el-dialog>

    <el-dialog
      v-model="groupPhotoPreviewOpen"
      :title="activeGroupPhotoTitle"
      width="min(960px, 96vw)"
      class="group-photo-preview-dialog"
      append-to-body
    >
      <div class="group-photo-preview-stage">
        <img v-if="activeGroupPhotoUrl" :src="activeGroupPhotoUrl" :alt="activeGroupPhotoTitle || '资料组照片'" />
      </div>
    </el-dialog>

    <el-drawer v-model="editOpen" title="编辑资料组" size="min(560px, 100vw)" class="edit-drawer">
      <div v-if="activeGroup" class="edit-body">
        <div class="readonly-grid">
          <span>资料组ID</span><strong>{{ activeGroup.id }}</strong>
          <span>任务ID</span><strong>{{ activeGroup.taskId || '-' }}</strong>
          <span>照片数</span><strong>{{ activeGroup.photoCount }}</strong>
        </div>
        <el-form label-position="top" class="edit-form">
          <el-form-item label="表号">
            <el-input v-model="editForm.meterNo" />
          </el-form-item>
          <el-form-item label="匹配键">
            <el-input v-model="editForm.meterMatchKey" />
          </el-form-item>
          <el-form-item label="终端">
            <el-input v-model="editForm.terminal" />
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="editForm.status">
              <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="地址" class="wide-field">
            <el-input v-model="editForm.address" type="textarea" :rows="2" />
          </el-form-item>
          <el-form-item label="审阅员">
            <el-input v-model="editForm.reviewer" />
          </el-form-item>
          <el-form-item label="审阅备注">
            <el-input v-model="editForm.reviewNote" />
          </el-form-item>
          <el-form-item label="异常备注" class="wide-field">
            <el-input v-model="editForm.exceptionNote" type="textarea" :rows="2" />
          </el-form-item>
          <el-form-item label="扫码采集器号">
            <el-input v-model="editForm.collector" />
          </el-form-item>
          <el-form-item label="扫码模块号">
            <el-input v-model="editForm.moduleAssetNo" />
          </el-form-item>
          <el-form-item label="施工采集器号">
            <el-input v-model="editForm.constructionCollector" />
          </el-form-item>
          <el-form-item label="施工模块号">
            <el-input v-model="editForm.constructionModuleAssetNo" />
          </el-form-item>
        </el-form>

        <div class="danger-zone">
          <div>
            <el-icon><Warning /></el-icon>
            <strong>回退操作</strong>
          </div>
          <el-input v-model="resetReason" placeholder="填写回退原因，写入审计记录" />
          <div class="reset-actions">
            <el-button :loading="saving" @click="resetUnreviewed">回退至未审阅</el-button>
            <el-button type="danger" plain :loading="saving" @click="resetUnconstructed">回退至未施工</el-button>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="editOpen = false">关闭</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存并审计</el-button>
      </template>
    </el-drawer>
  </section>
</template>

<style scoped>
.global-search-page {
  display: grid;
  gap: 12px;
}

.search-panel,
.result-panel {
  padding: 18px;
}

.search-heading,
.result-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.search-heading h2,
.result-heading h3 {
  margin: 4px 0 0;
  color: var(--v2-text-strong);
  letter-spacing: 0;
}

.result-heading span {
  display: inline-block;
  margin-top: 4px;
  color: var(--v2-text-muted);
  font-size: 12px;
}

.search-bar {
  display: grid;
  grid-template-columns: minmax(240px, 1fr) minmax(160px, 220px) auto auto auto;
  gap: 10px;
  margin-top: 14px;
  align-items: center;
}

.result-panel {
  display: grid;
  gap: 12px;
}

.result-table {
  width: 100%;
}

.plain-link {
  appearance: none;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--v2-accent);
  font: inherit;
  cursor: pointer;
}

.plain-link:hover {
  text-decoration: underline;
}

.row-actions {
  display: flex;
  gap: 8px;
}

.result-actions {
  display: flex;
  justify-content: flex-end;
  min-width: max-content;
}

.photo-thumb-error {
  display: grid;
  width: 100%;
  height: 100%;
  place-items: center;
  padding: 4px;
  color: var(--v2-text-muted);
  font-size: 10px;
  line-height: 1.1;
  text-align: center;
}

.group-photo-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  min-height: 220px;
}

.group-photo-card {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.group-photo-image {
  width: 100%;
  height: 260px;
  border: 1px solid var(--v2-border);
  border-radius: 8px;
  background: var(--v2-surface-soft);
}

.group-photo-image-button {
  overflow: hidden;
  padding: 0;
  cursor: zoom-in;
}

.group-photo-image-button img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.group-photo-meta {
  display: grid;
  gap: 3px;
  min-width: 0;
  font-size: 12px;
}

.group-photo-meta strong,
.group-photo-meta span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.group-photo-meta span {
  color: var(--v2-text-muted);
}

.group-photo-preview-stage {
  display: grid;
  min-height: 60vh;
  place-items: center;
  background: #0f172a;
}

.group-photo-preview-stage img {
  display: block;
  max-width: 100%;
  max-height: 78vh;
  object-fit: contain;
}

.empty-cell {
  color: var(--v2-text-muted);
}

.scanner-box {
  display: grid;
  gap: 12px;
}

.scanner-video {
  width: 100%;
  aspect-ratio: 4 / 3;
  border-radius: 8px;
  background: #111827;
  object-fit: cover;
}

.scanner-file-input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}

.scanner-box p {
  margin: 0;
  color: var(--v2-text-muted);
  font-size: 13px;
}

.edit-body {
  display: grid;
  gap: 14px;
}

.readonly-grid {
  display: grid;
  grid-template-columns: 80px minmax(0, 1fr);
  gap: 8px 12px;
  padding: 12px;
  border: 1px solid var(--v2-border);
  border-radius: 8px;
  background: var(--v2-surface-soft);
  font-size: 13px;
}

.readonly-grid span {
  color: var(--v2-text-muted);
}

.readonly-grid strong {
  min-width: 0;
  overflow-wrap: anywhere;
}

.edit-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 0 12px;
}

.wide-field {
  grid-column: 1 / -1;
}

.danger-zone {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid #f3c6c6;
  border-radius: 8px;
  background: #fff7f7;
}

.danger-zone > div:first-child,
.reset-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

@media (max-width: 860px) {
  .search-heading,
  .result-heading {
    align-items: flex-start;
  }

  .search-bar,
  .edit-form {
    grid-template-columns: 1fr;
  }

  .reset-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .result-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .group-photo-grid {
    grid-template-columns: 1fr;
  }

  .group-photo-image {
    height: 220px;
  }
}
</style>
