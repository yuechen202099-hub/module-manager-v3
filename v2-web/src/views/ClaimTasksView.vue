<script setup lang="ts">
import { Refresh, Search, Upload } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, onUnmounted, ref } from 'vue'

import { assignConstructionTask, fetchTaskSnapshot, fetchUserAccounts, setConstructionTaskPriority } from '@/api/services'
import ConstructionPriorityImportDialog from '@/components/ConstructionPriorityImportDialog.vue'
import MaterialExportCardControls from '@/components/material-export/MaterialExportCardControls.vue'
import MaterialExportToolbar from '@/components/material-export/MaterialExportToolbar.vue'
import type { ReviewTask, UserAccount } from '@/api/types'
import { useMaterialExport } from '@/features/materialExport/useMaterialExport'
import { useAuthStore } from '@/stores/auth'
import { createMutationGuardedRequestGate, isAbortError } from '@/utils/latestRequestGate.mjs'

const TASK_STATUS_REFRESH_INTERVAL_MS = 15 * 60 * 1000
const MATERIAL_EXPORT_ENABLED = false

type TaskFilter = 'all' | 'priority' | 'construction' | 'completed'

const auth = useAuthStore()
const loading = ref(false)
const assigningTaskId = ref('')
const assignmentDialogVisible = ref(false)
const assignmentTargetTask = ref<ReviewTask | null>(null)
const assignmentConstructor = ref('')
const assignmentSubmitting = ref(false)
const priorityUpdatingTaskId = ref('')
const constructionPriorityImportVisible = ref(false)
const tasks = ref<ReviewTask[]>([])
const accountUsers = ref<UserAccount[]>([])
const loadingAccounts = ref(false)
const errorMessage = ref('')
const searchQuery = ref('')
const taskFilter = ref<TaskFilter>('all')

let refreshInterval = 0
let taskMutationVersion = 0

const taskLoadGate = createMutationGuardedRequestGate((nextLoading) => {
  loading.value = nextLoading
})

const isAdmin = computed(() => Boolean(auth.user?.role === 'admin' || auth.user?.roles?.includes('admin')))
const materialExport = useMaterialExport(tasks, isAdmin)
const userByUsername = computed(() => {
  const map = new Map<string, UserAccount>()
  for (const user of accountUsers.value) {
    if (user.username) map.set(user.username, user)
  }
  return map
})
const constructorOptions = computed(() => accountUsers.value.filter((user) => (user.roles || []).includes('constructor')))
const assignmentDialogTitle = computed(() => {
  const task = assignmentTargetTask.value
  if (!task) return '指派施工'
  return taskConstructorAccount(task) ? '改派施工' : '指派施工'
})
const assignmentTargetLabel = computed(() => {
  const task = assignmentTargetTask.value
  if (!task) return ''
  return `终端 ${task.terminal || task.id}`
})
const visibleTasks = computed(() => {
  const query = normalizeSearch(searchQuery.value)
  const items = tasks.value.filter((task) => {
    if (taskFilter.value === 'priority' && !task.constructionPriority) return false
    if (taskFilter.value === 'construction' && (!task.constructionAvailable || isTaskConstructionComplete(task))) return false
    if (taskFilter.value === 'completed' && !isTaskConstructionComplete(task)) return false
    if (query && !taskMatchesSearch(task, query)) return false
    return true
  })
  return items.sort((left, right) => {
    const priorityDiff = Number(right.constructionPriority) - Number(left.constructionPriority)
    if (priorityDiff) return priorityDiff
    const completionDiff = constructionProgressPercent(right) - constructionProgressPercent(left)
    if (completionDiff) return completionDiff
    return String(left.terminal || left.id).localeCompare(String(right.terminal || right.id), 'zh-Hans-CN')
  })
})
const exportableVisibleTasks = computed(() => visibleTasks.value.filter((task) => taskUploadedGroups(task) > 0))
const allVisibleExportSelected = computed(() => {
  const rows = exportableVisibleTasks.value
  return Boolean(rows.length) && rows.every((task) => materialExport.isSelected(task.id))
})
const summary = computed(() => ({
  total: tasks.value.length,
  priority: tasks.value.filter((task) => task.constructionPriority && !isTaskConstructionComplete(task)).length,
  available: tasks.value.filter((task) => task.constructionAvailable && !isTaskConstructionComplete(task)).length,
  completed: tasks.value.filter((task) => isTaskConstructionComplete(task)).length,
}))

