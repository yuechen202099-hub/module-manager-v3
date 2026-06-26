<script setup lang="ts">
import { MoreFilled, Refresh, Upload } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'

import {
  assignConstructionExceptionOrder,
  boardEventHeaders,
  boardEventsUrl,
  deleteUnmatchedRecord,
  dedupeUnmatchedRecords,
  exportExceptionMeters,
  fetchConstructionExceptionOrders,
  fetchExceptionGroups,
  fetchInstallerWorkload,
  fetchProjectSummary,
  fetchReplacementRecords,
  fetchSystemStatus,
  fetchTaskStatus,
  fetchUnmatchedRecords,
  fetchUserAccounts,
  importTotalCatalog,
  rematchUnmatchedRecord,
  returnGroupToException,
  unassignConstructionExceptionOrder,
} from '@/api/services'
import type {
  ConstructionExceptionOrder,
  ImportJob,
  InstallerExceptionGroup,
  InstallerWorkload,
  InstallerWorkSegment,
  InstallerWorkloadRow,
  MaterialGroup,
  ProjectSummary,
  ReplacementRecord,
  TaskStatusSummary,
  UnmatchedRecord,
  UserAccount,
} from '@/api/types'
import { useAuthStore } from '@/stores/auth'

const emptySummary: ProjectSummary = {
  totalCatalogRows: 0,
  groups: 0,
  scannedGroups: 0,
  approvedGroups: 0,
  reviewedGroups: 0,
  unreviewedGroups: 0,
  exceptionGroups: 0,
  incompleteGroups: 0,
  unconstructedGroups: 0,
  photoRowsLinked: 0,
  scanUnmatched: 0,
  reviewProgress: 0,
  photoAccuracyChecked: 0,
  photoAccuracyPassed: 0,
  photoAccuracyFailed: 0,
  photoAccuracyUnreadable: 0,
  photoAccuracyNotRequired: 0,
  photoAccuracyRate: 0,
  installerDistribution: [],
}

const emptyTaskStatus: TaskStatusSummary = {
  version: '',
  generatedAt: '',
  total: 0,
  scanned: 0,
  uploaded: 0,
  reviewing: 0,
  archived: 0,
  claimed: 0,
  constructionAssigned: 0,
  avgUploadRate: 0,
  avgReviewRate: 0,
  renovationCount: 0,
  uploadedCount: 0,
  reviewedCount: 0,
  unreviewedCount: 0,
  totalCatalogRows: 0,
  groups: 0,
}

const auth = useAuthStore()
const loading = ref(false)
const importingTotal = ref(false)
const importingScan = ref(false)
const summary = ref<ProjectSummary>({ ...emptySummary })
const taskStatus = ref<TaskStatusSummary>({ ...emptyTaskStatus })
const systemStatus = ref<Record<string, unknown> | null>(null)
const activeJob = ref<ImportJob | null>(null)
const errorMessage = ref('')
const accountUsers = ref<UserAccount[]>([])
const loadingAccounts = ref(false)
const exportingException = ref(false)
const workloadDialogVisible = ref(false)
const workloadLoading = ref(false)
const workloadInstaller = ref('')
const workloadRows = ref<InstallerWorkloadRow[]>([])
const workloadExceptionDialogVisible = ref(false)
const workloadExceptionDate = ref('')
const workloadExceptionGroups = ref<InstallerExceptionGroup[]>([])
const workloadTimeDialogVisible = ref(false)
const workloadTimeRow = ref<InstallerWorkloadRow | null>(null)
const workloadSegmentDialogVisible = ref(false)
const workloadSegment = ref<InstallerWorkSegment | null>(null)
const installerWorkloadScope = ref<'all' | 'day' | 'week' | 'month'>('all')
const installerScopeDate = ref('')
const installerWorkloadLoading = ref(false)
const installerWorkloadCache = reactive<Record<string, InstallerWorkloadRow[]>>({})
const unmatchedDialogVisible = ref(false)
const unmatchedLoading = ref(false)
const unmatchedDeduping = ref(false)
const unmatchedDeletingId = ref('')
const unmatchedRematchingId = ref('')
const unmatchedQuery = ref('')
const unmatchedRows = ref<UnmatchedRecord[]>([])
const replacementDialogVisible = ref(false)
const replacementLoading = ref(false)
const replacementQuery = ref('')
const replacementRows = ref<ReplacementRecord[]>([])
const exceptionDialogVisible = ref(false)
const exceptionLoading = ref(false)
const exceptionAssigningGroupId = ref('')
const exceptionQuery = ref('')
const exceptionRows = ref<MaterialGroup[]>([])
const exceptionOrders = ref<ConstructionExceptionOrder[]>([])
const exceptionAssignDraft = reactive<Record<string, string>>({})

const BOARD_REFRESH_INTERVAL_MS = 15 * 60 * 1000
let boardEventAbortController: AbortController | null = null
let boardFallbackTimer = 0

