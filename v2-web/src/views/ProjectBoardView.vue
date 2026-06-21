<script setup lang="ts">
import { Refresh, Upload } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'

import {
  deleteUserAccount,
  exportExceptionMeters,
  exportTaskDetail,
  fetchUserAccounts,
  fetchProjectSummary,
  fetchSystemStatus,
  fetchTasks,
  importTotalCatalog,
  saveUserAccount,
} from '@/api/services'
import type { ImportJob, ProjectSummary, ReviewTask, UserAccount, UserRole } from '@/api/types'
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
  installerDistribution: [],
}

const loading = ref(false)
const importingTotal = ref(false)
const importingScan = ref(false)
const summary = ref<ProjectSummary>({ ...emptySummary })
const tasks = ref<ReviewTask[]>([])
const systemStatus = ref<Record<string, unknown> | null>(null)
const activeJob = ref<ImportJob | null>(null)
const errorMessage = ref('')
const auth = useAuthStore()
const accountUsers = ref<UserAccount[]>([])
const loadingAccounts = ref(false)
const savingAccount = ref(false)
const exportingException = ref(false)
const exportingTaskId = ref('')
const exportProgressText = ref('')
const exportProgressPercent = ref(0)
const exportScopeByTask = ref<Record<string, 'reviewed' | 'all'>>({})
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
const taskRows = computed(() =>
  [...tasks.value]
    .sort((left, right) => Number(right.uploadedCount || 0) - Number(left.uploadedCount || 0))
    .slice(0, 12),
)
const jobPercent = computed(() => {
  if (!activeJob.value) return 0
  if (activeJob.value.status === 'complete') return 100
  const progress = activeJob.value.progress || {}
  const percentValue = Number(progress.percent || progress.percentage || 0)
  return percentValue > 0 ? Math.min(99, Math.round(percentValue)) : 45
})
const systemRows = computed(() => {
  if (!systemStatus.value) return []
  const status = systemStatus.value as Record<string, unknown>
  const disk = (status.disk || {}) as Record<string, unknown>
  const data = (status.data || status.state_file || {}) as Record<string, unknown>
  const service = (status.service || {}) as Record<string, unknown>
  return [
    ['服务', String(service.status || status.status || 'unknown')],
    ['磁盘使用', String(disk.used_percent || disk.percent || 'unknown')],
    ['数据文件', String(data.local_state_size || data.state_size || data.size_bytes || 'unknown')],
    ['最近备份', String(status.latest_backup_at || status.latest_backup || 'unknown')],
  ]
})
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
  return `${Math.round(value * 100)}%`
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
  if (!accountForm.editing && !accountForm.password.trim()) {
    ElMessage.warning('新账号必须填写初始密码')
    return
  }
  savingAccount.value = true
  try {
    await saveUserAccount({
      username,
      password: accountForm.password.trim() || undefined,
      name: accountForm.name.trim() || username,
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
        <h3>安装人员资料组占比</h3>
        <div v-if="summary.installerDistribution.length" class="installer-list">
          <div v-for="item in summary.installerDistribution" :key="item.installer" class="installer-row">
            <span>{{ item.installer }}</span>
            <el-progress :percentage="Math.round(item.share * 100)" />
            <b>{{ item.groupCount }}</b>
          </div>
        </div>
        <el-empty v-else description="暂无安装人员统计" />
      </section>
    </div>

    <section class="panel task-list-panel">
      <div class="construction-panel-head">
        <div>
          <h3>终端任务进度</h3>
          <span>按上传量排序，显示前 12 个终端。</span>
        </div>
      </div>
      <el-table :data="taskRows" height="360" size="small">
        <el-table-column prop="terminal" label="终端" min-width="150" />
        <el-table-column prop="renovationCount" label="改造数" width="90" />
        <el-table-column prop="uploadedCount" label="已上传" width="90" />
        <el-table-column prop="unreviewedCount" label="未审阅" width="90" />
        <el-table-column prop="reviewedCount" label="已归档" width="90" />
        <el-table-column label="审阅率" width="110">
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
          <span>创建、停用和维护管理员、审阅员、施工员账号。</span>
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
          <el-input v-model="accountForm.name" placeholder="人员姓名" autocomplete="off" />
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
          <el-input v-model="accountForm.teamId" placeholder="例如 north-team-01" autocomplete="off" />
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
        <el-table v-loading="loadingAccounts" :data="accountUsers" height="300" size="small">
          <el-table-column prop="username" label="账号" min-width="140" />
          <el-table-column prop="name" label="姓名" min-width="120" />
          <el-table-column prop="teamId" label="团队" min-width="150" />
          <el-table-column label="角色" min-width="160">
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
          <el-table-column prop="lastLoginAt" label="最近登录" min-width="150" />
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
    </section>
  </section>
</template>

<style scoped>
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

.task-export-actions {
  align-items: center;
  display: flex;
  gap: 8px;
  min-width: 0;
}

.export-scope-select {
  width: 92px;
}

@media (max-width: 1280px) {
  .account-form-grid {
    grid-template-columns: repeat(3, minmax(160px, 1fr));
  }
}

@media (max-width: 720px) {
  .account-form-grid {
    grid-template-columns: 1fr;
  }

  .account-actions {
    justify-content: flex-end;
  }
}
</style>