function normalizeSearch(value: string) {
  return String(value || '')
    .normalize('NFKC')
    .toLowerCase()
    .replace(/\s+/g, '')
}

function taskMatchesSearch(task: ReviewTask, query: string) {
  const haystack = normalizeSearch(
    [task.terminal, task.address, task.addressSearchText, task.meterSearchText, task.name, task.id]
      .filter(Boolean)
      .join(' '),
  )
  return haystack.includes(query)
}

function taskTotalGroups(task: ReviewTask) {
  return Number(task.renovationCount || task.totalGroups || 0)
}

function taskUploadedGroups(task: ReviewTask) {
  return Number(task.constructionUploadedCount ?? task.uploadedCount ?? 0)
}

function taskPendingGroups(task: ReviewTask) {
  if (task.constructionUnbuiltCount !== undefined) return Math.max(0, Number(task.constructionUnbuiltCount || 0))
  return Math.max(0, taskTotalGroups(task) - taskUploadedGroups(task))
}

function isTaskConstructionComplete(task: ReviewTask) {
  const total = taskTotalGroups(task)
  if (total <= 0) return false
  if (task.constructionUnbuiltCount !== undefined && Number(task.constructionUnbuiltCount || 0) <= 0) return true
  return taskUploadedGroups(task) >= total || (Number(task.uploadRate) || 0) >= 1
}

function constructionProgressPercent(task: ReviewTask) {
  if (isTaskConstructionComplete(task)) return 100
  const total = taskTotalGroups(task)
  if (total <= 0) return 0
  return Math.max(0, Math.min(99, Math.floor((taskUploadedGroups(task) / total) * 100)))
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
  return task.assignedConstructorName || task.constructionClaimedByName || userDisplayName(taskConstructorAccount(task)) || '未指派'
}

function taskConstructorAccountHint(task: ReviewTask) {
  const account = taskConstructorAccount(task)
  const name = taskConstructorName(task)
  return account && account !== name ? `账号 ${account}` : ''
}

function taskStatusLabel(task: ReviewTask) {
  if (isTaskConstructionComplete(task)) return '已施工'
  if (task.constructionPriority) return '优先施工'
  if (taskConstructorAccount(task)) return '已指派'
  if (task.constructionAvailable) return '可施工'
  return '待指派'
}

function taskStatusType(task: ReviewTask) {
  if (isTaskConstructionComplete(task)) return 'success'
  if (task.constructionPriority) return 'danger'
  if (taskConstructorAccount(task)) return 'warning'
  if (task.constructionAvailable) return 'primary'
  return 'info'
}

function constructionActionLabel(task: ReviewTask) {
  if (isTaskConstructionComplete(task)) return '已施工'
  return taskConstructorAccount(task) ? '改派施工' : '指派施工'
}

function canManageConstructionPriority(task: ReviewTask) {
  return isAdmin.value && task.constructionAvailable && !isTaskConstructionComplete(task)
}

async function loadAccounts() {
  if (!isAdmin.value || loadingAccounts.value) return
  loadingAccounts.value = true
  try {
    accountUsers.value = await fetchUserAccounts()
  } catch (error) {
    ElMessage.warning(error instanceof Error ? error.message : '施工员账号加载失败')
  } finally {
    loadingAccounts.value = false
  }
}

async function loadTasks(force = false) {
  const request = taskLoadGate.begin(taskMutationVersion)
  errorMessage.value = ''
  try {
    const snapshot = await fetchTaskSnapshot({ force, signal: request.signal })
    if (!request.isCurrent(taskMutationVersion)) return
    tasks.value = snapshot.items
  } catch (error) {
    if (isAbortError(error)) return
    if (!request.isCurrent(taskMutationVersion)) return
    errorMessage.value = error instanceof Error ? error.message : '任务加载失败'
  } finally {
    request.finish()
  }
}