const isAdmin = computed(() => Boolean(auth.user?.roles?.includes('admin') || auth.user?.role === 'admin'))
const scannedRate = computed(() => (summary.value.groups ? summary.value.scannedGroups / summary.value.groups : 0))
const archiveRate = computed(() => (summary.value.groups ? summary.value.approvedGroups / summary.value.groups : 0))
const photoAccuracyRate = computed(() => summary.value.photoAccuracyRate || 0)
const photoAccuracyCaption = computed(() => {
  const checked = summary.value.photoAccuracyChecked
  if (!checked) return `暂无应检图片，${summary.value.photoAccuracyNotRequired} 张不参与`
  return `通过 ${summary.value.photoAccuracyPassed} / 应检 ${checked}，失败 ${summary.value.photoAccuracyFailed}，无法识别 ${summary.value.photoAccuracyUnreadable}`
})
const terminalCockpit = computed(() => {
  const total = taskStatus.value.total
  const scanned = taskStatus.value.scanned
  const uploaded = taskStatus.value.uploaded
  const reviewing = taskStatus.value.reviewing
  const archived = taskStatus.value.archived
  const claimed = taskStatus.value.claimed
  const constructionAssigned = taskStatus.value.constructionAssigned
  const avgUploadRate = taskStatus.value.avgUploadRate
  const avgReviewRate = taskStatus.value.avgReviewRate
  return {
    total,
    scanned,
    uploaded,
    reviewing,
    archived,
    claimed,
    constructionAssigned,
    avgUploadRate,
    avgReviewRate,
  }
})
const cockpitFlow = computed(() => [
  { label: '终端总数', value: terminalCockpit.value.total, hint: '导入形成的终端范围' },
  { label: '已扫码', value: terminalCockpit.value.scanned, hint: '扫码表已关联终端' },
  { label: '有上传', value: terminalCockpit.value.uploaded, hint: '已有现场照片回流' },
  { label: '待审阅', value: terminalCockpit.value.reviewing, hint: '仍有未审照片' },
  { label: '已闭环', value: terminalCockpit.value.archived, hint: '终端审阅完成' },
])
const exceptionRiskTotal = computed(() => summary.value.exceptionGroups)
const cockpitSignals = computed(() => [
  { label: '审阅领取', value: terminalCockpit.value.claimed, caption: '已被审阅员持有的终端', tone: 'info' },
  { label: '施工指派', value: terminalCockpit.value.constructionAssigned, caption: '已指派施工员的终端', tone: 'success' },
])
const reviewRingStyle = computed(() => ringStyle(archiveRate.value, '#0a72d8', '#e8eef5'))
const uploadRingStyle = computed(() => ringStyle(terminalCockpit.value.avgUploadRate, '#0f7892', '#e8eef5'))
const reviewGap = computed(() => Math.max(0, summary.value.groups - summary.value.approvedGroups))
const jobPercent = computed(() => {
  if (!activeJob.value) return 0
  if (activeJob.value.status === 'complete') return 100
  const progress = activeJob.value.progress || {}
  const percentValue = Number(progress.percent || progress.percentage || 0)
  return percentValue > 0 ? Math.min(99, Math.round(percentValue)) : 45
})
const systemRows = computed<Array<[string, string]>>(() => {
  if (!systemStatus.value) return []
  const status = systemStatus.value as Record<string, unknown>
  const disk = (status.disk || {}) as Record<string, unknown>
  const stateFile = (status.state_file || status.data || {}) as Record<string, unknown>
  const service = (status.service || {}) as Record<string, unknown>
  const backups = (status.backups || {}) as Record<string, unknown>
  return [
    ['版本号', String(status.version || 'unknown')],
    ['服务', String(service.status || status.status || (status.ok ? 'ok' : 'unknown'))],
    ['磁盘使用', `${String(disk.used_percent || disk.percent || 'unknown')}%`],
    ['数据文件', formatBytes(Number(stateFile.local_state_size || stateFile.state_size || stateFile.size_bytes || 0))],
    ['最近备份', String(status.latest_backup_at || backups.latest_modified_at || status.latest_backup || 'unknown')],
  ]
})
const workloadTotals = computed(() =>
  workloadRows.value.reduce(
    (total, item) => ({
      groupCount: total.groupCount + item.groupCount,
      photoCount: total.photoCount + item.photoCount,
      archivedCount: total.archivedCount + item.archivedCount,
      exceptionCount: total.exceptionCount + item.exceptionCount,
      unreviewedCount: total.unreviewedCount + item.unreviewedCount,
      workDurationMinutes: total.workDurationMinutes + item.workDurationMinutes,
      workDurationMinutesV2: total.workDurationMinutesV2 + item.workDurationMinutesV2,
      fusedWorkDurationMinutes: total.fusedWorkDurationMinutes + item.fusedWorkDurationMinutes,
      completionCount: total.completionCount + item.completionCount,
      weightedCompletion: total.weightedCompletion + item.weightedCompletion,
    }),
    {
      groupCount: 0,
      photoCount: 0,
      archivedCount: 0,
      exceptionCount: 0,
      unreviewedCount: 0,
      workDurationMinutes: 0,
      workDurationMinutesV2: 0,
      fusedWorkDurationMinutes: 0,
      completionCount: 0,
      weightedCompletion: 0,
    },
  ),
)
const workloadExceptionTitle = computed(() => `${workloadInstaller.value} ${workloadExceptionDate.value} 异常明细`)
const workloadTimeTitle = computed(() => `${workloadInstaller.value} ${workloadTimeRow.value?.date || ''} 工时时段分布`)
const workloadSegmentTitle = computed(() => `${workloadInstaller.value} ${workloadTimeRow.value?.date || ''} ${workloadSegment.value?.label || ''} 地址清单`)
const workloadTimeSegments = computed(() => workloadTimeRow.value?.twoHourSegments || [])
const workloadMaxSegmentMinutes = computed(() =>
  Math.max(1, ...workloadTimeSegments.value.map((item) => Number(item.minutes || 0))),
)
const installerScopeOptions = [
  { value: 'all', label: '全部' },
  { value: 'day', label: '日' },
  { value: 'week', label: '周' },
  { value: 'month', label: '月' },
]
const installerScopeSelectLabel = computed(() => {
  if (installerWorkloadScope.value === 'day') return '日期'
  if (installerWorkloadScope.value === 'week') return '自然周'
  if (installerWorkloadScope.value === 'month') return '月份'
  return ''
})
const installerScopePlaceholder = computed(() => {
  if (installerWorkloadScope.value === 'day') return '选择日期'
  if (installerWorkloadScope.value === 'week') return '选择自然周'
  if (installerWorkloadScope.value === 'month') return '选择月份'
  return ''
})
const installerScopeChoices = computed(() => {
  if (installerWorkloadScope.value === 'all') return []
  const dates = new Set<string>()
  for (const rows of Object.values(installerWorkloadCache)) {
    for (const row of rows) {
      if (row.date) dates.add(row.date)
    }
  }
  const sortedDates = [...dates].sort((left, right) => right.localeCompare(left))
  if (installerWorkloadScope.value === 'day') {
    return sortedDates.map((date) => ({ value: date, label: date }))
  }
  if (installerWorkloadScope.value === 'week') {
    const weekStarts = new Set(sortedDates.map((date) => naturalWeekStart(date)))
    return [...weekStarts]
      .sort((left, right) => right.localeCompare(left))
      .map((date) => ({ value: date, label: `${date} 至 ${shiftDate(date, 6)}` }))
  }
  const monthLatestDate = new Map<string, string>()
  for (const date of sortedDates) {
    const month = date.slice(0, 7)
    if (!monthLatestDate.has(month)) monthLatestDate.set(month, date)
  }
  return [...monthLatestDate.entries()]
    .sort(([left], [right]) => right.localeCompare(left))
    .map(([month, date]) => ({ value: date, label: month }))
})
const filteredInstallerDistribution = computed(() => {
  if (installerWorkloadScope.value === 'all') {
    return [...summary.value.installerDistribution].sort((left, right) => right.groupCount - left.groupCount)
  }
  const anchorDate = installerScopeAnchorDate()
  if (!anchorDate) return []
  const rows = summary.value.installerDistribution
    .map((item) => {
      const completionCount = (installerWorkloadCache[item.installer] || [])
        .filter((row) => installerWorkloadRowInScope(row, anchorDate))
        .reduce((sum, row) => sum + Number(row.completionCount || 0), 0)
      return { installer: item.installer, groupCount: completionCount, share: 0 }
    })
    .filter((item) => item.groupCount > 0)
    .sort((left, right) => right.groupCount - left.groupCount || left.installer.localeCompare(right.installer, 'zh-Hans-CN'))
  const total = rows.reduce((sum, item) => sum + item.groupCount, 0)
  return rows.map((item) => ({ ...item, share: total ? item.groupCount / total : 0 }))
})
const installerScopeHint = computed(() => {
  if (installerWorkloadScope.value === 'all') return '全部资料组'
  const anchorDate = installerScopeAnchorDate()
  if (!anchorDate) return '等待工作量数据'
  if (installerWorkloadScope.value === 'day') return anchorDate
  if (installerWorkloadScope.value === 'week') return `${anchorDate} 至 ${shiftDate(anchorDate, 6)}`
  return anchorDate.slice(0, 7)
})
const unmatchedDialogStats = computed(() => {
  const outside = unmatchedRows.value.filter((item) => item.projectOutside).length
  const assigned = unmatchedRows.value.filter((item) => item.assignedTo).length
  return {
    total: unmatchedRows.value.length,
    outside,
    assigned,
    pending: unmatchedRows.value.filter((item) => !item.projectOutside && !item.assignedTo).length,
  }
})
const replacementDialogStats = computed(() => ({
  total: replacementRows.value.length,
  terminals: new Set(replacementRows.value.map((item) => item.terminal).filter(Boolean)).size,
  operators: new Set(replacementRows.value.map((item) => item.replacementBy).filter(Boolean)).size,
  photos: replacementRows.value.reduce((sum, item) => sum + Number(item.photoCount || 0), 0),
}))
const constructorOptions = computed(() =>
  accountUsers.value
    .filter((user) => user.status !== 'disabled' && user.roles?.includes('constructor'))
    .map((user) => ({
      value: user.username,
      label: user.name && user.name !== user.username ? `${user.name} / ${user.username}` : user.username,
    })),
)
const exceptionOrdersByGroupId = computed(() => {
  const map = new Map<string, ConstructionExceptionOrder>()
  for (const order of exceptionOrders.value) {
    if (order.groupId) map.set(String(order.groupId), order)
  }
  return map
})
const filteredExceptionRows = computed(() => {
  const keyword = exceptionQuery.value.trim().toLowerCase()
  if (!keyword) return exceptionRows.value
  return exceptionRows.value.filter((row) => {
    const order = exceptionOrdersByGroupId.value.get(String(row.id))
    const content = [
      row.meterNo,
      row.meterMatchKey,
      row.terminal,
      row.address,
      row.constructionCollector,
      row.constructionModuleAssetNo,
      row.reviewer,
      row.exceptionNote,
      ...(row.exceptionReasons || []),
      order?.assignedTo,
      order?.note,
      order?.category,
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    return content.includes(keyword)
  })
})
const exceptionDialogStats = computed(() => {
  const assigned = exceptionRows.value.filter((row) => {
    const order = exceptionOrdersByGroupId.value.get(String(row.id))
    return Boolean(order?.assignedTo)
  }).length
  return {
    total: exceptionRows.value.length,
    assigned,
    pending: Math.max(0, exceptionRows.value.length - assigned),
  }
})

function percent(value: number) {
  if (!Number.isFinite(value)) return '0%'
  return `${Math.round(value * 100)}%`
}

function flowPercent(value: number) {
  const total = Math.max(terminalCockpit.value.total, 1)
  return Math.max(0, Math.min(100, Math.round((Number(value || 0) / total) * 100)))
}

function ringStyle(value: number, active: string, track: string) {
  const degrees = Math.max(0, Math.min(360, Math.round(Number(value || 0) * 360)))
  return {
    background: `conic-gradient(${active} ${degrees}deg, ${track} 0deg)`,
  }
}

function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let amount = value
  let index = 0
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024
    index += 1
  }
  return `${amount >= 10 || index === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[index]}`
}

function formatWorkDuration(minutes: number) {
  const safeMinutes = Math.max(0, Math.round(Number(minutes || 0)))
  const hours = Math.floor(safeMinutes / 60)
  const rest = safeMinutes % 60
  if (hours && rest) return `${hours}小时${rest}分钟`
  if (hours) return `${hours}小时`
  return `${rest}分钟`
}

function formatDecimal(value: number, digits = 2) {
  if (!Number.isFinite(Number(value))) return '0'
  return Number(value).toFixed(digits).replace(/\.?0+$/, '')
}

function formatDateTime(value = '') {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('zh-CN', { hour12: false })
}

async function loadAccounts() {
  if (!isAdmin.value || loadingAccounts.value) return
  loadingAccounts.value = true
  try {
    accountUsers.value = await fetchUserAccounts()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '账号列表加载失败')
  } finally {
    loadingAccounts.value = false
  }
}

