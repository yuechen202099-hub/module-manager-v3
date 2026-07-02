<script setup lang="ts">
import { DataBoard, Expand, Fold, FolderChecked, List, Search, SwitchButton, Tickets, UserFilled } from '@element-plus/icons-vue'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { exportTerminalDeliveryPackage, fetchScanImportJob, startScanImportJob } from '@/api/services'
import { APP_VERSION, releaseNotes } from '@/constants/releaseNotes'
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
    projects: List,
    'project-board': DataBoard,
    'claim-tasks': Tickets,
    'task-hall': List,
    'global-search': Search,
    construction: FolderChecked,
    'account-management': UserFilled,
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
const isAdmin = computed(() => auth.user?.role === 'admin' || auth.user?.roles?.includes('admin'))
const releaseNotesVisible = ref(false)
const releaseNotesPage = ref(1)
const releaseNotesPageSize = 4
const sidebarStorageKey = 'module_manager_sidebar_collapsed'
const sidebarCollapsed = ref(localStorage.getItem(sidebarStorageKey) === '1')
const pagedReleaseNotes = computed(() => {
  const start = (releaseNotesPage.value - 1) * releaseNotesPageSize
  return releaseNotes.slice(start, start + releaseNotesPageSize)
})
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
  syncRouteProject()
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

watch(
  () => route.query.project_id,
  () => {
    syncRouteProject()
  },
)

function syncRouteProject() {
  workspace.selectRouteProject(route.query.project_id)
}

function logout() {
  auth.logout()
  void router.push({ name: 'login' })
}