async function loadMaterialExportSummaries() {
  if (!isAdmin.value) return
  try {
    await materialExport.loadSummaries(tasks.value)
  } catch (error) {
    materialExport.error.value = error instanceof Error ? error.message : '导出摘要加载失败'
  }
}

async function loadInitialTasks() {
  await loadTasks()
  await loadMaterialExportSummaries()
}

async function refreshTasks() {
  await loadTasks(true)
  await loadMaterialExportSummaries()
}

function selectVisibleForExport(selected: boolean) {
  materialExport.selectCurrent(visibleTasks.value, selected)
}

async function updateExportCollectorCount(task: ReviewTask, count: number) {
  try {
    await materialExport.updateCount(task.id, count)
    ElMessage.success(`终端 ${task.terminal || task.id} 的应还采集器数量已保存`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '应还采集器数量保存失败')
  }
}

async function startMaterialExport(taskIds?: string[]) {
  try {
    const result = await materialExport.start(taskIds)
    if (result === 'completed') ElMessage.success('终端资料导出完成')
    else ElMessage.info('已在当前文件完成后暂停，可继续导出')
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    ElMessage.error(error instanceof Error ? error.message : '终端资料导出失败')
  }
}

function pauseMaterialExportRun() {
  materialExport.pause()
  ElMessage.info('将在当前文件完成后暂停')
}

async function resumeMaterialExportRun() {
  try {
    const result = await materialExport.resume()
    if (result === 'completed') ElMessage.success('终端资料导出完成')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '继续导出失败')
  }
}

async function confirmReleaseMaterialExport() {
  try {
    await ElMessageBox.confirm(
      '仅释放尚未完成终端的采集器预留；已完成终端不会被释放。是否继续？',
      '取消本次导出',
      { confirmButtonText: '确认释放', cancelButtonText: '返回', type: 'warning' },
    )
    await materialExport.release('管理员在任务派发页取消导出')
    ElMessage.success('未完成终端的采集器占用已释放')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error instanceof Error ? error.message : '释放失败')
  }
}

function handleConstructionPriorityImported() {
  constructionPriorityImportVisible.value = false
  taskMutationVersion += 1
  taskLoadGate.invalidate()
  void loadTasks(true)
}

async function openAssignDialog(task: ReviewTask) {
  if (!isAdmin.value || isTaskConstructionComplete(task)) return
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
    ElMessage.warning('请选择施工员')
    return
  }
  assignmentSubmitting.value = true
  assigningTaskId.value = task.id
  errorMessage.value = ''
  try {
    const updated = await assignConstructionTask(task.id, constructor)
    taskMutationVersion += 1
    taskLoadGate.invalidate()
    tasks.value = tasks.value.map((item) => (item.id === task.id ? updated : item))
    assignmentDialogVisible.value = false
    ElMessage.success(`已指派给 ${userDisplayLabel(constructor)}`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '指派施工失败'
  } finally {
    assignmentSubmitting.value = false
    assigningTaskId.value = ''
  }
}

async function updateConstructionPriority(task: ReviewTask, priority: boolean) {
  if (!canManageConstructionPriority(task)) return
  priorityUpdatingTaskId.value = task.id
  errorMessage.value = ''
  try {
    const updated = await setConstructionTaskPriority(task.id, priority)
    taskMutationVersion += 1
    taskLoadGate.invalidate()
    tasks.value = tasks.value.map((item) => (item.id === task.id ? updated : item))
    ElMessage.success(priority ? '已设为优先施工' : '已取消优先施工')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '优先施工更新失败'
  } finally {
    priorityUpdatingTaskId.value = ''
  }
}

function handleExternalRefresh(event: MessageEvent) {
  if (event.data?.type === 'module-manager:data-refresh') {
    void loadTasks(true)
  }
}

