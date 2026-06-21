<script setup lang="ts">
import { Refresh, Upload } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'

import {
  deleteUserAccount,
  exportExceptionMeters,
  exportTaskDetail,
  fetchInstallerWorkload,
  fetchProjectSummary,
  fetchSystemStatus,
  fetchTasks,
  fetchUserAccounts,
  importTotalCatalog,
  saveUserAccount,
} from '@/api/services'
import type {
  ImportJob,
  InstallerWorkloadRow,
  ProjectSummary,
  ReviewTask,
  UserAccount,
  UserRole,
} from '@/api/types'
import { useAuthStore } from '@/stores/auth'

type SortOrder = 'ascending' | 'descending'
type TaskSortKey =
  | 'renovationCount'
  | 'uploadedCount'
  | 'uploadRate'
  | 'unreviewedCount'
  | 'reviewedCount'
  | 'reviewRate'

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
  installerDistribution: [],
}

const auth = useAuthStore()
const loading = ref(false)
const importingTotal = ref(false)
const importingScan = ref(false)
const summary = ref<ProjectSummary>({ ...emptySummary })
const tasks = ref<ReviewTask[]>([])
const systemStatus = ref<Record<string, unknown> | null>(null)
const activeJob = ref<ImportJob | null>(null)
const errorMessage = ref('')
const accountUsers = ref<UserAccount[]>([])
const loadingAccounts = ref(false)
const savingAccount = ref(false)
const exportingException = ref(false)
const exportingTaskId = ref('')
const exportProgressText = ref('')
const exportProgressPercent = ref(0)
const exportScopeByTask = ref<Record<string, 'reviewed' | 'all'>>({})
const taskSortKey = ref<TaskSortKey>('uploadedCount')
const taskSortOrder = ref<SortOrder>('descending')
const workloadDialogVisible = ref(false)
const workloadLoading = ref(false)
const workloadInstaller = ref('')
const workloadRows = ref<InstallerWorkloadRow[]>([])

const accountForm = reactive({
  username: '',
  name: '',
  password: '',
  teamId: auth.user?.teamId || 'default-team',
  role: 'reviewer' as UserRole,
  status: 'active',
  editing: false,
})

const isAdmin = computed(() => Boolean(auth.user?.roles?.includes('admin') || auth.user?.role === 'admin'))
const scannedRate = computed(() => (summary.value.groups ? summary.value.scannedGroups / summary.value.groups : 0))
const archiveRate = computed(() => (summary.value.groups ? summary.value.approvedGroups / summary.value.groups : 0))
const taskRows = computed(() => {
  const order = taskSortOrder.value === 'ascending' ? 1 : -1
  return [...tasks.value].sort((left, right) => {
    const delta = taskSortValue(left, taskSortKey.value) - taskSortValue(right, taskSortKey.value)
    if (delta !== 0) return delta * order
    return String(left.terminal || left.id).localeCompare(String(right.terminal || right.id), 'zh-Hans-CN')
  })
})
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
    }),
    { groupCount: 0, photoCount: 0, archivedCount: 0, exceptionCount: 0, unreviewedCount: 0 },
  ),
)

const accountRoles: Array<{ value: UserRole; label: string }> = [
  { value: 'admin', label: '管理员' },
  { value: 'reviewer', label: '审阅员' },
  { value: 'constructor', label: '施工员' },
]
const accountStatuses = [
  { value: 'active', label: '启用' },
  { value: 'disabled', label: '停用' },
]

