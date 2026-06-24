<script setup lang="ts">
import { DataBoard, FolderChecked, List, SwitchButton, Tickets } from '@element-plus/icons-vue'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { exportTerminalDeliveryPackage, fetchScanImportJob, startScanImportJob } from '@/api/services'
import { staticPages } from '@/router/staticPages'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'
import type { ImportJob } from '@/api/types'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const workspace = useWorkspaceStore()

const pageTitle = computed(() => String(route.meta.title || '模块更换项目管理器'))
const navigation = computed(() => {
  const role = auth.user?.role || 'reviewer'
  const iconMap = {
    'project-board': DataBoard,
    'claim-tasks': Tickets,
    'task-hall': List,
    construction: FolderChecked,
    'sync-config': DataBoard,
  }
  return staticPages
    .filter((page) => page.key !== 'sync-config')
    .filter((page) => !page.roles.length || page.roles.includes(role) || role === 'admin')
    .map((page) => ({ ...page, icon: iconMap[page.key] }))
})

const roleLabel = computed(() => {
  if (auth.user?.role === 'admin') return '管理员'
  if (auth.user?.role === 'constructor') return '施工员'
  return '审阅员'
})
const isEmbedded = computed(() => route.query.embedded === '1')
const isConstructionRoute = computed(() => route.path === '/construction')
const refreshEventKey = 'module_manager_refresh_event'
const refreshVersionKey = 'module_manager_refresh_version'
let refreshVersion = Number(localStorage.getItem(refreshVersionKey) || 0)
let shellExportActive = false
let shellImportActive = false
let shellImportTimer = 0
let shellJobHideTimer = 0

const shellJobVisible = ref(false)
const shellJobTitle = ref('')
const shellJobDetail = ref('')
const shellJobPercent = ref(0)
const shellJobTone = ref<'info' | 'success' | 'danger'>('info')

onMounted(() => {
  void auth.hydrateFromLegacySession()
  if (!workspace.projects.length) {
    void workspace.loadProjects()
  }
  window.addEventListener('message', handleShellMessage)
  window.addEventListener('storage', handleStorageRefresh)
})

onUnmounted(() => {
  window.removeEventListener('message', handleShellMessage)
  window.removeEventListener('storage', handleStorageRefresh)
  if (shellImportTimer) window.clearInterval(shellImportTimer)
  if (shellJobHideTimer) window.clearTimeout(shellJobHideTimer)
})

function logout() {
  auth.logout()
  void router.push({ name: 'login' })
}

function currentTeamId() {
  return auth.user?.teamId || localStorage.getItem('module_manager_team_id') || 'default-team'
}

function postRefresh(reason: string, payload: Record<string, unknown> = {}, version = refreshVersion) {
  window.postMessage(
    {
      type: 'module-manager:data-refresh',
      reason,
      payload,
      version,
    },
    window.location.origin,
  )
}

function broadcastRefresh(reason: string, payload: Record<string, unknown> = {}) {
  refreshVersion += 1
  localStorage.setItem(refreshVersionKey, String(refreshVersion))
  localStorage.setItem(
    refreshEventKey,
    JSON.stringify({
      teamId: currentTeamId(),
      reason,
      payload,
      version: refreshVersion,
      ts: Date.now(),
    }),
  )
  postRefresh(reason, payload, refreshVersion)
}

function handleShellMessage(event: MessageEvent) {
  if (event.origin && event.origin !== window.location.origin) return
  const message = event.data || {}
  if (message.type === 'module-manager:start-terminal-export') {
    void startShellExport((message.scope || {}) as Record<string, unknown>)
    return
  }
  if (message.type === 'module-manager:start-scan-import') {
    void startShellScanImport(message as { file?: File; filename?: string })
    return
  }
  if (message.type !== 'module-manager:data-mutated') return
  broadcastRefresh(String(message.reason || 'data-mutated'), (message.payload || {}) as Record<string, unknown>)
}

