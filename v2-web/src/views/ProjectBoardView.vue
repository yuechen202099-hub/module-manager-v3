<script setup lang="ts">
import { Download, Refresh, Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  boardEventHeaders,
  boardEventsUrl,
  downloadProjectMeterModuleWorkbook,
  fetchInstallerWorkload,
  fetchProjectSummary,
  fetchTasks,
  fetchTaskStatus,
  importTotalCatalog,
} from '@/api/services'
import type {
  ImportJob,
  InstallerWorkload,
  InstallerWorkloadRow,
  ProjectSummary,
  ReviewTask,
  TaskStatusSummary,
} from '@/api/types'
import InstallerKpiDialog from '@/components/InstallerKpiDialog.vue'
import { useAuthStore } from '@/stores/auth'
import {
  buildDataCenterDrilldown,
  type DataCenterDrilldownContext,
  type DataCenterDrilldownKind,
} from '@/utils/dataCenterDrilldown'
import type { InstallerKpiScope } from '@/utils/installerKpi'

const router = useRouter()
const auth = useAuthStore()

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
  groupBarcodeAccuracyChecked: 0,
  groupBarcodeAccuracyPassed: 0,
  groupBarcodeAccuracyFailed: 0,
  groupBarcodeAccuracyUnreadable: 0,
  groupBarcodeAccuracyNotRequired: 0,
  groupBarcodeAccuracyRate: 0,
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

const BOARD_REFRESH_INTERVAL_MS = 15 * 60 * 1000

const loading = ref(false)
const importingTotal = ref(false)
const importingScan = ref(false)
const exportingMeterModule = ref(false)
const summary = ref<ProjectSummary>({ ...emptySummary })
const taskStatus = ref<TaskStatusSummary>({ ...emptyTaskStatus })
const terminalTasks = ref<ReviewTask[]>([])
const activeJob = ref<ImportJob | null>(null)
const errorMessage = ref('')
const installerWorkloadScope = ref<'all' | 'day' | 'week' | 'month'>('all')
const installerScopeDate = ref('')
const installerWorkloadLoading = ref(false)
const installerWorkloadCache = reactive<Record<string, InstallerWorkloadRow[]>>({})
const installerKpiDialogVisible = ref(false)
const installerKpiInstaller = ref('')

let boardEventAbortController: AbortController | null = null
let boardFallbackTimer = 0

const installerWorkloadFetchConcurrency = 3

const isAdmin = computed(() => Boolean(auth.user?.roles?.includes('admin') || auth.user?.role === 'admin'))
const scannedRate = computed(() => (summary.value.groups ? summary.value.scannedGroups / summary.value.groups : 0))
const archiveRate = computed(() => (summary.value.groups ? summary.value.approvedGroups / summary.value.groups : 0))

const summaryCards = computed<Array<{ label: string; value: number; drilldown: DataCenterDrilldownKind }>>(() => [
  { label: '资料组', value: summary.value.groups, drilldown: 'groups' },
  { label: '已扫码组', value: summary.value.scannedGroups, drilldown: 'scanned_groups' },
  { label: '已归档', value: summary.value.approvedGroups, drilldown: 'archived_groups' },
])

const progressRows = computed<Array<{ label: string; percentage: number; valueLabel: string; drilldown: DataCenterDrilldownKind }>>(() => [
  {
    label: '已扫码',
    percentage: Math.round(scannedRate.value * 100),
    valueLabel: percent(scannedRate.value),
    drilldown: 'scanned_groups',
  },
  {
    label: '已归档',
    percentage: Math.round(archiveRate.value * 100),
    valueLabel: percent(archiveRate.value),
    drilldown: 'archived_groups',
  },
])

const riskCards = computed<
  Array<{ label: string; value: number; tone: 'bad' | 'warn'; drilldown: DataCenterDrilldownKind }>
>(() => [
  {
    label: '扫码未匹配',
    value: summary.value.scanUnmatched,
    tone: 'bad',
    drilldown: 'unmatched_records',
  },
  {
    label: '异常与缺照',
    value: summary.value.exceptionGroups,
    tone: 'bad',
    drilldown: 'exception_missing_photo',
  },
  {
    label: '未施工未扫码',
    value: summary.value.unconstructedGroups,
    tone: 'warn',
    drilldown: 'unconstructed_unscanned',
  },
])