async function loadSystemHealth() {
  if (!isAdmin.value) {
    systemStatus.value = null
    return
  }
  try {
    systemStatus.value = await fetchSystemStatus()
  } catch {
    systemStatus.value = null
  }
}

async function loadBoard() {
  loading.value = true
  errorMessage.value = ''
  try {
    const [summaryResult, statusResult] = await Promise.all([
      fetchProjectSummary(),
      fetchTaskStatus(),
    ])
    summary.value = summaryResult.summary
    taskStatus.value = statusResult
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '项目看板加载失败'
  } finally {
    loading.value = false
  }
}

async function refreshBoard() {
  await loadBoard()
  void loadSystemHealth()
}

async function exportExceptionRows() {
  exportingException.value = true
  try {
    await exportExceptionMeters(isAdmin.value ? '' : undefined)
    ElMessage.success('异常表计已导出')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '异常表计导出失败')
  } finally {
    exportingException.value = false
  }
}

async function uploadTotal(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  importingTotal.value = true
  try {
    await importTotalCatalog(file)
    ElMessage.success('总清单导入完成')
    await loadBoard()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '总清单导入失败')
  } finally {
    importingTotal.value = false
  }
}

async function uploadScan(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  importingScan.value = true
  try {
    activeJob.value = {
      jobId: 'shell-scan-import',
      status: 'queued',
      progress: { phase: '已提交到全局导入任务栏' },
      result: {},
      error: '',
    }
    window.postMessage(
      {
        type: 'module-manager:start-scan-import',
        file,
        filename: file.name,
      },
      window.location.origin,
    )
    ElMessage.success('扫码表格导入已提交，可切换页面继续等待')
    window.setTimeout(() => {
      importingScan.value = false
      activeJob.value = null
    }, 1200)
  } catch (error) {
    importingScan.value = false
    ElMessage.error(error instanceof Error ? error.message : '扫码表格导入失败')
  }
}

function downloadText(filename: string, content: string, type = 'text/csv;charset=utf-8') {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function csvCell(value: unknown) {
  return `"${String(value ?? '').replace(/"/g, '""')}"`
}

function dateTime(date: string) {
  const time = new Date(`${date}T00:00:00`).getTime()
  return Number.isFinite(time) ? time : 0
}

function formatLocalDate(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function shiftDate(date: string, days: number) {
  const shifted = new Date(`${date}T00:00:00`)
  shifted.setDate(shifted.getDate() + days)
  return formatLocalDate(shifted)
}

function naturalWeekStart(date: string) {
  const day = new Date(`${date}T00:00:00`)
  const weekday = day.getDay() || 7
  day.setDate(day.getDate() - weekday + 1)
  return formatLocalDate(day)
}

function latestInstallerWorkloadDate() {
  let latest = ''
  for (const rows of Object.values(installerWorkloadCache)) {
    for (const row of rows) {
      if (row.date && (!latest || row.date > latest)) latest = row.date
    }
  }
  return latest
}

function installerScopeAnchorDate() {
  return installerScopeDate.value || installerScopeChoices.value[0]?.value || latestInstallerWorkloadDate()
}

function syncInstallerScopeDate() {
  if (installerWorkloadScope.value === 'all') {
    installerScopeDate.value = ''
    return
  }
  const choices = installerScopeChoices.value
  if (choices.length) {
    const currentExists = choices.some((item) => item.value === installerScopeDate.value)
    if (!currentExists) installerScopeDate.value = choices[0].value
    return
  }
  if (!installerScopeDate.value) {
    installerScopeDate.value = latestInstallerWorkloadDate()
  }
}

function installerWorkloadRowInScope(row: InstallerWorkloadRow, anchorDate: string) {
  if (!row.date) return false
  if (installerWorkloadScope.value === 'day') return row.date === anchorDate
  if (installerWorkloadScope.value === 'week') {
    const rowTime = dateTime(row.date)
    return rowTime >= dateTime(anchorDate) && rowTime <= dateTime(shiftDate(anchorDate, 6))
  }
  if (installerWorkloadScope.value === 'month') return row.date.slice(0, 7) === anchorDate.slice(0, 7)
  return true
}

function cacheInstallerWorkload(workload: InstallerWorkload) {
  installerWorkloadCache[workload.installer] = workload.items
}

async function loadInstallerScopeWorkload() {
  if (installerWorkloadScope.value === 'all') {
    syncInstallerScopeDate()
    return
  }
  if (installerWorkloadLoading.value) return
  const installers = summary.value.installerDistribution.map((item) => item.installer).filter(Boolean)
  const missing = installers.filter((installer) => !installerWorkloadCache[installer])
  if (!missing.length) {
    syncInstallerScopeDate()
    return
  }
  installerWorkloadLoading.value = true
  try {
    const workloads = await Promise.all(missing.map((installer) => fetchInstallerWorkload(installer)))
    workloads.forEach(cacheInstallerWorkload)
    syncInstallerScopeDate()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '安装人员工作量筛选加载失败')
  } finally {
    installerWorkloadLoading.value = false
  }
}

async function handleInstallerScopeChange() {
  if (installerWorkloadScope.value !== 'all') {
    installerScopeDate.value = ''
  }
  await loadInstallerScopeWorkload()
  syncInstallerScopeDate()
}

async function openInstallerWorkload(installer: string) {
  workloadInstaller.value = installer
  workloadRows.value = []
  workloadExceptionGroups.value = []
  workloadExceptionDate.value = ''
  workloadExceptionDialogVisible.value = false
  workloadDialogVisible.value = true
  workloadLoading.value = true
  try {
    if (!installerWorkloadCache[installer]) {
      cacheInstallerWorkload(await fetchInstallerWorkload(installer))
    }
    workloadRows.value = installerWorkloadCache[installer]
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '安装人员工作量加载失败')
  } finally {
    workloadLoading.value = false
  }
}

function openWorkloadExceptionGroups(row: InstallerWorkloadRow) {
  if (!row.exceptionCount) return
  workloadExceptionDate.value = row.date
  workloadExceptionGroups.value = row.exceptionGroups || []
  workloadExceptionDialogVisible.value = true
}

function openWorkloadTimeChart(row: InstallerWorkloadRow) {
  if (!row.timepointCount) return
  workloadTimeRow.value = row
  workloadTimeDialogVisible.value = true
}

function openWorkloadSegmentDetail(segment: InstallerWorkSegment) {
  workloadSegment.value = segment
  workloadSegmentDialogVisible.value = true
}

function workloadBarHeight(minutes: number) {
  const value = Number(minutes || 0)
  if (!value) return 0
  return Math.max(8, Math.round((value / workloadMaxSegmentMinutes.value) * 100))
}

function startBoardFallbackRefresh() {
  if (boardFallbackTimer) return
  boardFallbackTimer = window.setInterval(() => {
    void loadBoard()
  }, BOARD_REFRESH_INTERVAL_MS)
}

function stopBoardFallbackRefresh() {
  if (!boardFallbackTimer) return
  window.clearInterval(boardFallbackTimer)
  boardFallbackTimer = 0
}

function handleBoardEventChunk(chunk: string) {
  for (const eventBlock of chunk.split('\n\n')) {
    if (eventBlock.includes('event: board-refresh')) void loadBoard()
  }
}

async function connectBoardEvents() {
  if (typeof ReadableStream === 'undefined' || typeof TextDecoder === 'undefined') {
    startBoardFallbackRefresh()
    return
  }
  boardEventAbortController?.abort()
  const controller = new AbortController()
  boardEventAbortController = controller
  try {
    const response = await fetch(boardEventsUrl('project-board'), {
      headers: boardEventHeaders(),
      signal: controller.signal,
    })
    if (!response.ok || !response.body) throw new Error(`Board event stream failed: ${response.status}`)
    stopBoardFallbackRefresh()
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (!controller.signal.aborted) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lastBoundary = buffer.lastIndexOf('\n\n')
      if (lastBoundary < 0) continue
      handleBoardEventChunk(buffer.slice(0, lastBoundary + 2))
      buffer = buffer.slice(lastBoundary + 2)
    }
  } catch {
    if (!controller.signal.aborted) startBoardFallbackRefresh()
  } finally {
    if (boardEventAbortController === controller) boardEventAbortController = null
  }
}

function disconnectBoardEvents() {
  boardEventAbortController?.abort()
  boardEventAbortController = null
  stopBoardFallbackRefresh()
}

function exportInstallerWorkloadCsv() {
  const rows = [
    [
      '安装人员',
      '日期',
      '开工时间',
      '收工时间',
      '有效工时',
      '补偿分钟',
      '考勤跨度',
      '有效时间点',
      '完成量',
      '每小时完成量',
      '难度加权完成量',
      '难度加权效率',
      '资料组数',
      '照片数',
      '已归档',
      '异常',
      '未审阅',
    ],
    ...workloadRows.value.map((item) => [
      workloadInstaller.value,
      item.date,
      item.startTime || '-',
      item.endTime || '-',
      item.workDurationLabel || formatWorkDuration(item.workDurationMinutes),
      item.denseBonusMinutesV2,
      item.workSpanLabel || formatWorkDuration(item.workSpanMinutes),
      item.timepointCount,
      item.completionCount,
      item.completionPerEffectiveHour,
      item.weightedCompletion,
      item.weightedCompletionPerEffectiveHour,
      item.groupCount,
      item.photoCount,
      item.archivedCount,
      item.exceptionCount,
      item.unreviewedCount,
    ]),
  ]
  const csv = `\uFEFF${rows.map((row) => row.map(csvCell).join(',')).join('\r\n')}`
  downloadText(`${workloadInstaller.value || 'installer'}-daily-workload.csv`, csv)
}