function handleStorageRefresh(event: StorageEvent) {
  if (event.key !== refreshEventKey || !event.newValue) return
  try {
    const refresh = JSON.parse(event.newValue) as {
      teamId?: string
      reason?: string
      payload?: Record<string, unknown>
      version?: number
    }
    if (refresh.teamId && refresh.teamId !== currentTeamId()) return
    refreshVersion = Math.max(refreshVersion, Number(refresh.version || 0))
    postRefresh(refresh.reason || 'external-refresh', refresh.payload || {}, refreshVersion)
  } catch {
    // 忽略损坏的跨页刷新事件。
  }
}

function setShellJob(title: string, detail: string, percent = 0, tone: 'info' | 'success' | 'danger' = 'info', autoHide = false) {
  if (shellJobHideTimer) {
    window.clearTimeout(shellJobHideTimer)
    shellJobHideTimer = 0
  }
  shellJobVisible.value = true
  shellJobTitle.value = title
  shellJobDetail.value = detail
  shellJobPercent.value = Math.max(0, Math.min(100, Math.round(percent)))
  shellJobTone.value = tone
  if (autoHide) {
    shellJobHideTimer = window.setTimeout(() => {
      shellJobVisible.value = false
      shellJobHideTimer = 0
    }, 4200)
  }
}

function importJobPercent(job: ImportJob) {
  if (job.status === 'complete') return 100
  if (job.status === 'failed') return 100
  const progress = job.progress || {}
  const direct = Number(progress.percent || progress.percentage || 0)
  if (direct > 0) return Math.min(99, direct)
  const totalPhotos = Number(progress.total_photos || progress.total_records || 0)
  const processedPhotos = Number(progress.processed_photos || progress.processed_records || progress.resolved_image_urls || 0)
  if (totalPhotos > 0) return Math.min(99, Math.max(8, (processedPhotos / totalPhotos) * 90))
  return 45
}

function importJobDetail(job: ImportJob) {
  const progress = job.progress || {}
  if (job.status === 'complete') {
    return `导入完成，已处理 ${progress.processed_photos || progress.processed_records || progress.resolved_image_urls || 0} 项`
  }
  if (job.status === 'failed') return job.error || '扫码表格导入失败'
  const phase = String(progress.phase || job.status || '导入中')
  return `${phase}：照片 ${progress.processed_photos || progress.resolved_image_urls || 0}/${progress.total_photos || progress.total_records || 0}`
}

async function startShellExport(scope: Record<string, unknown>) {
  if (shellExportActive) {
    setShellJob('导出任务进行中', '当前已有终端包导出任务，请等待完成后再发起。', shellJobPercent.value)
    return
  }
  const taskId = String(scope.taskId || '')
  const terminal = String(scope.terminal || '')
  const reviewScope = scope.reviewScope === 'all' ? 'all' : 'reviewed'
  if (!taskId && !terminal) {
    setShellJob('导出失败', '只支持单终端导出，请从终端任务行发起。', 100, 'danger', true)
    return
  }
  shellExportActive = true
  try {
    setShellJob('准备导出终端包', `正在读取 ${terminal || taskId} 的清单`, 2)
    const result = await exportTerminalDeliveryPackage({
      taskId,
      terminal,
      reviewScope,
      onProgress: (progress) => setShellJob('导出终端包', progress.text, progress.percent),
    })
    setShellJob(
      '导出完成',
      result.failed ? `压缩包已生成，${result.failed} 张图片下载失败` : `压缩包已生成，已下载 ${result.downloaded} 张图片`,
      100,
      'success',
      true,
    )
  } catch (error) {
    setShellJob('导出失败', error instanceof Error ? error.message : '终端包导出失败', 100, 'danger', true)
  } finally {
    shellExportActive = false
  }
}

