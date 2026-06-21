<script setup lang="ts">
import { Refresh, Unlock, UserFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  assignConstructionTask,
  currentActor,
  fetchTasks,
  claimTask as claimTaskApi,
  releaseAllClaimedTasks,
  releaseTask as releaseTaskApi,
} from '@/api/services'
import type { ReviewTask } from '@/api/types'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const releasingAll = ref(false)
const assigningTaskId = ref('')
const tasks = ref<ReviewTask[]>([])
const errorMessage = ref('')
let refreshInterval = 0
let refreshTimer = 0

const actor = computed(() => auth.user?.username || auth.user?.id || currentActor())
const isAdmin = computed(() => auth.user?.role === 'admin' || auth.user?.roles?.includes('admin'))
const visibleTasks = computed(() => {
  const items = isAdmin.value
    ? [...tasks.value]
    : tasks.value.filter((task) => task.hasScanInfo && Number(task.unreviewedCount || 0) > 0)
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

async function loadTasks() {
  loading.value = true
  errorMessage.value = ''
  try {
    tasks.value = await fetchTasks()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '任务加载失败'
  } finally {
    loading.value = false
  }
}

function scheduleRefresh() {
  if (refreshTimer) window.clearTimeout(refreshTimer)
  refreshTimer = window.setTimeout(() => {
    refreshTimer = 0
    void loadTasks()
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
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '领取失败'
  }
}

async function release(task: ReviewTask) {
  errorMessage.value = ''
  try {
    const updated = await releaseTaskApi(task.id)
    tasks.value = tasks.value.map((item) => (item.id === task.id ? updated : item))
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
    await loadTasks()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '收回全部失败'
  } finally {
    releasingAll.value = false
  }
}

async function assignConstruction(task: ReviewTask) {
  if (!isAdmin.value) return
  try {
    const { value } = await ElMessageBox.prompt('请输入施工员账号', '指派施工终端', {
      confirmButtonText: task.assignedConstructor || task.constructionClaimedBy ? '确认改派' : '确认指派',
      cancelButtonText: '取消',
      inputValue: task.assignedConstructor || task.constructionClaimedBy || '',
      inputPlaceholder: '例如 constructor-a',
      inputValidator: (value) => Boolean(String(value || '').trim()) || '施工员账号不能为空',
    })
    const constructor = String(value || '').trim()
    assigningTaskId.value = task.id
    errorMessage.value = ''
    const updated = await assignConstructionTask(task.id, constructor)
    tasks.value = tasks.value.map((item) => (item.id === task.id ? updated : item))
    ElMessage.success(`已指派给 ${constructor}`)
  } catch (error) {
    if (error === 'cancel' || (error instanceof Error && error.message === 'cancel')) return
    errorMessage.value = error instanceof Error ? error.message : '指派施工失败'
  } finally {
    assigningTaskId.value = ''
  }
}

function openReview(task: ReviewTask) {
  if (task.claimedBy && task.claimedBy !== actor.value && !isAdmin.value) return
  void router.push('/task-hall')
}

onMounted(() => {
  void loadTasks()
  window.addEventListener('message', handleExternalRefresh)
  refreshInterval = window.setInterval(scheduleRefresh, 10000)
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
        <ElButton :icon="Refresh" :loading="loading" @click="loadTasks">刷新</ElButton>
        <ElButton v-if="isAdmin" :icon="Unlock" type="warning" plain :loading="releasingAll" @click="releaseAll">
          收回全部
        </ElButton>
      </div>
    </div>

    <ElAlert v-if="errorMessage" class="claim-alert" type="error" :closable="false" :title="errorMessage" />

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
      </div>

      <ElSkeleton v-if="loading && !tasks.length" :rows="6" animated />
      <ElEmpty v-else-if="!visibleTasks.length" description="暂无可领取终端任务" />
      <div v-else class="claim-task-grid">
        <article
          v-for="task in visibleTasks"
          :key="task.id"
          class="claim-task-card"
          :class="{ empty: !task.hasScanInfo, done: !task.unreviewedCount && task.hasScanInfo }"
          @click="openReview(task)"
        >
          <div class="task-card-top">
            <div class="task-title-block">
              <strong>终端 {{ task.terminal || task.id }}</strong>
              <span>{{ task.claimedBy ? `审阅：${task.claimedBy}` : '审阅：尚未领取' }}</span>
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
            <span>施工：{{ task.assignedConstructor || task.constructionClaimedBy || '未指派' }}</span>
            <span v-if="task.constructionExceptionCount">异常 {{ task.constructionExceptionCount }}</span>
          </div>

          <div class="task-card-actions" @click.stop>
            <ElButton
              v-if="isAdmin"
              size="small"
              plain
              :icon="UserFilled"
              :loading="assigningTaskId === task.id"
              @click="assignConstruction(task)"
            >
              {{ task.assignedConstructor || task.constructionClaimedBy ? '改派施工' : '指派施工' }}
            </ElButton>
            <ElButton size="small" :disabled="!task.claimedBy && !isAdmin" @click="release(task)">暂存释放</ElButton>
            <ElButton
              size="small"
              type="primary"
              :disabled="!task.canClaim || (!!task.claimedBy && task.claimedBy !== actor && !isAdmin)"
              @click="claim(task)"
            >
              {{ task.claimedBy === actor ? '继续持有' : '领取' }}
            </ElButton>
          </div>
        </article>
      </div>
    </section>
  </section>
</template>