function exceptionReasonText(row: MaterialGroup) {
  return row.exceptionReasons?.length ? row.exceptionReasons.join('；') : row.exceptionNote || '异常与缺照'
}

function exceptionOrderFor(row: MaterialGroup) {
  return exceptionOrdersByGroupId.value.get(String(row.id))
}

async function loadExceptionRows() {
  exceptionLoading.value = true
  try {
    const [groups, orders] = await Promise.all([fetchExceptionGroups(''), fetchConstructionExceptionOrders('', '')])
    exceptionRows.value = groups
    exceptionOrders.value = orders
    for (const group of groups) {
      const order = orders.find((item) => String(item.groupId) === String(group.id))
      if (order?.assignedTo) exceptionAssignDraft[group.id] = order.assignedTo
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '异常与缺照加载失败')
  } finally {
    exceptionLoading.value = false
  }
}

async function openExceptionDialog() {
  exceptionDialogVisible.value = true
  if (isAdmin.value && !accountUsers.value.length) await loadAccounts()
  await loadExceptionRows()
}

function exportExceptionGroupCsv() {
  const rows = [
    ['资料组ID', '表号', '终端', '地址', '采集器', '模块', '审阅员', '照片数', '异常原因', '派发施工员', '工单状态'],
    ...filteredExceptionRows.value.map((item) => {
      const order = exceptionOrderFor(item)
      return [
        item.id,
        item.meterNo,
        item.terminal,
        item.address,
        item.constructionCollector,
        item.constructionModuleAssetNo,
        item.reviewer,
        item.photoCount,
        exceptionReasonText(item),
        order?.assignedTo || '',
        order?.status || '',
      ]
    }),
  ]
  const csv = `\uFEFF${rows.map((row) => row.map(csvCell).join(',')).join('\r\n')}`
  downloadText(`异常与缺照-${new Date().toISOString().slice(0, 10)}.csv`, csv)
}

async function assignExceptionGroup(row: MaterialGroup) {
  if (!isAdmin.value) return
  const constructor = String(exceptionAssignDraft[row.id] || '').trim()
  if (!constructor) {
    ElMessage.warning('请选择施工员')
    return
  }
  exceptionAssigningGroupId.value = row.id
  try {
    let order = exceptionOrderFor(row)
    let orderId = order?.id || row.exceptionOrderId || ''
    if (!orderId) {
      const result = await returnGroupToException(row.id, {
        category: row.exceptionReasons?.[0] || '其他',
        note: exceptionReasonText(row),
      })
      orderId = result.orderId || ''
    }
    if (!orderId) throw new Error('异常工单创建失败')
    order = await assignConstructionExceptionOrder(orderId, constructor, '项目看板派发异常与缺照')
    exceptionAssignDraft[row.id] = order.assignedTo || constructor
    ElMessage.success(`已派发给 ${constructor}`)
    await Promise.all([loadExceptionRows(), loadBoard()])
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '派发异常与缺照失败')
  } finally {
    exceptionAssigningGroupId.value = ''
  }
}

async function unassignExceptionGroup(row: MaterialGroup) {
  if (!isAdmin.value) return
  const order = exceptionOrderFor(row)
  if (!order?.id) return
  exceptionAssigningGroupId.value = row.id
  try {
    await unassignConstructionExceptionOrder(order.id, '项目看板取消异常与缺照派发')
    exceptionAssignDraft[row.id] = ''
    ElMessage.success('已取消派发')
    await Promise.all([loadExceptionRows(), loadBoard()])
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '取消派发失败')
  } finally {
    exceptionAssigningGroupId.value = ''
  }
}

async function loadUnmatchedRows() {
  unmatchedLoading.value = true
  try {
    unmatchedRows.value = await fetchUnmatchedRecords(unmatchedQuery.value)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '未匹配清单加载失败')
  } finally {
    unmatchedLoading.value = false
  }
}

async function openUnmatchedDialog() {
  unmatchedDialogVisible.value = true
  await loadUnmatchedRows()
}

async function loadReplacementRows() {
  replacementLoading.value = true
  try {
    replacementRows.value = await fetchReplacementRecords(replacementQuery.value)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '换表清单加载失败')
  } finally {
    replacementLoading.value = false
  }
}

async function openReplacementDialog() {
  replacementDialogVisible.value = true
  await loadReplacementRows()
}

async function openReplacementFromUnmatchedDialog() {
  unmatchedDialogVisible.value = false
  await nextTick()
  await openReplacementDialog()
}

function exportReplacementCsv() {
  const rows = [
    ['资料组ID', '终端', '地址', '旧表号', '新表号', '当前表号', '照片数', '操作人', '操作时间', '状态'],
    ...replacementRows.value.map((item) => [
      item.groupId,
      item.terminal,
      item.address,
      item.oldMeterNo,
      item.newMeterNo,
      item.meterNo,
      item.photoCount,
      item.replacementBy,
      formatDateTime(item.replacementAt),
      item.status,
    ]),
  ]
  const csv = `\uFEFF${rows.map((row) => row.map(csvCell).join(',')).join('\r\n')}`
  downloadText(`换表清单-${new Date().toISOString().slice(0, 10)}.csv`, csv)
}

function exportUnmatchedCsv() {
  const rows = [
    ['未匹配ID', '表号/扫码内容', '短表号', '终端', '地址', '采集器', '模块', '安装人员', '照片数', '状态', '指派施工员', '项目外施工', '备注', '来源文件'],
    ...unmatchedRows.value.map((item) => [
      item.unmatchedId,
      item.barcode || item.meterNo,
      item.meterMatchKey,
      item.terminal,
      item.address,
      item.collector,
      item.moduleAssetNo,
      item.creator,
      item.photoCount,
      item.status,
      item.assignedTo || '',
      item.projectOutside ? '是' : '否',
      item.projectOutsideNote || item.assignmentNote || '',
      item.sourceFile || '',
    ]),
  ]
  const csv = `\uFEFF${rows.map((row) => row.map(csvCell).join(',')).join('\r\n')}`
  downloadText(`未匹配清单-${new Date().toISOString().slice(0, 10)}.csv`, csv)
}