async function startShellScanImport(message: { file?: File; filename?: string }) {
  if (shellImportActive) {
    setShellJob('导入任务进行中', '当前已有扫码表格导入任务，请等待完成后再提交。', shellJobPercent.value)
    return
  }
  if (!message.file) {
    setShellJob('导入失败', '没有收到需要导入的扫码表格文件。', 100, 'danger', true)
    return
  }
  shellImportActive = true
  try {
    setShellJob('提交扫码表格', `正在提交 ${message.filename || message.file.name || 'scan.xlsx'}`, 2)
    let job = await startScanImportJob(message.file)
    setShellJob('导入扫码表格', importJobDetail(job), importJobPercent(job))
    shellImportTimer = window.setInterval(async () => {
      if (!job.jobId) return
      job = await fetchScanImportJob(job.jobId)
      setShellJob('导入扫码表格', importJobDetail(job), importJobPercent(job))
      if (['complete', 'partial_failed', 'failed'].includes(job.status)) {
        if (shellImportTimer) window.clearInterval(shellImportTimer)
        shellImportTimer = 0
        shellImportActive = false
        if (job.status === 'failed') {
          setShellJob('导入失败', job.error || '扫码表格导入失败', 100, 'danger', true)
        } else {
          setShellJob('导入完成', importJobDetail({ ...job, status: 'complete' }), 100, 'success', true)
          broadcastRefresh('scan-import-complete', { jobId: job.jobId, status: job.status })
        }
      }
    }, 1200)
  } catch (error) {
    shellImportActive = false
    setShellJob('导入失败', error instanceof Error ? error.message : '扫码表格导入失败', 100, 'danger', true)
  }
}
</script>

<template>
  <div class="app-shell" :class="{ embedded: isEmbedded, 'construction-route': isConstructionRoute }">
    <header v-if="!isEmbedded" class="topbar">
      <div class="topbar-brand">
        <span class="brand-mark">V3.0.8</span>
        <div class="brand-copy">
          <strong>模块更换项目管理器</strong>
          <span>{{ workspace.activeProject?.name || '工程审阅与施工采集工作台' }}</span>
        </div>
      </div>

      <nav class="top-nav" aria-label="主导航">
        <button
          v-for="item in navigation"
          :key="item.key"
          class="top-nav__item"
          :class="{ active: route.path === item.routePath }"
          type="button"
          @click="router.push(item.routePath)"
        >
          <ElIcon><component :is="item.icon" /></ElIcon>
          <span>{{ item.title }}</span>
        </button>
      </nav>

      <div class="header-actions">
        <span class="page-chip">{{ pageTitle }}</span>
        <span class="user-chip">{{ roleLabel }} / {{ auth.displayName }}</span>
        <ElTooltip content="退出登录" placement="bottom">
          <ElButton :icon="SwitchButton" circle @click="logout" />
        </ElTooltip>
      </div>
    </header>

    <main class="main-panel">
      <RouterView />
    </main>

    <aside v-if="shellJobVisible" class="shell-job-status" :class="`tone-${shellJobTone}`" aria-live="polite">
      <strong>{{ shellJobTitle }}</strong>
      <span>{{ shellJobDetail }}</span>
      <ElProgress :percentage="shellJobPercent" :show-text="false" />
    </aside>
  </div>
</template>

<style scoped>
.shell-job-status {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 80;
  display: grid;
  width: min(420px, calc(100vw - 36px));
  gap: 8px;
  padding: 16px;
  border: 1px solid var(--v2-border, #d7e1ec);
  border-radius: var(--v2-radius-panel, 12px);
  background: rgba(255, 255, 255, 0.9);
  box-shadow: var(--v2-shadow-panel, 0 18px 42px rgba(15, 23, 42, 0.16));
  backdrop-filter: blur(20px) saturate(160%);
  -webkit-backdrop-filter: blur(20px) saturate(160%);
}

.shell-job-status strong {
  color: var(--v2-text-strong, #0f172a);
  font-size: 14px;
}

.shell-job-status span {
  color: var(--v2-text-muted, #64748b);
  font-size: 12px;
  line-height: 1.5;
}

.shell-job-status.tone-success {
  border-color: rgba(22, 163, 74, 0.28);
}

.shell-job-status.tone-danger {
  border-color: rgba(185, 28, 28, 0.32);
}

@media (max-width: 640px) {
  .shell-job-status {
    right: 10px;
    bottom: calc(10px + env(safe-area-inset-bottom, 0px));
    width: calc(100vw - 20px);
  }
}
</style>