type TerminalStatusFilter = 'all' | 'completed' | 'incomplete' | 'pending_archive' | 'archived'

const terminalTotal = computed(() => terminalTasks.value.length || taskStatus.value.total)
const terminalCompletedCount = computed(() => terminalTasks.value.filter(isTerminalConstructionCompleted).length)
const terminalIncompleteCount = computed(() => terminalTasks.value.filter((task) => !isTerminalConstructionCompleted(task)).length)
const terminalPendingArchiveCount = computed(() => terminalTasks.value.filter(isTerminalPendingArchive).length)
const terminalArchivedCount = computed(() => terminalTasks.value.filter(isTerminalArchived).length)
const cockpitFlow = computed<
  Array<{ key: TerminalStatusFilter; label: string; value: number; drilldown: DataCenterDrilldownKind }>
>(() => [
  { key: 'all', label: '终端总数', value: terminalTotal.value, drilldown: 'terminal_all' },
  { key: 'completed', label: '已完成施工', value: terminalCompletedCount.value, drilldown: 'terminal_completed' },
  { key: 'incomplete', label: '未完成施工', value: terminalIncompleteCount.value, drilldown: 'terminal_incomplete' },
  { key: 'pending_archive', label: '待归档', value: terminalPendingArchiveCount.value, drilldown: 'terminal_pending_archive' },
  { key: 'archived', label: '已归档', value: terminalArchivedCount.value, drilldown: 'terminal_archived' },
])

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

const installerKpiScope = computed<InstallerKpiScope>(() => ({
  mode: installerWorkloadScope.value,
  anchorDate: installerScopeAnchorDate() || '',
}))

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

function percent(value: number) {
  if (!Number.isFinite(value)) return '0%'
  return `${Math.round(value * 100)}%`
}

function flowPercent(value: number) {
  const total = Math.max(terminalTotal.value, 1)
  return Math.max(0, Math.min(100, Math.round((Number(value || 0) / total) * 100)))
}

function taskTotalGroups(task: ReviewTask) {
  return Math.max(0, Number(task.renovationCount ?? task.totalGroups ?? 0))
}

function taskUploadedCount(task: ReviewTask) {
  return Math.max(0, Number(task.constructionUploadedCount ?? task.uploadedCount ?? task.claimedGroups ?? 0))
}

function taskReviewedCount(task: ReviewTask) {
  return Math.max(0, Number(task.reviewedCount ?? task.completedGroups ?? 0))
}

function taskUnreviewedCount(task: ReviewTask) {
  const total = taskTotalGroups(task)
  return Math.max(0, Number(task.unreviewedCount ?? total - taskReviewedCount(task)))
}

function taskUnbuiltCount(task: ReviewTask) {
  const total = taskTotalGroups(task)
  return Math.max(0, Number(task.constructionUnbuiltCount ?? total - taskUploadedCount(task)))
}

function isTerminalConstructionCompleted(task: ReviewTask) {
  const total = taskTotalGroups(task)
  return total > 0 && taskUnbuiltCount(task) <= 0
}

function isTerminalArchived(task: ReviewTask) {
  return taskUploadedCount(task) > 0 && taskUnreviewedCount(task) <= 0
}

function isTerminalPendingArchive(task: ReviewTask) {
  return isTerminalConstructionCompleted(task) && !isTerminalArchived(task)
}

