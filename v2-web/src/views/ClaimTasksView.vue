<script setup lang="ts">
import { MoreFilled, Refresh, Search, Unlock } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  assignConstructionTask,
  currentActor,
  currentTeamId,
  exportTaskDetail,
  fetchTaskStatus,
  fetchTasks,
  fetchUserAccounts,
  claimTask as claimTaskApi,
  releaseAllClaimedTasks,
  releaseTask as releaseTaskApi,
} from '@/api/services'
import type { ReviewTask, TaskStatusSummary, UserAccount } from '@/api/types'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const releasingAll = ref(false)
const assigningTaskId = ref('')
const assignmentDialogVisible = ref(false)
const assignmentTargetTask = ref<ReviewTask | null>(null)
const assignmentConstructor = ref('')
const assignmentSubmitting = ref(false)
const tasks = ref<ReviewTask[]>([])
const accountUsers = ref<UserAccount[]>([])
const loadingAccounts = ref(false)
const errorMessage = ref('')
const searchQuery = ref('')
const exportingTaskId = ref('')
const exportProgressText = ref('')
const exportProgressPercent = ref(0)
const exportScopeByTask = ref<Record<string, 'reviewed' | 'all'>>({})
const taskStatus = ref<TaskStatusSummary | null>(null)
const taskStatusVersion = ref('')
const CLAIM_TASK_CACHE_PREFIX = 'module-manager:claim-tasks:v3'
const TASK_STATUS_REFRESH_INTERVAL_MS = 15 * 60 * 1000
let refreshInterval = 0
let refreshTimer = 0

type TaskMoreAction = 'scope-reviewed' | 'scope-all' | 'export-terminal' | 'export-detail' | 'assign' | 'release'
type TaskMoreCommand = {
  action: TaskMoreAction
  taskId: string
}

const actor = computed(() => auth.user?.username || auth.user?.id || currentActor())
const isAdmin = computed(() => auth.user?.role === 'admin' || auth.user?.roles?.includes('admin'))
const baseVisibleTasks = computed(() =>
  isAdmin.value
    ? [...tasks.value]
    : tasks.value.filter((task) => task.hasScanInfo && Number(task.unreviewedCount || 0) > 0),
)
const visibleTasks = computed(() => {
  const query = normalizeSearch(searchQuery.value)
  const items = query ? baseVisibleTasks.value.filter((task) => taskMatchesSearch(task, query)) : [...baseVisibleTasks.value]
  return items.sort((left, right) => {
    if (!isAdmin.value) {
      const myDiff = Number(right.claimedBy === actor.value) - Number(left.claimedBy === actor.value)
      if (myDiff) return myDiff
      const unreviewedDiff = Number(right.unreviewedCount || 0) - Number(left.unreviewedCount || 0)
      if (unreviewedDiff) return unreviewedDiff
    }
    const uploadedDiff = (right.uploadedCount || 0) - (left.uploadedCount || 0)
    if (isAdmin.value && uploadedDiff) return uploadedDiff
    return String(left.terminal || left.id).localeCompare(String(right.terminal || right.id), 'zh-Hans-CN')
  })
})

const claimedTasks = computed(() => tasks.value.filter((task) => task.claimedBy))
const myTasks = computed(() => tasks.value.filter((task) => task.claimedBy === actor.value))
const userByUsername = computed(() => {
  const map = new Map<string, UserAccount>()
  for (const user of accountUsers.value) {
    if (user.username) map.set(user.username, user)
  }
  return map
})
const constructorOptions = computed(() =>
  accountUsers.value.filter((user) => (user.roles || []).includes('constructor')),
)
const assignmentDialogTitle = computed(() => {
  const task = assignmentTargetTask.value
  if (!task) return '指派施工终端'
  return task.assignedConstructor || task.constructionClaimedBy ? '改派施工终端' : '指派施工终端'
})
const assignmentTargetLabel = computed(() => {
  const task = assignmentTargetTask.value
  if (!task) return ''
  return `终端 ${task.terminal || task.id}`
})
const claimedSummary = computed(() => {
  const base = claimedTasks.value
  const renovation = base.reduce((sum, task) => sum + Number(task.renovationCount || task.totalGroups || 0), 0)
  const uploaded = base.reduce((sum, task) => sum + Number(task.uploadedCount || 0), 0)
  const reviewed = base.reduce((sum, task) => sum + Number(task.reviewedCount || task.completedGroups || 0), 0)
  const unreviewed = base.reduce((sum, task) => sum + Number(task.unreviewedCount || 0), 0)
  return {
    claimed: base.length,
    mine: myTasks.value.length,
    renovation,
    uploaded,
    reviewed,
    unreviewed,
    reviewRate: renovation ? reviewed / renovation : 0,
  }
})