onMounted(() => {
  void loadInitialTasks()
  void loadAccounts()
  window.addEventListener('message', handleExternalRefresh)
  refreshInterval = window.setInterval(() => void loadTasks(true), TASK_STATUS_REFRESH_INTERVAL_MS)
})

onUnmounted(() => {
  window.removeEventListener('message', handleExternalRefresh)
  taskLoadGate.cancel()
  if (refreshInterval) window.clearInterval(refreshInterval)
  refreshInterval = 0
})
</script>

<template>
  <section class="native-claim-page">
    <div class="claim-hero panel">
      <div>
        <p class="eyebrow">任务派发</p>
      </div>
      <div class="claim-actions">
        <ElButton :icon="Refresh" :loading="loading" @click="refreshTasks">刷新</ElButton>
        <ElButton v-if="isAdmin" :icon="Upload" type="primary" plain @click="constructionPriorityImportVisible = true">
          批量标记
        </ElButton>
      </div>
    </div>

    <ElAlert v-if="errorMessage" class="claim-alert" type="error" :closable="false" :title="errorMessage" />
    <ElAlert v-if="isAdmin && materialExport.error.value" class="claim-alert" type="warning" :closable="false" :title="materialExport.error.value" />
    <ElAlert
      v-if="isAdmin && !MATERIAL_EXPORT_ENABLED"
      data-testid="material-export-disabled-notice"
      class="claim-alert"
      type="info"
      :closable="false"
      title="资料导出暂时关闭，正在切换为浏览器直连 OSS；应还采集器数量仍可设置"
    />

    <div class="claim-summary">
      <article class="metric">
        <span class="metric-label">终端总数</span>
        <strong class="metric-value">{{ summary.total }}</strong>
      </article>
      <article class="metric">
        <span class="metric-label">优先施工</span>
        <strong class="metric-value">{{ summary.priority }}</strong>
      </article>
      <article class="metric">
        <span class="metric-label">可施工</span>
        <strong class="metric-value">{{ summary.available }}</strong>
      </article>
      <article class="metric">
        <span class="metric-label">已施工</span>
        <strong class="metric-value">{{ summary.completed }}</strong>
      </article>
    </div>

    <section class="panel task-list-panel">
      <div class="panel-heading">
        <div>
          <h3>终端任务</h3>
          <p class="muted">共 {{ visibleTasks.length }} 个</p>
        </div>
        <div class="claim-task-heading-actions">
          <MaterialExportToolbar
            v-if="isAdmin && MATERIAL_EXPORT_ENABLED"
            :selected-count="materialExport.selectedCount.value"
            :all-selected="allVisibleExportSelected"
            :running="materialExport.running.value"
            :paused="materialExport.paused.value"
            :has-job="Boolean(materialExport.currentJob.value)"
            :progress-text="materialExport.progressText.value"
            @select-all="selectVisibleForExport"
            @export="startMaterialExport()"
            @pause="pauseMaterialExportRun"
            @resume="resumeMaterialExportRun"
            @release="confirmReleaseMaterialExport"
          />
          <ElInput
            v-model="searchQuery"
            class="claim-task-search"
            clearable
            :prefix-icon="Search"
            placeholder="搜索终端号或地址"
            aria-label="搜索终端号或地址"
          />
        </div>
      </div>

      <ElRadioGroup v-model="taskFilter" class="claim-task-filters" size="small">
        <ElRadioButton value="all">全部</ElRadioButton>
        <ElRadioButton value="priority">优先施工</ElRadioButton>
        <ElRadioButton value="construction">可施工</ElRadioButton>
        <ElRadioButton value="completed">已施工</ElRadioButton>
      </ElRadioGroup>

      <ElSkeleton v-if="loading && !tasks.length" :rows="6" animated />
      <ElEmpty v-else-if="!visibleTasks.length" :description="searchQuery ? '没有匹配的终端或地址' : '暂无终端任务'" />
      <div v-else class="claim-task-grid">
        <article
          v-for="task in visibleTasks"
          :key="task.id"
          class="claim-task-card"
          :class="{
            done: isTaskConstructionComplete(task),
            priority: task.constructionPriority && !isTaskConstructionComplete(task),
          }"
        >
          <div class="task-card-top">
            <div class="task-title-block">
              <strong>终端 {{ task.terminal || task.id }}</strong>
              <span>{{ taskConstructorName(task) }}</span>
              <span v-if="task.address" class="task-address-line">{{ task.address }}</span>
            </div>
            <ElTag class="status-badge" :class="`status-badge--${taskStatusType(task)}`" :type="taskStatusType(task)" effect="plain">
              {{ taskStatusLabel(task) }}
            </ElTag>
          </div>

          <div class="task-primary-line">
            <div>
              <span>未施工</span>
              <b>{{ taskPendingGroups(task) }}</b>
            </div>
            <div>
              <span>施工进度</span>
              <b>{{ constructionProgressPercent(task) }}%</b>
            </div>
          </div>

          <div class="task-card-metrics">
            <div><span>改造数</span><b>{{ taskTotalGroups(task) }}</b></div>
            <div><span>已上传</span><b>{{ taskUploadedGroups(task) }}</b></div>
            <div><span>异常</span><b>{{ task.constructionExceptionCount || 0 }}</b></div>
          </div>

          <div class="task-availability-tags">
            <ElTag v-if="task.constructionPriority && !isTaskConstructionComplete(task)" size="small" type="danger" effect="plain">优先施工</ElTag>
            <ElTag v-if="task.constructionAvailable && !isTaskConstructionComplete(task)" size="small" type="warning" effect="plain">可施工</ElTag>
            <ElTag v-if="isTaskConstructionComplete(task)" size="small" type="success" effect="plain">已施工</ElTag>
          </div>

          <ElProgress :percentage="constructionProgressPercent(task)" :stroke-width="8" :show-text="false" />

          <div class="task-construction-line">
            <span>
              施工：<strong>{{ taskConstructorName(task) }}</strong>
              <small v-if="!isTaskConstructionComplete(task) && taskConstructorAccountHint(task)">{{ taskConstructorAccountHint(task) }}</small>
            </span>
          </div>

          <div class="task-card-actions" @click.stop>
            <ElButton
              size="small"
              type="primary"
              :loading="assigningTaskId === task.id"
              :disabled="isTaskConstructionComplete(task)"
              @click="openAssignDialog(task)"
            >
              {{ constructionActionLabel(task) }}
            </ElButton>
            <ElButton
              v-if="canManageConstructionPriority(task)"
              size="small"
              plain
              type="danger"
              :loading="priorityUpdatingTaskId === task.id"
              @click="updateConstructionPriority(task, !task.constructionPriority)"
            >
              {{ task.constructionPriority ? '取消优先施工' : '设为优先施工' }}
            </ElButton>
            <MaterialExportCardControls
              v-if="isAdmin"
              :task-id="task.id"
              :terminal-code="task.terminal || task.id"
              :summary="materialExport.summaries.value[task.id]"
              :selected="materialExport.isSelected(task.id)"
              :disabled="taskUploadedGroups(task) <= 0"
              :busy="materialExport.running.value"
              :export-enabled="MATERIAL_EXPORT_ENABLED"
              @selected="materialExport.setSelected(task.id, $event)"
              @count="updateExportCollectorCount(task, $event)"
              @export="startMaterialExport([task.id])"
            />
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
            placeholder="选择施工员"
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
      </div>
      <template #footer>
        <ElButton @click="assignmentDialogVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="assignmentSubmitting" @click="submitAssignment">确认</ElButton>
      </template>
    </ElDialog>

    <ConstructionPriorityImportDialog
      v-if="isAdmin"
      v-model="constructionPriorityImportVisible"
      @imported="handleConstructionPriorityImported"
    />
  </section>
</template>

<style scoped>
.claim-task-heading-actions {
  display: flex;
  flex: 1 1 640px;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}
</style>