function formatLocalDate(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function dateTime(date: string) {
  const time = new Date(`${date}T00:00:00`).getTime()
  return Number.isFinite(time) ? time : 0
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

function monthBounds(date: string) {
  const start = new Date(`${date.slice(0, 7)}-01T00:00:00`)
  const end = new Date(start)
  end.setMonth(end.getMonth() + 1)
  end.setDate(0)
  return {
    dateFrom: formatLocalDate(start),
    dateTo: formatLocalDate(end),
  }
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

async function loadInstallerWorkloadsInBatches(installers: string[]) {
  for (let index = 0; index < installers.length; index += installerWorkloadFetchConcurrency) {
    const batch = installers.slice(index, index + installerWorkloadFetchConcurrency)
    const workloads = await Promise.all(batch.map((installer) => fetchInstallerWorkload(installer)))
    workloads.forEach(cacheInstallerWorkload)
  }
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
    await loadInstallerWorkloadsInBatches(missing)
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

function installerDrilldownContext(installer: string): DataCenterDrilldownContext {
  const context: DataCenterDrilldownContext = { installer }
  if (installerWorkloadScope.value === 'all') return context
  const anchorDate = installerScopeAnchorDate()
  if (!anchorDate) return context
  if (installerWorkloadScope.value === 'day') {
    return { ...context, dateFrom: anchorDate, dateTo: anchorDate }
  }
  if (installerWorkloadScope.value === 'week') {
    return { ...context, dateFrom: anchorDate, dateTo: shiftDate(anchorDate, 6) }
  }
  return { ...context, ...monthBounds(anchorDate) }
}

function openDashboardDrilldown(kind: DataCenterDrilldownKind, context: DataCenterDrilldownContext = {}) {
  if (!isAdmin.value) return
  void router.push(buildDataCenterDrilldown(kind, context))
}

function openInstallerKpi(installer: string) {
  if (!isAdmin.value || !installer) return
  installerKpiInstaller.value = installer
  installerKpiDialogVisible.value = true
}

function openInstallerDataCenter() {
  openDashboardDrilldown(
    'installer_completed',
    installerDrilldownContext(installerKpiInstaller.value),
  )
}

async function loadBoard(options: { forceSummaryRefresh?: boolean } = {}) {
  loading.value = true
  errorMessage.value = ''
  try {
    const [summaryResult, statusResult, taskResult] = await Promise.all([
      fetchProjectSummary({ refresh: options.forceSummaryRefresh }),
      fetchTaskStatus(),
      fetchTasks({ summary: true }),
    ])
    summary.value = summaryResult.summary
    taskStatus.value = statusResult
    terminalTasks.value = taskResult
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '项目看板加载失败'
  } finally {
    loading.value = false
  }
}

async function refreshBoard() {
  await loadBoard({ forceSummaryRefresh: true })
}

async function exportMeterModuleWorkbook() {
  if (exportingMeterModule.value) return
  exportingMeterModule.value = true
  try {
    await downloadProjectMeterModuleWorkbook()
    ElMessage.success('表号模块号对应表已导出')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '表号模块号对应表导出失败')
  } finally {
    exportingMeterModule.value = false
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

const jobPercent = computed(() => {
  if (!activeJob.value) return 0
  if (activeJob.value.status === 'complete') return 100
  const progress = activeJob.value.progress || {}
  const percentValue = Number(progress.percent || progress.percentage || 0)
  return percentValue > 0 ? Math.min(99, Math.round(percentValue)) : 45
})

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

function handleExternalRefresh(event: MessageEvent) {
  if (event.data?.type !== 'module-manager:data-refresh') return
  void loadBoard()
}

onMounted(() => {
  void loadBoard()
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
        <el-button
          v-if="isAdmin"
          data-testid="export-meter-module"
          :icon="Download"
          :loading="exportingMeterModule"
          @click="exportMeterModuleWorkbook"
        >导出表号模块号</el-button>
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
      <template v-for="item in summaryCards" :key="item.label">
        <button
          v-if="isAdmin"
          class="metric metric-button"
          type="button"
          @click="openDashboardDrilldown(item.drilldown)"
        >
          <span class="metric-label">{{ item.label }}</span>
          <strong class="metric-value">{{ item.value }}</strong>
        </button>
        <article v-else class="metric">
          <span class="metric-label">{{ item.label }}</span>
          <strong class="metric-value">{{ item.value }}</strong>
        </article>
      </template>
    </div>

    <div class="board-grid">
      <section class="panel board-progress">
        <h3>项目进度</h3>
        <div class="board-progress-rows">
          <template v-for="item in progressRows" :key="item.label">
            <button
              v-if="isAdmin"
              class="board-progress-row board-progress-row-button"
              type="button"
              @click="openDashboardDrilldown(item.drilldown)"
            >
              <span>{{ item.label }}</span>
              <el-progress :percentage="item.percentage" />
              <b>{{ item.valueLabel }}</b>
            </button>
            <div v-else class="board-progress-row">
              <span>{{ item.label }}</span>
              <el-progress :percentage="item.percentage" />
              <b>{{ item.valueLabel }}</b>
            </div>
          </template>
        </div>
        <div class="risk-grid">
          <template v-for="item in riskCards" :key="item.label">
            <button
              v-if="isAdmin"
              class="risk-card risk-card-button"
              :class="item.tone"
              type="button"
              @click="openDashboardDrilldown(item.drilldown)"
            >
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </button>
            <article v-else class="risk-card" :class="item.tone">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </article>
          </template>
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
          </div>
        </div>
        <div v-if="filteredInstallerDistribution.length" v-loading="installerWorkloadLoading" class="installer-list">
          <template v-for="item in filteredInstallerDistribution" :key="item.installer">
            <button
              v-if="isAdmin"
              class="installer-row installer-row-button"
              type="button"
              @click="openInstallerKpi(item.installer)"
            >
              <span>{{ item.installer }}</span>
              <el-progress :percentage="Math.round(item.share * 100)" />
              <b>{{ item.groupCount }}</b>
            </button>
            <div v-else class="installer-row">
              <span>{{ item.installer }}</span>
              <el-progress :percentage="Math.round(item.share * 100)" />
              <b>{{ item.groupCount }}</b>
            </div>
          </template>
        </div>
        <el-empty v-else :description="installerWorkloadLoading ? '正在加载工作量' : '暂无安装人员统计'" />
      </section>
    </div>

    <section class="panel cockpit-panel">
      <div class="construction-panel-head">
        <div>
          <h3>终端流转态势</h3>
        </div>
      </div>
      <div class="cockpit-body">
        <div class="cockpit-flow" aria-label="终端流转阶段">
          <template v-for="item in cockpitFlow" :key="item.key">
            <button
              v-if="isAdmin"
              class="flow-node flow-node-button"
              type="button"
              @click="openDashboardDrilldown(item.drilldown)"
            >
              <div>
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </div>
              <div class="flow-track" aria-hidden="true">
                <i :style="{ width: `${flowPercent(item.value)}%` }" />
              </div>
            </button>
            <article v-else class="flow-node">
              <div>
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </div>
              <div class="flow-track" aria-hidden="true">
                <i :style="{ width: `${flowPercent(item.value)}%` }" />
              </div>
            </article>
          </template>
        </div>
      </div>
    </section>
    <InstallerKpiDialog
      v-if="isAdmin"
      v-model="installerKpiDialogVisible"
      :installer="installerKpiInstaller"
      :scope="installerKpiScope"
      @open-data-center="openInstallerDataCenter"
    />
  </section>
</template>

<style scoped>
.section-head-inline {
  align-items: baseline;
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.metric-button,
.board-progress-row-button,
.risk-card-button,
.installer-row-button,
.flow-node-button {
  color: inherit;
  font: inherit;
  text-align: left;
}

.metric-button,
.board-progress-row-button,
.risk-card-button,
.installer-row-button,
.flow-node-button {
  cursor: pointer;
}

.metric-button,
.board-progress-row-button,
.installer-row-button {
  width: 100%;
  border: 0;
  background: transparent;
}

.metric-button {
  appearance: none;
}

.metric-button:hover,
.board-progress-row-button:hover,
.risk-card-button:hover,
.installer-row-button:hover,
.flow-node-button:hover {
  border-color: rgba(10, 114, 216, 0.32);
  box-shadow: var(--v2-shadow-raised, 0 1px 2px rgba(15, 26, 36, 0.05));
  transform: translateY(-1px);
}

.metric-button:focus-visible,
.board-progress-row-button:focus-visible,
.risk-card-button:focus-visible,
.installer-row-button:focus-visible,
.flow-node-button:focus-visible {
  outline: 2px solid rgba(10, 114, 216, 0.46);
  outline-offset: 2px;
}

.board-progress-rows {
  display: grid;
  gap: 12px;
}

.native-board-page .risk-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.native-board-page .cockpit-body {
  grid-template-columns: minmax(0, 1fr);
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

.installer-row-button:hover {
  color: var(--v2-primary);
}

.risk-card-button {
  width: 100%;
  border: 1px solid var(--v2-border-soft, #dde5ee);
}

.flow-node-button {
  border: 1px solid rgba(10, 114, 216, 0.1);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(247, 250, 253, 0.92)),
    var(--v2-bg-surface);
}

@media (max-width: 1280px) {
  .native-board-page .board-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

}

@media (max-width: 720px) {
  .native-board-page .board-metrics {
    grid-template-columns: 1fr;
  }
}
</style>