function percent(value: number | undefined) {
  return `${Math.round((Number(value) || 0) * 100)}%`
}

function countValue(value: number | undefined) {
  return Number(value || 0)
}

function userDisplayName(username = '') {
  const value = String(username || '').trim()
  if (!value) return ''
  const user = userByUsername.value.get(value)
  return user?.name?.trim() || value
}

function userDisplayLabel(username = '') {
  const value = String(username || '').trim()
  if (!value) return '未指派'
  const name = userDisplayName(value)
  return name && name !== value ? `${name}（${value}）` : value
}

function accountOptionLabel(user: UserAccount) {
  const name = user.name?.trim()
  return name && name !== user.username ? `${name}（${user.username}）` : user.username
}

function taskConstructorAccount(task: ReviewTask) {
  return task.assignedConstructor || task.constructionClaimedBy || ''
}

function taskConstructorName(task: ReviewTask) {
  return (
    task.assignedConstructorName ||
    task.constructionClaimedByName ||
    userDisplayName(taskConstructorAccount(task)) ||
    '未指派'
  )
}

function taskConstructorAccountHint(task: ReviewTask) {
  const account = taskConstructorAccount(task)
  const name = taskConstructorName(task)
  return account && account !== name ? `账号 ${account}` : ''
}

function taskReviewerLabel(task: ReviewTask) {
  if (!task.claimedBy) return '审阅：尚未领取'
  const name = task.claimedByName || userDisplayName(task.claimedBy)
  return name && name !== task.claimedBy ? `审阅：${name}（${task.claimedBy}）` : `审阅：${task.claimedBy}`
}

function normalizeSearch(value: string) {
  return String(value || '')
    .normalize('NFKC')
    .toLowerCase()
    .replace(/\s+/g, '')
}

function taskMatchesSearch(task: ReviewTask, query: string) {
  const haystack = normalizeSearch(
    [
      task.terminal,
      task.address,
      task.addressSearchText,
      task.name,
      task.id,
    ].filter(Boolean).join(' '),
  )
  return haystack.includes(query)
}

function taskReviewPercent(task: ReviewTask) {
  return Math.round((Number(task.reviewRate) || 0) * 100)
}

function statusLabel(task: ReviewTask) {
  if (task.claimedBy === actor.value) return '我已领取'
  if (task.claimedBy) return '已被领取'
  if (!task.hasScanInfo) return '无扫码'
  if (!task.unreviewedCount) return '已审完'
  return '可领取'
}

function statusType(task: ReviewTask) {
  if (task.claimedBy === actor.value) return 'success'
  if (task.claimedBy) return 'warning'
  if (!task.hasScanInfo) return 'info'
  return 'primary'
}

type LoadTasksOptions = {
  force?: boolean
  silent?: boolean
}

function claimTasksCacheKey() {
  return `${CLAIM_TASK_CACHE_PREFIX}:${currentTeamId()}:${actor.value}:${isAdmin.value ? 'admin' : 'reviewer'}`
}

function primeExportScopes(items: ReviewTask[]) {
  for (const task of items) {
    if (!exportScopeByTask.value[task.id]) exportScopeByTask.value[task.id] = 'reviewed'
  }
}

function restoreCachedTasks() {
  if (typeof window === 'undefined') return
  try {
    const cached = JSON.parse(sessionStorage.getItem(claimTasksCacheKey()) || 'null') as
      | { version?: string; tasks?: ReviewTask[] }
      | null
    if (!cached?.tasks?.length) return
    tasks.value = cached.tasks
    taskStatusVersion.value = cached.version || ''
    primeExportScopes(cached.tasks)
  } catch {
    sessionStorage.removeItem(claimTasksCacheKey())
  }
}

function rememberCachedTasks(version = taskStatusVersion.value) {
  if (typeof window === 'undefined') return
  try {
    sessionStorage.setItem(
      claimTasksCacheKey(),
      JSON.stringify({
        version,
        cachedAt: Date.now(),
        tasks: tasks.value,
      }),
    )
  } catch {
    // Storage quota should not block the task list.
  }
}