function openReleaseNotes() {
  releaseNotesPage.value = 1
  releaseNotesVisible.value = true
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem(sidebarStorageKey, sidebarCollapsed.value ? '1' : '0')
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
  <div
    class="app-shell side-shell"
    :class="{ embedded: isEmbedded, 'construction-route': isConstructionRoute, collapsed: sidebarCollapsed }"
  >
    <aside v-if="!isEmbedded" class="side-rail" aria-label="平台导航">
      <div class="side-brand">
        <span class="brand-mark">V{{ APP_VERSION }}</span>
        <div class="brand-copy">
          <strong>模块更换项目管理器</strong>
          <span>{{ workspace.activeProject?.name || '工程审阅与施工采集工作台' }}</span>
        </div>
      </div>

      <button
        class="side-toggle"
        type="button"
        :aria-expanded="!sidebarCollapsed"
        :aria-label="sidebarCollapsed ? '展开导航' : '收起导航'"
        @click="toggleSidebar"
      >
        <ElIcon><component :is="sidebarCollapsed ? Expand : Fold" /></ElIcon>
      </button>

      <nav class="side-nav" aria-label="主导航">
        <button
          v-for="item in navigation"
          :key="item.key"
          class="side-nav__item"
          :class="{ active: route.path === item.routePath }"
          type="button"
          :title="sidebarCollapsed ? item.title : undefined"
          @click="router.push(item.routePath)"
        >
          <ElIcon><component :is="item.icon" /></ElIcon>
          <span>{{ item.title }}</span>
        </button>
      </nav>

      <div class="side-actions">
        <ElTooltip v-if="isAdmin && sidebarCollapsed" content="更新内容" placement="right">
          <ElButton :icon="Tickets" circle @click="openReleaseNotes" />
        </ElTooltip>
        <ElButton v-else-if="isAdmin" :icon="Tickets" plain @click="openReleaseNotes">更新内容</ElButton>

        <div class="side-user" :title="`${roleLabel} / ${auth.displayName}`">
          <span>{{ roleLabel }}</span>
          <strong>{{ auth.displayName }}</strong>
        </div>

        <ElTooltip content="退出登录" placement="right">
          <ElButton :icon="SwitchButton" circle @click="logout" />
        </ElTooltip>
      </div>
    </aside>

    <div class="shell-content">
      <header v-if="!isEmbedded" class="shell-header">
        <div>
          <span class="shell-page-kicker">当前页面</span>
          <h1 class="shell-page-title">{{ pageTitle }}</h1>
        </div>
        <span class="shell-project-chip">{{ workspace.activeProject?.name || '未选择项目' }}</span>
      </header>

      <main class="main-panel">
        <RouterView />
      </main>
    </div>

    <aside v-if="shellJobVisible" class="shell-job-status" :class="`tone-${shellJobTone}`" aria-live="polite">
      <strong>{{ shellJobTitle }}</strong>
      <span>{{ shellJobDetail }}</span>
      <ElProgress :percentage="shellJobPercent" :show-text="false" />
    </aside>

    <ElDialog v-model="releaseNotesVisible" title="更新内容" width="720px" class="release-notes-dialog" append-to-body>
      <div class="release-notes">
        <article v-for="note in pagedReleaseNotes" :key="note.version" class="release-note">
          <header>
            <div>
              <strong>{{ note.version }}</strong>
              <span>{{ note.date }} / {{ note.type }}</span>
            </div>
            <ElTag effect="light">{{ note.title }}</ElTag>
          </header>
          <ul>
            <li v-for="item in note.items" :key="item">{{ item }}</li>
          </ul>
        </article>
      </div>
      <template #footer>
        <ElPagination
          v-model:current-page="releaseNotesPage"
          :page-size="releaseNotesPageSize"
          :total="releaseNotes.length"
          layout="total, prev, pager, next"
          background
          small
        />
      </template>
    </ElDialog>
  </div>
</template>

<style scoped>
.side-shell {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  min-height: 100dvh;
}

.side-shell.collapsed {
  grid-template-columns: 80px minmax(0, 1fr);
}

.side-shell.embedded {
  display: block;
}

.side-rail {
  position: sticky;
  top: 0;
  z-index: 20;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
  align-self: start;
  height: 100dvh;
  gap: 14px;
  padding: 16px 12px;
  border-right: 1px solid var(--v2-border-soft, #e2e8f0);
  background: rgba(255, 255, 255, 0.86);
  box-shadow: 12px 0 32px rgba(16, 24, 40, 0.05);
  backdrop-filter: blur(22px) saturate(170%);
  -webkit-backdrop-filter: blur(22px) saturate(170%);
}

.side-brand {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.side-shell.collapsed .side-brand {
  grid-template-columns: 1fr;
  justify-items: center;
}

.side-shell.collapsed .brand-copy,
.side-shell.collapsed .side-nav__item span,
.side-shell.collapsed .side-user strong {
  display: none;
}

.side-shell.collapsed .brand-mark {
  min-width: 48px;
  width: 48px;
  padding: 0;
  font-size: 10px;
}

.side-toggle {
  display: inline-grid;
  place-items: center;
  justify-self: end;
  width: 34px;
  height: 34px;
  border: 1px solid var(--v2-border-soft, #e2e8f0);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
  color: var(--v2-text-muted, #64748b);
  cursor: pointer;
}

.side-shell.collapsed .side-toggle {
  justify-self: center;
}

.side-nav {
  display: grid;
  align-content: start;
  gap: 6px;
  min-height: 0;
  overflow-y: auto;
  scrollbar-width: none;
}

.side-nav::-webkit-scrollbar {
  display: none;
}

.side-nav__item {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  min-height: 42px;
  padding: 0 12px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--v2-text-muted, #64748b);
  font-size: 14px;
  font-weight: 760;
  letter-spacing: 0;
  text-align: left;
  cursor: pointer;
}

.side-nav__item:hover {
  color: var(--v2-text-strong, #0f172a);
  background: rgba(10, 114, 216, 0.06);
}

.side-nav__item.active {
  color: var(--v2-primary, #0a72d8);
  background: var(--v2-primary-muted, #e8f3ff);
  box-shadow: inset 3px 0 0 var(--v2-primary, #0a72d8);
}

.side-shell.collapsed .side-nav__item {
  grid-template-columns: 1fr;
  justify-items: center;
  padding: 0;
}

.side-actions {
  display: grid;
  gap: 10px;
  padding-top: 12px;
  border-top: 1px solid var(--v2-border-soft, #e2e8f0);
}

.side-user {
  display: grid;
  gap: 2px;
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--v2-border-soft, #e2e8f0);
  border-radius: 8px;
  background: rgba(248, 250, 252, 0.82);
}

.side-user span,
.side-user strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.side-user span {
  color: var(--v2-text-muted, #64748b);
  font-size: 12px;
}

.side-user strong {
  color: var(--v2-text-strong, #0f172a);
  font-size: 13px;
}

.side-shell.collapsed .side-user {
  justify-items: center;
  padding: 8px 4px;
}

.shell-content {
  min-width: 0;
}

.shell-header {
  position: sticky;
  top: 0;
  z-index: 12;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  min-height: 64px;
  padding: 12px 18px;
  border-bottom: 1px solid var(--v2-border-soft, #e2e8f0);
  background: rgba(255, 255, 255, 0.76);
  backdrop-filter: blur(20px) saturate(160%);
  -webkit-backdrop-filter: blur(20px) saturate(160%);
}

.shell-page-kicker {
  display: block;
  color: var(--v2-text-muted, #64748b);
  font-size: 12px;
  font-weight: 700;
}

.shell-page-title {
  margin: 0;
  color: var(--v2-text-strong, #0f172a);
  font-size: 20px;
  font-weight: 820;
  line-height: 1.25;
}

.shell-project-chip {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  max-width: min(360px, 42vw);
  padding: 0 12px;
  overflow: hidden;
  border: 1px solid var(--v2-primary-border, rgba(10, 114, 216, 0.22));
  border-radius: 999px;
  background: var(--v2-primary-muted, #e8f3ff);
  color: var(--v2-primary, #0a72d8);
  font-size: 13px;
  font-weight: 760;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.side-shell:not(.embedded) .main-panel {
  width: 100%;
  max-width: var(--v2-content-max, 1440px);
}

.side-shell.construction-route:not(.embedded) .main-panel {
  max-width: 100%;
}

@media (max-width: 900px) {
  .side-shell:not(.embedded) {
    grid-template-columns: 1fr;
  }

  .side-shell:not(.embedded) .side-rail {
    position: sticky;
    top: 0;
    grid-template-rows: auto auto;
    grid-template-columns: minmax(0, 1fr) auto;
    height: auto;
    gap: 10px;
    padding: 10px;
    border-right: 0;
    border-bottom: 1px solid var(--v2-border-soft, #e2e8f0);
  }

  .side-brand {
    grid-column: 1;
  }

  .side-toggle {
    grid-column: 2;
    grid-row: 1;
  }

  .side-nav {
    grid-column: 1 / -1;
    grid-row: 2;
    display: flex;
    overflow-x: auto;
    overflow-y: hidden;
  }

  .side-nav__item {
    grid-template-columns: 20px auto;
    flex: 0 0 auto;
    min-height: 38px;
  }

  .side-actions {
    display: none;
  }

  .shell-header {
    position: static;
    min-height: 56px;
  }

  .shell-project-chip {
    max-width: 46vw;
  }
}

@media (max-width: 640px) {
  .shell-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .shell-project-chip {
    max-width: 100%;
  }
}

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

.release-notes {
  display: grid;
  gap: 14px;
  max-height: min(68vh, 760px);
  overflow-y: auto;
  padding-right: 2px;
}

.release-note {
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--v2-border, #d7e1ec);
  border-radius: 8px;
  background: #fff;
}

.release-note header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.release-note header div {
  display: grid;
  gap: 4px;
}

.release-note strong {
  color: var(--v2-text-strong, #0f172a);
  font-size: 16px;
}

.release-note span,
.release-note li {
  color: var(--v2-text-muted, #64748b);
  line-height: 1.7;
}

.release-note ul {
  display: grid;
  gap: 6px;
  margin: 0;
  padding-left: 20px;
}
</style>