function percent(value: number) {
  if (!Number.isFinite(value)) return '0%'
  return `${Math.round(value * 100)}%`
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

function taskSortValue(task: ReviewTask, key: TaskSortKey) {
  if (key === 'uploadRate') {
    return Number(task.uploadRate ?? ((task.renovationCount || 0) ? (task.uploadedCount || 0) / (task.renovationCount || 1) : 0))
  }
  if (key === 'reviewRate') return Number(task.reviewRate || 0)
  return Number(task[key] || 0)
}

function handleTaskSortChange(payload: { prop?: string; order?: SortOrder | null }) {
  const prop = payload.prop as TaskSortKey | undefined
  if (prop) taskSortKey.value = prop
  taskSortOrder.value = payload.order || 'descending'
}

function roleLabel(role: string) {
  return accountRoles.find((item) => item.value === role)?.label || role
}

function rolesLabel(user: UserAccount) {
  return (user.roles || []).map((role) => roleLabel(role)).join(' / ') || '审阅员'
}

function primaryRole(user: UserAccount): UserRole {
  const role = user.roles.find((item) => accountRoles.some((option) => option.value === item))
  return role || 'reviewer'
}

function shortDevice(value = '') {
  const trimmed = value.trim()
  if (!trimmed) return '-'
  return trimmed.length > 42 ? `${trimmed.slice(0, 42)}...` : trimmed
}

function resetAccountForm() {
  accountForm.username = ''
  accountForm.name = ''
  accountForm.password = ''
  accountForm.teamId = auth.user?.teamId || 'default-team'
  accountForm.role = 'reviewer'
  accountForm.status = 'active'
  accountForm.editing = false
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

function editAccount(user: UserAccount) {
  accountForm.username = user.username
  accountForm.name = user.name || user.username
  accountForm.password = ''
  accountForm.teamId = user.teamId || auth.user?.teamId || 'default-team'
  accountForm.role = primaryRole(user)
  accountForm.status = user.status || 'active'
  accountForm.editing = true
}

async function submitAccount() {
  const username = accountForm.username.trim()
  if (!username) {
    ElMessage.warning('请填写账号')
    return
  }
  if (!accountForm.name.trim()) {
    ElMessage.warning('请填写姓名，姓名将作为安装人员和 KPI 的统一口径')
    return
  }
  if (!accountForm.editing && !accountForm.password.trim()) {
    ElMessage.warning('新账号必须填写初始密码')
    return
  }
  savingAccount.value = true
  try {
    await saveUserAccount({
      username,
      password: accountForm.password.trim() || undefined,
      name: accountForm.name.trim(),
      roles: [accountForm.role],
      teamId: accountForm.teamId.trim() || auth.user?.teamId || 'default-team',
      status: accountForm.status,
    })
    ElMessage.success('账号已保存')
    resetAccountForm()
    await loadAccounts()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '账号保存失败')
  } finally {
    savingAccount.value = false
  }
}

async function removeAccount(user: UserAccount) {
  if (user.username === auth.user?.username) {
    ElMessage.warning('不能删除当前登录账号')
    return
  }
  try {
    await ElMessageBox.confirm(`确认删除账号 ${user.username}？删除后该账号将无法登录。`, '删除账号', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteUserAccount(user.username)
    ElMessage.success('账号已删除')
    await loadAccounts()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '账号删除失败')
  }
}

async function loadBoard() {
  loading.value = true
  errorMessage.value = ''
  try {
    const [summaryResult, taskResult] = await Promise.all([fetchProjectSummary(), fetchTasks()])
    summary.value = summaryResult.summary
    tasks.value = taskResult
    for (const task of taskResult) {
      if (!exportScopeByTask.value[task.id]) exportScopeByTask.value[task.id] = 'reviewed'
    }
    try {
      systemStatus.value = await fetchSystemStatus()
    } catch {
      systemStatus.value = null
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '项目看板加载失败'
  } finally {
    loading.value = false
  }
}

async function exportTaskDetailRow(task: ReviewTask) {
  exportingTaskId.value = `detail-${task.id}`
  try {
    await exportTaskDetail(task.id)
    ElMessage.success('任务明细已导出')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '任务明细导出失败')
  } finally {
    exportingTaskId.value = ''
  }
}

async function exportTerminalPackage(task: ReviewTask) {
  exportingTaskId.value = `terminal-${task.id}`
  exportProgressText.value = '准备导出终端包'
  exportProgressPercent.value = 2
  try {
    window.postMessage(
      {
        type: 'module-manager:start-terminal-export',
        scope: {
          taskId: task.id,
          terminal: task.terminal || '',
          reviewScope: exportScopeByTask.value[task.id] || 'reviewed',
        },
      },
      window.location.origin,
    )
    exportProgressText.value = '终端包导出已提交到全局任务栏'
    exportProgressPercent.value = 5
    ElMessage.success('终端包导出已提交，可切换页面继续等待')
  } finally {
    window.setTimeout(() => {
      exportingTaskId.value = ''
      exportProgressText.value = ''
      exportProgressPercent.value = 0
    }, 900)
  }
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

async function openInstallerWorkload(installer: string) {
  workloadInstaller.value = installer
  workloadRows.value = []
  workloadDialogVisible.value = true
  workloadLoading.value = true
  try {
    const workload = await fetchInstallerWorkload(installer)
    workloadRows.value = workload.items
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '安装人员工作量加载失败')
  } finally {
    workloadLoading.value = false
  }
}

function exportInstallerWorkloadCsv() {
  const rows = [
    ['安装人员', '日期', '资料组数', '照片数', '已归档', '异常', '未审阅'],
    ...workloadRows.value.map((item) => [
      workloadInstaller.value,
      item.date,
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

function handleExternalRefresh(event: MessageEvent) {
  if (event.data?.type !== 'module-manager:data-refresh') return
  void loadBoard()
  if (isAdmin.value) void loadAccounts()
}

onMounted(() => {
  void loadBoard()
  if (isAdmin.value) void loadAccounts()
  window.addEventListener('message', handleExternalRefresh)
})
watch(isAdmin, (value) => {
  if (value && !accountUsers.value.length) void loadAccounts()
})
onUnmounted(() => {
  window.removeEventListener('message', handleExternalRefresh)
})
</script>

<template>
  <section class="native-board-page">
    <div class="board-hero panel">
      <div>
        <p class="eyebrow">项目看板</p>
        <h2>总清单、终端任务、审阅进度</h2>
        <p class="muted">生产关键入口：导入、进度、风险、系统状态。</p>
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
        <el-button :icon="Refresh" :loading="loading" @click="loadBoard">刷新</el-button>
      </div>
    </div>

    <el-alert v-if="errorMessage" class="claim-alert" type="error" :closable="false" :title="errorMessage" />

    <div v-if="activeJob" class="panel import-progress">
      <strong>扫码导入任务：{{ activeJob.status }}</strong>
      <span class="muted">{{ activeJob.error || JSON.stringify(activeJob.progress || {}) }}</span>
      <el-progress :percentage="jobPercent" />
    </div>

    <div v-if="exportingTaskId" class="panel import-progress">
      <strong>导出任务</strong>
      <span class="muted">{{ exportProgressText || '正在处理导出任务' }}</span>
      <el-progress :percentage="exportProgressPercent" />
    </div>

    <div v-loading="loading" class="board-metrics">
      <article class="metric">
        <span class="metric-label">总清单</span>
        <strong class="metric-value">{{ summary.totalCatalogRows }}</strong>
      </article>
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
      <article class="metric">
        <span class="metric-label">异常组</span>
        <strong class="metric-value">{{ summary.exceptionGroups }}</strong>
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
          <article class="risk-card bad">
            <span>扫码未匹配</span>
            <strong>{{ summary.scanUnmatched }}</strong>
          </article>
          <article class="risk-card bad">
            <span>异常资料组</span>
            <strong>{{ summary.exceptionGroups }}</strong>
          </article>
          <article class="risk-card warn">
            <span>未施工未扫码</span>
            <strong>{{ summary.unconstructedGroups }}</strong>
          </article>
          <article class="risk-card warn">
            <span>缺照片</span>
            <strong>{{ summary.incompleteGroups }}</strong>
          </article>
        </div>
      </section>

      <section class="panel board-progress">
        <div class="section-head-inline">
          <h3>安装人员资料组占比</h3>
          <span class="muted">点击姓名查看每日工作量并导出 KPI</span>
        </div>
        <div v-if="summary.installerDistribution.length" class="installer-list">
          <button
            v-for="item in summary.installerDistribution"
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
        <el-empty v-else description="暂无安装人员统计" />
      </section>
    </div>

    <section class="panel task-list-panel">
      <div class="construction-panel-head">
        <div>
          <h3>终端任务进度</h3>
          <span>全量显示 {{ taskRows.length }} 个终端。点击表头可按上传率、审阅率、已归档、未审阅等字段升序/降序。</span>
        </div>
      </div>
      <el-table
        :data="taskRows"
        height="520"
        row-key="id"
        size="small"
        :default-sort="{ prop: taskSortKey, order: taskSortOrder }"
        @sort-change="handleTaskSortChange"
      >
        <el-table-column prop="terminal" label="终端" min-width="150" fixed="left" />
        <el-table-column prop="renovationCount" label="档案数" width="92" sortable="custom" />
        <el-table-column prop="uploadedCount" label="已上传" width="92" sortable="custom" />
        <el-table-column prop="uploadRate" label="上传率" width="96" sortable="custom">
          <template #default="{ row }">{{ percent(row.uploadRate || 0) }}</template>
        </el-table-column>
        <el-table-column prop="unreviewedCount" label="未审阅" width="96" sortable="custom" />
        <el-table-column prop="reviewedCount" label="已归档" width="96" sortable="custom" />
        <el-table-column prop="reviewRate" label="审阅率" width="96" sortable="custom">
          <template #default="{ row }">{{ percent(row.reviewRate || 0) }}</template>
        </el-table-column>
        <el-table-column prop="claimedBy" label="审阅员" min-width="120" />
        <el-table-column v-if="isAdmin" label="导出" min-width="330" fixed="right">
          <template #default="{ row }">
            <div class="task-export-actions">
              <el-button
                size="small"
                :loading="exportingTaskId === `detail-${row.id}`"
                @click="exportTaskDetailRow(row)"
              >
                导出明细
              </el-button>
              <el-select v-model="exportScopeByTask[row.id]" class="export-scope-select" size="small">
                <el-option label="已归档" value="reviewed" />
                <el-option label="全部" value="all" />
              </el-select>
              <el-button
                size="small"
                type="primary"
                :loading="exportingTaskId === `terminal-${row.id}`"
                @click="exportTerminalPackage(row)"
              >
                导出终端包
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section v-if="isAdmin" class="panel account-admin-panel">
      <div class="construction-panel-head">
        <div>
          <h3>账号管理</h3>
          <span>创建、停用和维护账号。姓名作为安装人员与 KPI 的唯一人员口径。</span>
        </div>
        <el-button :loading="loadingAccounts" size="small" @click="loadAccounts">刷新账号</el-button>
      </div>

      <div class="account-form-grid">
        <label class="account-field">
          <span>账号</span>
          <el-input
            v-model="accountForm.username"
            :disabled="accountForm.editing"
            placeholder="例如 reviewer-a"
            autocomplete="off"
          />
        </label>
        <label class="account-field">
          <span>姓名</span>
          <el-input v-model="accountForm.name" placeholder="人员姓名，作为安装与考核唯一标准" autocomplete="off" />
        </label>
        <label class="account-field">
          <span>密码</span>
          <el-input
            v-model="accountForm.password"
            type="password"
            show-password
            placeholder="新账号必填，更新可留空"
            autocomplete="new-password"
          />
        </label>
        <label class="account-field">
          <span>团队</span>
          <el-input v-model="accountForm.teamId" placeholder="例如 default-team" autocomplete="off" />
        </label>
        <label class="account-field">
          <span>角色</span>
          <el-select v-model="accountForm.role" placeholder="选择角色">
            <el-option v-for="role in accountRoles" :key="role.value" :label="role.label" :value="role.value" />
          </el-select>
        </label>
        <label class="account-field">
          <span>状态</span>
          <el-select v-model="accountForm.status" placeholder="选择状态">
            <el-option
              v-for="status in accountStatuses"
              :key="status.value"
              :label="status.label"
              :value="status.value"
            />
          </el-select>
        </label>
        <div class="account-actions">
          <el-button type="primary" :loading="savingAccount" @click="submitAccount">保存账号</el-button>
          <el-button @click="resetAccountForm">清空</el-button>
        </div>
      </div>

      <div class="account-table-wrap">
        <el-table v-loading="loadingAccounts" :data="accountUsers" height="340" size="small">
          <el-table-column prop="username" label="账号" min-width="130" />
          <el-table-column prop="name" label="姓名" min-width="120" />
          <el-table-column prop="teamId" label="团队" min-width="140" />
          <el-table-column label="角色" min-width="150">
            <template #default="{ row }">
              {{ rolesLabel(row) }}
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.status === 'disabled' ? 'danger' : 'success'" effect="plain" round>
                {{ row.status === 'disabled' ? '停用' : '启用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="lastLoginAt" label="最近登录" min-width="180" />
          <el-table-column prop="lastLoginIp" label="登录 IP" min-width="130" />
          <el-table-column label="登录设备" min-width="220">
            <template #default="{ row }">
              <el-tooltip :content="row.lastLoginDevice || '-'" placement="top" :disabled="!row.lastLoginDevice">
                <span class="device-cell">{{ shortDevice(row.lastLoginDevice) }}</span>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="editAccount(row)">编辑</el-button>
              <el-button size="small" type="danger" plain @click="removeAccount(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
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

    <el-dialog v-model="workloadDialogVisible" :title="`${workloadInstaller} 每日工作量`" width="760px">
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
      </div>
      <el-table v-loading="workloadLoading" :data="workloadRows" height="360" size="small">
        <el-table-column prop="date" label="日期" min-width="120" />
        <el-table-column prop="groupCount" label="资料组" width="92" />
        <el-table-column prop="photoCount" label="照片" width="92" />
        <el-table-column prop="archivedCount" label="已归档" width="92" />
        <el-table-column prop="exceptionCount" label="异常" width="92" />
        <el-table-column prop="unreviewedCount" label="未审阅" width="92" />
      </el-table>
      <template #footer>
        <el-button @click="workloadDialogVisible = false">关闭</el-button>
        <el-button type="primary" :disabled="!workloadRows.length" @click="exportInstallerWorkloadCsv">
          导出 KPI CSV
        </el-button>
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

.account-admin-panel {
  display: grid;
  gap: 0;
}

.account-form-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(128px, 1fr)) auto;
  gap: 10px;
  padding: 12px;
  border-bottom: 1px solid var(--v2-border-soft, #dde5ee);
}

.account-field {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.account-field > span {
  color: var(--v2-text-muted, #64748b);
  font-size: 12px;
  font-weight: 700;
}

.account-actions {
  align-self: end;
  display: flex;
  gap: 8px;
  white-space: nowrap;
}

.account-table-wrap {
  padding: 12px;
}

.device-cell {
  display: inline-block;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.workload-summary article {
  display: grid;
  gap: 4px;
  padding: 10px;
  border: 1px solid var(--v2-border-soft, #dde5ee);
  border-radius: 8px;
  background: var(--v2-bg-soft, #f8fafc);
}

.workload-summary span {
  color: var(--v2-text-muted, #64748b);
  font-size: 12px;
}

.workload-summary strong {
  color: var(--v2-text-strong, #0f172a);
  font-size: 22px;
}

@media (max-width: 1280px) {
  .account-form-grid {
    grid-template-columns: repeat(3, minmax(160px, 1fr));
  }
}

@media (max-width: 720px) {
  .account-form-grid,
  .workload-summary {
    grid-template-columns: 1fr;
  }

  .account-actions {
    justify-content: flex-end;
  }
}
</style>