async function loadTasks(options: LoadTasksOptions = {}) {
  const showLoading = !options.silent
  if (showLoading) loading.value = true
  errorMessage.value = ''
  try {
    const status = await fetchTaskStatus()
    taskStatus.value = status
    if (!options.force && tasks.value.length && status.version && status.version === taskStatusVersion.value) {
      return
    }
    const result = await fetchTasks()
    tasks.value = result
    taskStatusVersion.value = status.version
    primeExportScopes(result)
    rememberCachedTasks(status.version)
  } catch (error) {
    if (!tasks.value.length || options.force) {
      try {
        const result = await fetchTasks()
        tasks.value = result
        taskStatusVersion.value = ''
        primeExportScopes(result)
        rememberCachedTasks('')
        return
      } catch (fallbackError) {
        errorMessage.value = fallbackError instanceof Error ? fallbackError.message : '任务加载失败'
        return
      }
    }
    errorMessage.value = error instanceof Error ? error.message : '任务状态加载失败'
  } finally {
    if (showLoading) loading.value = false
  }
}

function refreshTasks() {
  void loadTasks({ force: true })
}

async function loadAccounts() {
  if (!isAdmin.value || loadingAccounts.value) return
  loadingAccounts.value = true
  try {
    accountUsers.value = await fetchUserAccounts()
  } catch (error) {
    ElMessage.warning(error instanceof Error ? error.message : '施工员账号列表加载失败，可稍后重试')
  } finally {
    loadingAccounts.value = false
  }
}

function scheduleRefresh() {
  if (refreshTimer) window.clearTimeout(refreshTimer)
  refreshTimer = window.setTimeout(() => {
    refreshTimer = 0
    void loadTasks({ silent: true })
  }, 180)
}

function handleExternalRefresh(event: MessageEvent) {
  if (event.data?.type === 'module-manager:data-refresh') {
    scheduleRefresh()
  }
}

async function claim(task: ReviewTask) {
  errorMessage.value = ''
  try {
    const updated = await claimTaskApi(task.id)
    tasks.value = tasks.value.map((item) => (item.id === task.id ? updated : item))
    taskStatusVersion.value = ''
    rememberCachedTasks('')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '领取失败'
  }
}

async function release(task: ReviewTask) {
  errorMessage.value = ''
  try {
    const updated = await releaseTaskApi(task.id)
    tasks.value = tasks.value.map((item) => (item.id === task.id ? updated : item))
    taskStatusVersion.value = ''
    rememberCachedTasks('')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '释放失败'
  }
}

async function releaseAll() {
  if (!isAdmin.value) return
  releasingAll.value = true
  errorMessage.value = ''
  try {
    const result = await releaseAllClaimedTasks()
    ElMessage.success(`已收回 ${result.released || 0} 个任务`)
    await loadTasks({ force: true })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '收回全部失败'
  } finally {
    releasingAll.value = false
  }
}

async function openAssignDialog(task: ReviewTask) {
  if (!isAdmin.value) return
  assignmentTargetTask.value = task
  assignmentConstructor.value = taskConstructorAccount(task)
  assignmentDialogVisible.value = true
  if (!accountUsers.value.length) await loadAccounts()
}