async function cleanupDuplicateUnmatchedRows() {
  try {
    await ElMessageBox.confirm(
      '系统会按表号/扫码内容等特征保留价值最高的一条，删除重复未匹配项。已指派、项目外施工、换表记录会优先保留。',
      '清理未匹配重复项',
      {
        type: 'warning',
        confirmButtonText: '清理重复项',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  unmatchedDeduping.value = true
  try {
    const result = await dedupeUnmatchedRecords()
    ElMessage.success(result.removed ? `已清理 ${result.removed} 条重复未匹配项` : '未发现重复未匹配项')
    await Promise.all([loadUnmatchedRows(), loadBoard()])
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '重复项清理失败')
  } finally {
    unmatchedDeduping.value = false
  }
}

async function deleteUnmatchedRow(row: UnmatchedRecord) {
  try {
    await ElMessageBox.confirm(
      `确认删除未匹配记录 ${row.barcode || row.meterNo || row.unmatchedId}？删除后该记录会从未匹配清单移除。`,
      '删除未匹配记录',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  unmatchedDeletingId.value = row.unmatchedId
  try {
    await deleteUnmatchedRecord(row.unmatchedId, '项目看板人工删除未匹配记录')
    ElMessage.success('未匹配记录已删除')
    await Promise.all([loadUnmatchedRows(), loadBoard()])
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '删除未匹配记录失败')
  } finally {
    unmatchedDeletingId.value = ''
  }
}

async function replaceUnmatchedMeter(row: UnmatchedRecord) {
  try {
    const { value } = await ElMessageBox.prompt('录入旧表号，用旧表号匹配总清单地址并绑定终端', '换表匹配', {
      confirmButtonText: '匹配旧表',
      cancelButtonText: '取消',
      inputValue: row.replacementOldMeterNo || '',
      inputPattern: /\S+/,
      inputErrorMessage: '旧表号不能为空',
    })
    unmatchedRematchingId.value = row.unmatchedId
    const result = await rematchUnmatchedRecord(row.unmatchedId, {
      meterNo: row.meterNo || row.barcode || '',
      oldMeterNo: String(value || ''),
      terminal: row.terminal || '',
    })
    if (result.matched) {
      ElMessage.success('换表关系已绑定')
    } else {
      ElMessage.warning('未匹配到旧表地址，已保存换表记录')
    }
    await Promise.all([loadUnmatchedRows(), loadBoard()])
    if (replacementDialogVisible.value) await loadReplacementRows()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(error instanceof Error ? error.message : '换表失败')
  } finally {
    unmatchedRematchingId.value = ''
  }
}

function handleExternalRefresh(event: MessageEvent) {
  if (event.data?.type !== 'module-manager:data-refresh') return
  void loadBoard()
}

onMounted(() => {
  void loadBoard()
  void loadSystemHealth()
  void connectBoardEvents()
  window.addEventListener('message', handleExternalRefresh)
})
onUnmounted(() => {
  window.removeEventListener('message', handleExternalRefresh)
  disconnectBoardEvents()
})
</script>

<template>
  <section class="native-board-page">
    <div class="board-hero panel">
      <div>
        <p class="eyebrow">项目驾驶舱</p>
        <h2>进度、风险、采集与审阅态势</h2>
        <p class="muted">保留项目级导入、进度、风险和系统状态；终端级导出与施工指派统一前往任务领取。</p>
      </div>
      <div class="claim-actions">
        <label class="el-button el-button--primary" :class="{ 'is-loading': importingTotal }">
          <el-icon><Upload /></el-icon>
          <span>导入总清单</span>
          <input class="sr-only" type="file" accept=".xlsx,.xls" @change="uploadTotal" />
        </label>
        <label class="el-button" :class="{ 'is-loading': importingScan }">
          <el-icon><Upload /></el-icon>
          <span>导入扫码表格</span>
          <input class="sr-only" type="file" accept=".xlsx,.xls,.csv" @change="uploadScan" />
        </label>
        <el-button v-if="isAdmin" :loading="exportingException" @click="exportExceptionRows">导出异常表计</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="refreshBoard">刷新</el-button>
      </div>
    </div>

    <el-alert v-if="errorMessage" class="claim-alert" type="error" :closable="false" :title="errorMessage" />

    <div v-if="activeJob" class="panel import-progress">
      <strong>扫码导入任务：{{ activeJob.status }}</strong>
      <span class="muted">{{ activeJob.error || JSON.stringify(activeJob.progress || {}) }}</span>
      <el-progress :percentage="jobPercent" />
    </div>

    <div v-loading="loading" class="board-metrics">
      <article class="metric">
        <span class="metric-label">资料组</span>
        <strong class="metric-value">{{ summary.groups }}</strong>
      </article>
      <article class="metric">
        <span class="metric-label">已扫码组</span>
        <strong class="metric-value">{{ summary.scannedGroups }}</strong>
      </article>
      <article class="metric">
        <span class="metric-label">已归档</span>
        <strong class="metric-value">{{ summary.approvedGroups }}</strong>
      </article>
    </div>

    <div class="board-grid">
      <section class="panel board-progress">
        <h3>项目进度</h3>
        <div class="board-progress-row">
          <span>已扫码</span>
          <el-progress :percentage="Math.round(scannedRate * 100)" />
          <b>{{ percent(scannedRate) }}</b>
        </div>
        <div class="board-progress-row">
          <span>已归档</span>
          <el-progress :percentage="Math.round(archiveRate * 100)" />
          <b>{{ percent(archiveRate) }}</b>
        </div>
        <div class="risk-grid">
          <button class="risk-card risk-card-button bad" type="button" @click="openUnmatchedDialog">
            <span>扫码未匹配</span>
            <strong>{{ summary.scanUnmatched }}</strong>
            <small>点击查看清单</small>
          </button>
          <button class="risk-card risk-card-button bad" type="button" @click="openExceptionDialog">
            <span>异常与缺照</span>
            <strong>{{ exceptionRiskTotal }}</strong>
            <small>含缺照，查看并派发</small>
          </button>
          <article class="risk-card warn">
            <span>未施工未扫码</span>
            <strong>{{ summary.unconstructedGroups }}</strong>
          </article>
          <article class="risk-card good">
            <span>图片准确率</span>
            <strong>{{ percent(photoAccuracyRate) }}</strong>
            <small>{{ photoAccuracyCaption }}</small>
          </article>
        </div>
      </section>

      <section class="panel board-progress">
        <div class="section-head-inline">
          <h3>安装人员完成量占比</h3>
          <div class="installer-scope-tools">
            <el-select
              v-model="installerWorkloadScope"
              size="small"
              class="installer-scope-select"
              :loading="installerWorkloadLoading"
              @change="handleInstallerScopeChange"
            >
              <el-option
                v-for="item in installerScopeOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
            <label v-if="installerWorkloadScope !== 'all'" class="installer-date-field">
              <span>{{ installerScopeSelectLabel }}</span>
              <el-select
                v-model="installerScopeDate"
                size="small"
                class="installer-scope-period"
                filterable
                :disabled="installerWorkloadLoading"
                :loading="installerWorkloadLoading"
                :placeholder="installerScopePlaceholder"
                no-data-text="暂无可选周期"
              >
                <el-option
                  v-for="item in installerScopeChoices"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                />
              </el-select>
            </label>
            <span class="muted installer-scope-hint">{{ installerScopeHint }}</span>
          </div>
        </div>
        <div v-if="filteredInstallerDistribution.length" v-loading="installerWorkloadLoading" class="installer-list">
          <button
            v-for="item in filteredInstallerDistribution"
            :key="item.installer"
            class="installer-row installer-row-button"
            type="button"
            @click="openInstallerWorkload(item.installer)"
          >
            <span>{{ item.installer }}</span>
            <el-progress :percentage="Math.round(item.share * 100)" />
            <b>{{ item.groupCount }}</b>
          </button>
        </div>
        <el-empty v-else :description="installerWorkloadLoading ? '正在加载工作量' : '暂无安装人员统计'" />
      </section>
    </div>

    <section class="panel cockpit-panel">
      <div class="construction-panel-head">
        <div>
          <h3>终端流转态势</h3>
          <span>仅展示聚合态势，不承载单终端导出、审阅跳转或施工指派操作。</span>
        </div>
      </div>
      <div class="cockpit-body">
        <div class="cockpit-flow" aria-label="终端流转阶段">
          <article v-for="item in cockpitFlow" :key="item.label" class="flow-node">
            <div>
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
            <div class="flow-track" aria-hidden="true">
              <i :style="{ width: `${flowPercent(item.value)}%` }" />
            </div>
            <small>{{ item.hint }} / {{ flowPercent(item.value) }}%</small>
          </article>
        </div>

        <div class="cockpit-rings">
          <article>
            <div class="cockpit-ring" :style="reviewRingStyle">
              <span>{{ percent(archiveRate) }}</span>
            </div>
            <div>
              <strong>归档闭环率</strong>
              <small>{{ reviewGap }} 个资料组待闭环</small>
            </div>
          </article>
          <article>
            <div class="cockpit-ring teal" :style="uploadRingStyle">
              <span>{{ percent(terminalCockpit.avgUploadRate) }}</span>
            </div>
            <div>
              <strong>终端平均上传率</strong>
              <small>{{ terminalCockpit.uploaded }} 个终端已有照片回流</small>
            </div>
          </article>
        </div>

        <div class="cockpit-signals">
          <article v-for="signal in cockpitSignals" :key="signal.label" :class="['signal-card', signal.tone]">
            <span>{{ signal.label }}</span>
            <strong>{{ signal.value }}</strong>
            <small>{{ signal.caption }}</small>
          </article>
        </div>
      </div>
    </section>

    <section v-if="systemRows.length" class="panel system-status">
      <h3>系统状态</h3>
      <div class="system-row" v-for="[label, value] in systemRows" :key="label">
        <span>{{ label }}</span>
        <strong>{{ value }}</strong>
      </div>
      <p class="system-note">
        数据文件指当前业务状态快照（例如 local_state.json）的大小，不等同于照片容量；照片容量请以 uploads 或 OSS
        存储统计为准。
      </p>
    </section>

    <el-dialog v-model="workloadDialogVisible" :title="`${workloadInstaller} 每日工作量`" width="1180px">
      <div class="workload-summary">
        <article>
          <span>资料组</span>
          <strong>{{ workloadTotals.groupCount }}</strong>
        </article>
        <article>
          <span>照片</span>
          <strong>{{ workloadTotals.photoCount }}</strong>
        </article>
        <article>
          <span>已归档</span>
          <strong>{{ workloadTotals.archivedCount }}</strong>
        </article>
        <article>
          <span>异常</span>
          <strong>{{ workloadTotals.exceptionCount }}</strong>
        </article>
        <article>
          <span>总工时</span>
          <strong>{{ formatWorkDuration(workloadTotals.workDurationMinutes) }}</strong>
        </article>
        <article>
          <span>完成量</span>
          <strong>{{ workloadTotals.completionCount }}</strong>
        </article>
        <article>
          <span>加权完成</span>
          <strong>{{ formatDecimal(workloadTotals.weightedCompletion, 1) }}</strong>
        </article>
        <article>
          <span>计入工时</span>
          <strong>{{ formatWorkDuration(workloadTotals.fusedWorkDurationMinutes) }}</strong>
        </article>
      </div>
      <el-table v-loading="workloadLoading" :data="workloadRows" height="360" size="small">
        <el-table-column prop="date" label="日期" min-width="120" />
        <el-table-column prop="startTime" label="开工" width="82">
          <template #default="{ row }">
            <span>{{ row.startTime || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="endTime" label="收工" width="82">
          <template #default="{ row }">
            <span>{{ row.endTime || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="工作时长" width="120">
          <template #default="{ row }">
            <el-button
              v-if="row.timepointCount"
              class="workload-exception-link"
              link
              type="primary"
              @click.stop="openWorkloadTimeChart(row)"
            >
              {{ row.workDurationLabel || formatWorkDuration(row.workDurationMinutes) }}
            </el-button>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="completionPerEffectiveHour" label="每小时完成" width="110">
          <template #default="{ row }">
            <span>{{ formatDecimal(row.completionPerEffectiveHour) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="weightedCompletionPerEffectiveHour" label="加权效率" width="110">
          <template #default="{ row }">
            <span>{{ formatDecimal(row.weightedCompletionPerEffectiveHour) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="计入工时" width="110">
          <template #default="{ row }">
            <span>{{ row.fusedWorkDurationLabel || formatWorkDuration(row.fusedWorkDurationMinutes) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="融合效率" width="96">
          <template #default="{ row }">
            <span>{{ formatDecimal(row.fusedWeightedCompletionPerEffectiveHour) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="在线系数" width="96">
          <template #default="{ row }">
            <span>{{ formatDecimal(row.finalOnlineCoefficient) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="denseBonusMinutesV2" label="补偿" width="86">
          <template #default="{ row }">
            <span>{{ row.denseBonusMinutesV2 ? `${row.denseBonusMinutesV2}分钟` : '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="groupCount" label="资料组" width="92" />
        <el-table-column prop="photoCount" label="照片" width="92" />
        <el-table-column prop="archivedCount" label="已归档" width="92" />
        <el-table-column label="异常" width="92">
          <template #default="{ row }">
            <el-button
              v-if="row.exceptionCount"
              class="workload-exception-link"
              link
              type="danger"
              @click.stop="openWorkloadExceptionGroups(row)"
            >
              {{ row.exceptionCount }}
            </el-button>
            <span v-else>0</span>
          </template>
        </el-table-column>
        <el-table-column prop="unreviewedCount" label="未审阅" width="92" />
      </el-table>
      <template #footer>
        <el-button @click="workloadDialogVisible = false">关闭</el-button>
        <el-button type="primary" :disabled="!workloadRows.length" @click="exportInstallerWorkloadCsv">
          导出 KPI CSV
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="exceptionDialogVisible" title="异常与缺照" width="1120px" class="unmatched-board-dialog">
      <div class="unmatched-dialog-head">
        <div class="unmatched-dialog-stats">
          <article>
            <span>异常/缺照</span>
            <strong>{{ exceptionDialogStats.total }}</strong>
          </article>
          <article>
            <span>待派发</span>
            <strong>{{ exceptionDialogStats.pending }}</strong>
          </article>
          <article>
            <span>已派发</span>
            <strong>{{ exceptionDialogStats.assigned }}</strong>
          </article>
          <article>
            <span>当前筛选</span>
            <strong>{{ filteredExceptionRows.length }}</strong>
          </article>
        </div>
        <div class="unmatched-dialog-tools exception-dialog-tools">
          <el-input
            v-model="exceptionQuery"
            clearable
            placeholder="搜索表号、地址、终端、采集器、模块或异常原因"
          />
          <el-button :loading="exceptionLoading" @click="loadExceptionRows">刷新</el-button>
          <el-button :disabled="!filteredExceptionRows.length" @click="exportExceptionGroupCsv">导出清单</el-button>
          <el-button v-if="isAdmin" :disabled="!constructorOptions.length" @click="loadAccounts">刷新施工员</el-button>
        </div>
      </div>
      <el-alert
        class="claim-alert"
        type="info"
        :closable="false"
        title="异常与缺照记录可直接派发给施工员。施工员会在施工采集页看到异常任务卡，进入后只补充缺失或错误的数据。"
      />
      <el-table v-loading="exceptionLoading" :data="filteredExceptionRows" height="520" size="small">
        <el-table-column type="index" width="52" label="#" />
        <el-table-column label="表号 / 资料组" min-width="150">
          <template #default="{ row }">
            <strong>{{ row.meterNo || '-' }}</strong>
            <small class="table-subline">{{ row.id }}</small>
          </template>
        </el-table-column>
        <el-table-column prop="terminal" label="终端" min-width="120" />
        <el-table-column prop="address" label="地址" min-width="260" show-overflow-tooltip />
        <el-table-column prop="constructionCollector" label="采集器" min-width="150" show-overflow-tooltip />
        <el-table-column prop="constructionModuleAssetNo" label="模块" min-width="150" show-overflow-tooltip />
        <el-table-column label="异常原因" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="exception-reasons">{{ exceptionReasonText(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="派发状态" width="110">
          <template #default="{ row }">
            <el-tag v-if="exceptionOrderFor(row)?.assignedTo" type="success" effect="plain">
              已派发
            </el-tag>
            <el-tag v-else type="warning" effect="plain">待派发</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="施工员" min-width="260">
          <template #default="{ row }">
            <div v-if="isAdmin" class="exception-assign-cell">
              <el-select
                v-model="exceptionAssignDraft[row.id]"
                filterable
                allow-create
                default-first-option
                size="small"
                placeholder="选择或输入施工员账号"
              >
                <el-option
                  v-for="item in constructorOptions"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                />
              </el-select>
              <el-button
                size="small"
                type="primary"
                :loading="exceptionAssigningGroupId === row.id"
                @click="assignExceptionGroup(row)"
              >
                派发
              </el-button>
            </div>
            <span v-else>{{ exceptionOrderFor(row)?.assignedTo || '未派发' }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="isAdmin" label="操作" width="96">
          <template #default="{ row }">
            <el-button
              size="small"
              plain
              :disabled="!exceptionOrderFor(row)?.assignedTo"
              :loading="exceptionAssigningGroupId === row.id"
              @click="unassignExceptionGroup(row)"
            >
              取消
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="exceptionDialogVisible = false">关闭</el-button>
        <el-button type="primary" :disabled="!filteredExceptionRows.length" @click="exportExceptionGroupCsv">导出当前清单</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="replacementDialogVisible" title="换表清单" width="1080px" class="unmatched-board-dialog" append-to-body>
      <div class="unmatched-dialog-head">
        <div class="unmatched-dialog-stats">
          <article>
            <span>换表记录</span>
            <strong>{{ replacementDialogStats.total }}</strong>
          </article>
          <article>
            <span>涉及终端</span>
            <strong>{{ replacementDialogStats.terminals }}</strong>
          </article>
          <article>
            <span>操作人</span>
            <strong>{{ replacementDialogStats.operators }}</strong>
          </article>
          <article>
            <span>照片数</span>
            <strong>{{ replacementDialogStats.photos }}</strong>
          </article>
        </div>
        <div class="unmatched-dialog-tools">
          <el-input
            v-model="replacementQuery"
            clearable
            placeholder="搜索旧表号、新表号、地址、终端或操作人"
            @keyup.enter="loadReplacementRows"
            @clear="loadReplacementRows"
          />
          <el-button :loading="replacementLoading" @click="loadReplacementRows">刷新</el-button>
          <el-button :disabled="!replacementRows.length" @click="exportReplacementCsv">导出清单</el-button>
        </div>
      </div>
      <el-alert
        class="claim-alert"
        type="info"
        :closable="false"
        title="这里展示通过未匹配资料人工录入旧表号后，已成功匹配到总清单资料组的换表记录。"
      />
      <el-table v-loading="replacementLoading" :data="replacementRows" height="520" size="small">
        <el-table-column type="index" width="54" label="#" />
        <el-table-column label="旧表号 / 新表号" min-width="180">
          <template #default="{ row }">
            <strong>{{ row.oldMeterNo || '-' }}</strong>
            <small class="table-subline">新：{{ row.newMeterNo || '-' }}</small>
          </template>
        </el-table-column>
        <el-table-column prop="terminal" label="终端" min-width="120" />
        <el-table-column prop="address" label="匹配地址" min-width="280" show-overflow-tooltip />
        <el-table-column label="资料组" min-width="150">
          <template #default="{ row }">
            <strong>{{ row.groupId || '-' }}</strong>
            <small class="table-subline">当前：{{ row.meterNo || '-' }}</small>
          </template>
        </el-table-column>
        <el-table-column prop="photoCount" label="照片" width="76" />
        <el-table-column prop="replacementBy" label="操作人" width="110" />
        <el-table-column label="操作时间" min-width="180">
          <template #default="{ row }">
            <span>{{ formatDateTime(row.replacementAt) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="资料状态" width="110" />
      </el-table>
      <template #footer>
        <el-button @click="replacementDialogVisible = false">关闭</el-button>
        <el-button type="primary" :disabled="!replacementRows.length" @click="exportReplacementCsv">导出当前清单</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="unmatchedDialogVisible" title="未匹配清单" width="1040px" class="unmatched-board-dialog">
      <div class="unmatched-dialog-head">
        <div class="unmatched-dialog-stats">
          <article>
            <span>当前清单</span>
            <strong>{{ unmatchedDialogStats.total }}</strong>
          </article>
          <article>
            <span>待处理</span>
            <strong>{{ unmatchedDialogStats.pending }}</strong>
          </article>
          <article>
            <span>已指派</span>
            <strong>{{ unmatchedDialogStats.assigned }}</strong>
          </article>
          <article>
            <span>项目外</span>
            <strong>{{ unmatchedDialogStats.outside }}</strong>
          </article>
        </div>
        <div class="unmatched-dialog-tools unmatched-record-tools">
          <el-input
            v-model="unmatchedQuery"
            clearable
            placeholder="搜索表号、地址、终端、采集器或模块"
            @keyup.enter="loadUnmatchedRows"
            @clear="loadUnmatchedRows"
          />
          <el-button :loading="unmatchedLoading" @click="loadUnmatchedRows">刷新</el-button>
          <el-dropdown trigger="click">
            <el-button plain>
              更多
              <el-icon class="el-icon--right"><MoreFilled /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item :disabled="!unmatchedRows.length" @click="exportUnmatchedCsv">
                  导出清单
                </el-dropdown-item>
                <el-dropdown-item :disabled="unmatchedDeduping" @click="cleanupDuplicateUnmatchedRows">
                  删除重复项
                </el-dropdown-item>
                <el-dropdown-item @click="openReplacementFromUnmatchedDialog">
                  换表清单 {{ replacementRows.length ? `(${replacementRows.length})` : '' }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
      <el-alert
        class="claim-alert"
        type="info"
        :closable="false"
        title="重复项按表号/扫码内容等特征识别。系统会优先保留已指派、项目外施工、换表记录或照片更多的记录。"
      />
      <el-table v-loading="unmatchedLoading" :data="unmatchedRows" height="520" size="small">
        <el-table-column type="index" width="54" label="#" />
        <el-table-column label="表号 / 扫码内容" min-width="150">
          <template #default="{ row }">
            <strong>{{ row.barcode || row.meterNo || '-' }}</strong>
            <small class="table-subline">{{ row.meterMatchKey || row.unmatchedId }}</small>
          </template>
        </el-table-column>
        <el-table-column prop="terminal" label="终端" min-width="120" />
        <el-table-column prop="address" label="地址" min-width="280" show-overflow-tooltip />
        <el-table-column prop="collector" label="采集器" min-width="150" show-overflow-tooltip />
        <el-table-column prop="moduleAssetNo" label="模块" min-width="150" show-overflow-tooltip />
        <el-table-column prop="creator" label="安装人员" width="100" />
        <el-table-column prop="photoCount" label="照片" width="76" />
        <el-table-column label="状态" width="118">
          <template #default="{ row }">
            <el-tag v-if="row.projectOutside" type="warning" effect="plain">项目外</el-tag>
            <el-tag v-else-if="row.replacementOldMeterNo" type="info" effect="plain">换表</el-tag>
            <el-tag v-else-if="row.assignedTo" type="success" effect="plain">已指派</el-tag>
            <el-tag v-else effect="plain">待处理</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="assignedTo" label="指派" width="110" />
        <el-table-column prop="sourceFile" label="来源文件" min-width="150" show-overflow-tooltip />
        <el-table-column label="操作" width="94" fixed="right">
          <template #default="{ row }">
            <el-dropdown trigger="click">
              <el-button
                size="small"
                plain
                :loading="unmatchedRematchingId === row.unmatchedId || unmatchedDeletingId === row.unmatchedId"
              >
                操作
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    :disabled="unmatchedRematchingId === row.unmatchedId || unmatchedDeletingId === row.unmatchedId"
                    @click="replaceUnmatchedMeter(row)"
                  >
                    换表
                  </el-dropdown-item>
                  <el-dropdown-item
                    :disabled="unmatchedRematchingId === row.unmatchedId || unmatchedDeletingId === row.unmatchedId"
                    @click="deleteUnmatchedRow(row)"
                  >
                    删除
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="unmatchedDialogVisible = false">关闭</el-button>
        <el-button type="primary" :disabled="!unmatchedRows.length" @click="exportUnmatchedCsv">导出当前清单</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="workloadTimeDialogVisible" :title="workloadTimeTitle" width="900px">
      <div v-if="workloadTimeRow" class="work-time-detail">
        <div class="work-time-stats">
          <article>
            <span>开工</span>
            <strong>{{ workloadTimeRow.startTime || '-' }}</strong>
          </article>
          <article>
            <span>收工</span>
            <strong>{{ workloadTimeRow.endTime || '-' }}</strong>
          </article>
          <article>
            <span>推算工时</span>
            <strong>{{ workloadTimeRow.workDurationLabel || formatWorkDuration(workloadTimeRow.workDurationMinutes) }}</strong>
          </article>
          <article>
            <span>连续补偿</span>
            <strong>{{ workloadTimeRow.denseBonusMinutesV2 }}分钟</strong>
          </article>
          <article>
            <span>考勤跨度</span>
            <strong>{{ workloadTimeRow.workSpanLabel || formatWorkDuration(workloadTimeRow.workSpanMinutes) }}</strong>
          </article>
          <article>
            <span>每小时完成</span>
            <strong>{{ formatDecimal(workloadTimeRow.completionPerEffectiveHour) }}</strong>
          </article>
          <article>
            <span>加权效率</span>
            <strong>{{ formatDecimal(workloadTimeRow.weightedCompletionPerEffectiveHour) }}</strong>
          </article>
          <article>
            <span>在线补偿系数</span>
            <strong>{{ formatDecimal(workloadTimeRow.baseOnlineCoefficient) }}</strong>
          </article>
          <article>
            <span>挂机扣减</span>
            <strong>-{{ formatDecimal(workloadTimeRow.idlePenaltyCoefficient) }}</strong>
          </article>
          <article>
            <span>最终系数</span>
            <strong>{{ formatDecimal(workloadTimeRow.finalOnlineCoefficient) }}</strong>
          </article>
          <article>
            <span>融合加权效率</span>
            <strong>{{ formatDecimal(workloadTimeRow.fusedWeightedCompletionPerEffectiveHour) }}</strong>
          </article>
        </div>
        <p class="work-time-note">
          按 2 小时展示有效工时与完成量。25分钟内按实际间隔计入，25-45分钟压缩为25分钟，超过45分钟断开；2小时内至少15个有效gap且90%满足短gap时，补偿15或25分钟。地址权重会降低同楼集中施工的寻找成本，并提高缺少室号、零散地址、充电桩/车位等现场寻找难度。
        </p>
        <section class="screen-time-card" :aria-label="`${workloadTimeTitle}，按 2 小时展示有效工时和完成量`">
          <div class="screen-time-head">
            <div>
              <strong>2 小时效率分布</strong>
              <span>柱高为有效工时，数字为完成资料组，点按时段查看地址清单。</span>
            </div>
            <div class="screen-time-legend" aria-hidden="true">
              <span><i class="legend-bar" />有效工时</span>
              <span><i class="legend-dot" />完成量</span>
            </div>
          </div>
          <div class="work-time-chart" role="img">
            <article
              v-for="segment in workloadTimeSegments"
              :key="segment.label"
              class="work-time-segment"
              :class="{ active: segment.minutes > 0, clickable: (segment.addresses?.length || 0) > 0 }"
              @click="openWorkloadSegmentDetail(segment)"
            >
              <div class="work-time-value">
                <strong>{{ segment.completionCount || 0 }}组</strong>
                <span>{{ segment.minutes ? segment.durationLabel : '0分钟' }}</span>
              </div>
              <div class="work-time-bar-track">
                <span class="work-time-bar" :style="{ height: `${workloadBarHeight(segment.minutes)}%` }" />
              </div>
              <small>效 {{ formatDecimal(segment.completionPerEffectiveHour || 0) }}/h</small>
              <span class="work-time-label">{{ segment.label }}</span>
            </article>
          </div>
        </section>
      </div>
      <template #footer>
        <el-button @click="workloadTimeDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="workloadSegmentDialogVisible" :title="workloadSegmentTitle" width="920px">
      <el-alert
        class="claim-alert"
        type="info"
        :closable="false"
        title="效率权重：同楼/同区集中地址降低权重；缺少室号、零散地址、充电桩/车位提高权重。权重用于 KPI 修正，不改变原始完成量。"
      />
      <el-table :data="workloadSegment?.addresses || []" height="430" size="small">
        <el-table-column prop="completedTime" label="时间" width="76" />
        <el-table-column prop="meterNo" label="表号" min-width="130" />
        <el-table-column prop="terminal" label="终端" min-width="120" />
        <el-table-column prop="address" label="地址" min-width="260" show-overflow-tooltip />
        <el-table-column label="地址类型" min-width="150">
          <template #default="{ row }">
            <span>{{ row.difficultyLabel }} × {{ formatDecimal(row.difficultyWeight) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="判断原因" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <span>{{ row.difficultyReasons?.length ? row.difficultyReasons.join('；') : '标准地址' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="photoCount" label="照片" width="70" />
      </el-table>
      <template #footer>
        <el-button @click="workloadSegmentDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="workloadExceptionDialogVisible" :title="workloadExceptionTitle" width="860px">
      <el-alert
        class="claim-alert"
        type="info"
        :closable="false"
        title="点击日期异常数后展示该安装人员当天产生的异常资料组，便于按人、按天追溯问题。"
      />
      <el-table :data="workloadExceptionGroups" height="420" size="small">
        <el-table-column prop="meterNo" label="表号" min-width="130" />
        <el-table-column prop="terminal" label="终端" min-width="130" />
        <el-table-column prop="address" label="地址" min-width="240" show-overflow-tooltip />
        <el-table-column label="异常原因" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="exception-reasons">
              {{ row.exceptionReasons?.length ? row.exceptionReasons.join('；') : row.exceptionNote || '未填写' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="photoCount" label="照片" width="76" />
      </el-table>
      <template #footer>
        <el-button @click="workloadExceptionDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.section-head-inline {
  align-items: baseline;
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.native-board-page .board-metrics {
  grid-template-columns: repeat(3, minmax(136px, 1fr));
}

.native-board-page .risk-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.native-board-page .cockpit-signals {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.installer-scope-tools {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
  flex-wrap: wrap;
}

.installer-scope-select {
  width: 96px;
}

.installer-scope-period {
  width: 220px;
}

.installer-date-field {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--v2-text-muted, #64748b);
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.installer-scope-hint {
  min-width: 150px;
  text-align: right;
}

.installer-row-button {
  width: 100%;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.installer-row-button:hover {
  color: var(--v2-primary);
}

.risk-card-button {
  width: 100%;
  border: 1px solid var(--v2-border-soft, #dde5ee);
  color: inherit;
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.risk-card-button:hover {
  border-color: rgba(15, 120, 146, 0.36);
  box-shadow: var(--v2-shadow-raised, 0 1px 2px rgba(15, 26, 36, 0.05));
  transform: translateY(-1px);
}

.risk-card-button small {
  color: var(--v2-text-muted, #64748b);
  font-size: 11px;
  font-weight: 700;
}

.unmatched-dialog-head {
  display: grid;
  gap: 12px;
  margin-bottom: 12px;
}

.unmatched-dialog-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.unmatched-dialog-stats article {
  display: grid;
  gap: 4px;
  min-height: 72px;
  padding: 12px;
  border: 1px solid var(--v2-border-soft, #dde5ee);
  border-radius: var(--v2-radius-md, 9px);
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
}

.unmatched-dialog-stats span {
  color: var(--v2-text-muted, #64748b);
  font-size: 12px;
  font-weight: 760;
}

.unmatched-dialog-stats strong {
  color: var(--v2-text-strong, #0f172a);
  font-size: 24px;
  line-height: 1.1;
}

.unmatched-dialog-tools {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) auto auto auto;
  gap: 10px;
  align-items: center;
}

.unmatched-record-tools {
  grid-template-columns: minmax(280px, 1fr) auto auto;
}

.exception-dialog-tools {
  grid-template-columns: minmax(320px, 1fr) auto auto auto;
}

.exception-assign-cell {
  display: grid;
  grid-template-columns: minmax(132px, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.exception-assign-cell :deep(.el-select) {
  min-width: 0;
}

.exception-assign-cell :deep(.el-button),
.unmatched-board-dialog :deep(.el-tag) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}

.table-subline {
  display: block;
  margin-top: 3px;
  color: var(--v2-text-muted, #64748b);
  font-size: 11px;
  line-height: 1.3;
}

.task-export-actions {
  align-items: center;
  display: flex;
  gap: 8px;
  min-width: 0;
}

.export-scope-select {
  width: 92px;
}

.system-note {
  margin: 4px 0 0;
  color: var(--v2-text-muted, #64748b);
  font-size: 12px;
  line-height: 1.6;
}

.workload-summary {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.workload-summary article {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid var(--v2-border-soft, #dde5ee);
  border-radius: var(--v2-radius-md, 9px);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.9));
  box-shadow: var(--v2-shadow-hairline, 0 0 0 1px rgba(17, 24, 39, 0.03));
}

.workload-summary span {
  color: var(--v2-text-muted, #64748b);
  font-size: 12px;
}

.workload-summary strong {
  color: var(--v2-text-strong, #0f172a);
  font-size: 22px;
}

.workload-exception-link {
  height: auto;
  padding: 0;
  font-weight: 800;
}

.exception-reasons {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
  white-space: nowrap;
}

.work-time-detail {
  display: grid;
  gap: 14px;
}

.work-time-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(116px, 1fr));
  gap: 10px;
}

.work-time-stats article {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid var(--v2-border-soft, #dde5ee);
  border-radius: var(--v2-radius-md, 9px);
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  box-shadow: var(--v2-shadow-hairline, 0 0 0 1px rgba(17, 24, 39, 0.03));
}

.work-time-stats span,
.work-time-note {
  color: var(--v2-text-muted, #64748b);
  font-size: 12px;
}

.work-time-stats strong {
  color: var(--v2-text-strong, #0f172a);
  font-size: 20px;
}

.work-time-note {
  margin: 0;
  line-height: 1.7;
}

.screen-time-card {
  display: grid;
  gap: 14px;
  padding: 16px 18px 14px;
  border: 1px solid var(--v2-border-soft, #dde5ee);
  border-radius: var(--v2-radius-panel, 12px);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 251, 253, 0.96)),
    #ffffff;
  box-shadow: var(--v2-shadow-raised, 0 1px 2px rgba(15, 26, 36, 0.05)), inset 0 1px 0 rgba(255, 255, 255, 0.8);
}

.screen-time-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.screen-time-head > div:first-child {
  display: grid;
  gap: 4px;
}

.screen-time-head strong {
  color: var(--v2-text-strong, #0f172a);
  font-size: 15px;
  line-height: 1.3;
}

.screen-time-head span,
.screen-time-legend {
  color: var(--v2-text-muted, #64748b);
  font-size: 12px;
  line-height: 1.5;
}

.screen-time-legend {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10px;
  min-width: 190px;
}

.screen-time-legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.legend-bar,
.legend-dot {
  display: inline-block;
  background: #0f7892;
}

.legend-bar {
  width: 8px;
  height: 16px;
  border-radius: 999px;
}

.legend-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
}

.work-time-chart {
  display: grid;
  grid-template-columns: repeat(12, minmax(62px, 1fr));
  gap: 10px;
  align-items: end;
  min-height: 300px;
  padding: 6px 2px 0;
  overflow-x: auto;
}

.work-time-segment {
  display: grid;
  grid-template-rows: 48px 154px 18px 36px;
  gap: 7px;
  justify-items: center;
  min-width: 62px;
  color: var(--v2-text-muted, #64748b);
  font-size: 11px;
  font-weight: 800;
  padding: 8px 4px 7px;
  border: 1px solid transparent;
  border-radius: var(--v2-radius-md, 9px);
}

.work-time-segment.clickable {
  cursor: pointer;
}

.work-time-segment.clickable:hover {
  border-color: rgba(15, 120, 146, 0.24);
  background: rgba(255, 255, 255, 0.76);
  box-shadow: var(--v2-shadow-raised, 0 1px 2px rgba(15, 26, 36, 0.05));
}

.work-time-value {
  display: grid;
  align-content: end;
  gap: 2px;
  min-height: 48px;
  text-align: center;
}

.work-time-value strong {
  color: var(--v2-text-strong, #0f172a);
  font-size: 14px;
  line-height: 1.15;
}

.work-time-value span {
  color: var(--v2-text-muted, #64748b);
  font-size: 11px;
  line-height: 1.25;
}

.work-time-bar-track {
  display: flex;
  align-items: end;
  justify-content: center;
  width: 28px;
  height: 154px;
  border-radius: 999px;
  background: #e8eef5;
  overflow: hidden;
}

.work-time-bar {
  display: block;
  width: 100%;
  min-height: 0;
  border-radius: 999px;
  background: linear-gradient(180deg, #18a0c8 0%, #0a72d8 100%);
}

.work-time-segment.active strong {
  color: var(--v2-text-strong, #0f172a);
}

.work-time-segment em,
.work-time-segment small {
  font-style: normal;
}

.work-time-segment small {
  color: var(--v2-text-muted, #64748b);
}

.work-time-label {
  display: block;
  max-width: 64px;
  color: var(--v2-text-muted, #64748b);
  font-weight: 760;
  line-height: 1.35;
  text-align: center;
}
@media (max-width: 1280px) {
  .account-form-grid {
    grid-template-columns: repeat(3, minmax(160px, 1fr));
  }

  .workload-summary,
  .work-time-stats {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .account-form-grid,
  .workload-summary,
  .unmatched-dialog-stats,
  .work-time-stats {
    grid-template-columns: 1fr;
  }

  .unmatched-dialog-tools {
    grid-template-columns: 1fr;
  }

  .work-time-chart {
    grid-template-columns: repeat(12, 74px);
  }

  .account-actions {
    justify-content: flex-end;
  }
}
</style>