async function submitAssignment() {
  const task = assignmentTargetTask.value
  if (!task || !isAdmin.value) return
  const constructor = String(assignmentConstructor.value || '').trim()
  if (!constructor) {
    ElMessage.warning('请选择施工员，或输入施工员账号')
    return
  }
  assignmentSubmitting.value = true
  assigningTaskId.value = task.id
  errorMessage.value = ''
  try {
    const updated = await assignConstructionTask(task.id, constructor)
    tasks.value = tasks.value.map((item) => (item.id === task.id ? updated : item))
    taskStatusVersion.value = ''
    rememberCachedTasks('')
    assignmentDialogVisible.value = false
    ElMessage.success(`已指派给 ${userDisplayLabel(constructor)}`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '指派施工失败'
  } finally {
    assignmentSubmitting.value = false
    assigningTaskId.value = ''
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

async function handleTaskMoreCommand(command: string | number | TaskMoreCommand) {
  if (typeof command !== 'object' || command === null) return
  const task = tasks.value.find((item) => item.id === command.taskId)
  if (!task) return
  if (command.action === 'scope-reviewed') {
    exportScopeByTask.value[task.id] = 'reviewed'
    ElMessage.success('导出范围已切换为已归档')
    return
  }
  if (command.action === 'scope-all') {
    exportScopeByTask.value[task.id] = 'all'
    ElMessage.success('导出范围已切换为全部')
    return
  }
  if (command.action === 'export-terminal') {
    await exportTerminalPackage(task)
    return
  }
  if (command.action === 'export-detail') {
    await exportTaskDetailRow(task)
    return
  }
  if (command.action === 'assign') {
    await openAssignDialog(task)
    return
  }
  if (command.action === 'release') {
    await release(task)
  }
}

function openReview(task: ReviewTask) {
  if (task.claimedBy && task.claimedBy !== actor.value && !isAdmin.value) return
  void router.push('/task-hall')
}

onMounted(() => {
  restoreCachedTasks()
  void loadTasks({ silent: tasks.value.length > 0 })
  window.addEventListener('message', handleExternalRefresh)
  refreshInterval = window.setInterval(scheduleRefresh, TASK_STATUS_REFRESH_INTERVAL_MS)
})

onUnmounted(() => {
  window.removeEventListener('message', handleExternalRefresh)
  if (refreshInterval) window.clearInterval(refreshInterval)
  if (refreshTimer) window.clearTimeout(refreshTimer)
  refreshInterval = 0
  refreshTimer = 0
})
</script>

<template>
  <section class="native-claim-page">
    <div class="claim-hero panel">
      <div>
        <p class="eyebrow">任务领取</p>
        <h2>按终端领取审阅任务</h2>
        <p class="muted">审阅员只看到仍有未审阅照片的终端；管理员可查看全部终端并指派施工。</p>
      </div>
      <div class="claim-actions">
        <ElButton :icon="Refresh" :loading="loading" @click="refreshTasks">刷新</ElButton>
        <ElButton v-if="isAdmin" :icon="Unlock" type="warning" plain :loading="releasingAll" @click="releaseAll">
          收回全部
        </ElButton>
      </div>
    </div>

    <ElAlert v-if="errorMessage" class="claim-alert" type="error" :closable="false" :title="errorMessage" />

    <div v-if="exportingTaskId" class="panel import-progress">
      <strong>导出任务</strong>
      <span class="muted">{{ exportProgressText || '正在处理导出任务' }}</span>
      <ElProgress :percentage="exportProgressPercent" />
    </div>

    <div class="claim-summary">
      <article class="metric">
        <span class="metric-label">已领取任务</span>
        <strong class="metric-value">{{ claimedSummary.claimed }}</strong>
      </article>
      <article class="metric">
        <span class="metric-label">我的任务</span>
        <strong class="metric-value">{{ claimedSummary.mine }}</strong>
      </article>
      <article class="metric">
        <span class="metric-label">改造总数</span>
        <strong class="metric-value">{{ claimedSummary.renovation }}</strong>
      </article>
      <article class="metric">
        <span class="metric-label">未审阅数</span>
        <strong class="metric-value">{{ claimedSummary.unreviewed }}</strong>
      </article>
      <article class="metric progress-card">
        <div>
          <span class="metric-label">审阅进度</span>
          <strong class="metric-value">{{ percent(claimedSummary.reviewRate) }}</strong>
        </div>
        <ElProgress :percentage="Math.round(claimedSummary.reviewRate * 100)" :stroke-width="10" :show-text="false" />
      </article>
    </div>

    <section class="panel task-list-panel">
      <div class="panel-heading">
        <div>
          <h3>终端任务</h3>
          <p class="muted">
            共 {{ visibleTasks.length }} 个{{ isAdmin ? '可见终端' : '待审终端' }} / {{ tasks.length }} 个总终端
          </p>
        </div>
        <ElInput
          v-model="searchQuery"
          class="claim-task-search"
          clearable
          :prefix-icon="Search"
          placeholder="搜索终端号或地址"
          aria-label="搜索终端号或地址"
        />
      </div>

      <ElSkeleton v-if="loading && !tasks.length" :rows="6" animated />
      <ElEmpty
        v-else-if="!visibleTasks.length"
        :description="searchQuery ? '没有匹配的终端或地址' : '暂无可领取终端任务'"
      />
      <div v-else class="claim-task-grid">
        <article
          v-for="task in visibleTasks"
          :key="task.id"
          class="claim-task-card"
          :class="{
            empty: !task.hasScanInfo,
            done: !task.unreviewedCount && task.hasScanInfo,
            mine: task.claimedBy === actor,
            claimed: !!task.claimedBy,
          }"
        >
          <div class="task-card-top">
            <div class="task-title-block">
              <strong>终端 {{ task.terminal || task.id }}</strong>
              <span>{{ taskReviewerLabel(task) }}</span>
              <span v-if="task.address" class="task-address-line">{{ task.address }}</span>
            </div>
            <ElTag :type="statusType(task)" effect="plain">{{ statusLabel(task) }}</ElTag>
          </div>

          <div class="task-primary-line">
            <div>
              <span>未审阅</span>
              <b>{{ countValue(task.unreviewedCount) }}</b>
            </div>
            <div>
              <span>审阅进度</span>
              <b>{{ taskReviewPercent(task) }}%</b>
            </div>
          </div>

          <div class="task-card-metrics">
            <div><span>改造数</span><b>{{ task.renovationCount || task.totalGroups || 0 }}</b></div>
            <div><span>已上传</span><b>{{ task.uploadedCount || 0 }}</b></div>
            <div><span>已归档</span><b>{{ task.reviewedCount || task.completedGroups || 0 }}</b></div>
          </div>

          <ElProgress :percentage="taskReviewPercent(task)" :stroke-width="8" :show-text="false" />

          <div v-if="isAdmin" class="task-construction-line">
            <span>
              施工：<strong>{{ taskConstructorName(task) }}</strong>
              <small v-if="taskConstructorAccountHint(task)">{{ taskConstructorAccountHint(task) }}</small>
            </span>
            <span v-if="task.constructionExceptionCount">异常 {{ task.constructionExceptionCount }}</span>
          </div>

          <div class="task-card-actions" @click.stop>
            <ElButton
              size="small"
              type="primary"
              :disabled="!task.canClaim || (!!task.claimedBy && task.claimedBy !== actor && !isAdmin)"
              @click="claim(task)"
            >
              {{ task.claimedBy === actor ? '继续持有' : '领取' }}
            </ElButton>
            <ElButton
              size="small"
              type="primary"
              :disabled="!!task.claimedBy && task.claimedBy !== actor && !isAdmin"
              @click="openReview(task)"
            >
              进入审阅
            </ElButton>
            <ElDropdown
              v-if="isAdmin"
              trigger="click"
              placement="bottom-end"
              @command="handleTaskMoreCommand"
            >
              <ElButton size="small" plain :icon="MoreFilled" :loading="assigningTaskId === task.id || exportingTaskId.endsWith(`-${task.id}`)">
                更多
              </ElButton>
              <template #dropdown>
                <ElDropdownMenu>
                  <ElDropdownItem :command="{ action: 'export-terminal', taskId: task.id }">
                    导出终端包（{{ exportScopeByTask[task.id] === 'all' ? '全部' : '已归档' }}）
                  </ElDropdownItem>
                  <ElDropdownItem :command="{ action: 'export-detail', taskId: task.id }">导出明细</ElDropdownItem>
                  <ElDropdownItem divided :command="{ action: 'assign', taskId: task.id }">
                    {{ task.assignedConstructor || task.constructionClaimedBy ? '改派施工' : '指派施工' }}
                  </ElDropdownItem>
                  <ElDropdownItem :command="{ action: 'release', taskId: task.id }" :disabled="!task.claimedBy && !isAdmin">暂存释放</ElDropdownItem>
                  <ElDropdownItem divided :command="{ action: 'scope-reviewed', taskId: task.id }">导出范围：已归档</ElDropdownItem>
                  <ElDropdownItem :command="{ action: 'scope-all', taskId: task.id }">导出范围：全部</ElDropdownItem>
                </ElDropdownMenu>
              </template>
            </ElDropdown>
          </div>
        </article>
      </div>
    </section>

    <ElDialog v-model="assignmentDialogVisible" :title="assignmentDialogTitle" width="520px">
      <div class="assignment-dialog-body">
        <span class="assignment-target">{{ assignmentTargetLabel }}</span>
        <label class="assignment-field">
          <span>施工员</span>
          <ElSelect
            v-model="assignmentConstructor"
            filterable
            allow-create
            default-first-option
            clearable
            :loading="loadingAccounts"
            placeholder="优先选择姓名，必要时输入账号"
          >
            <ElOption
              v-for="user in constructorOptions"
              :key="user.username"
              :label="accountOptionLabel(user)"
              :value="user.username"
              :disabled="user.status === 'disabled'"
            />
          </ElSelect>
        </label>
        <p class="assignment-note">提交给后端仍使用账号；界面优先展示姓名，并保留账号辅助识别。</p>
      </div>
      <template #footer>
        <ElButton @click="assignmentDialogVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="assignmentSubmitting" @click="submitAssignment">确认指派</ElButton>
      </template>
    </ElDialog>
  </section>
</template>
