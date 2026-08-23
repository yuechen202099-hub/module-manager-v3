<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import {
  fetchCollectorTerminalWorkbench,
  fetchCollectorTransferRuns,
  fetchCollectorWorkbench,
  setCollectorWorkbenchItemCompleted,
} from '@/api/services'
import type {
  CollectorTerminalWorkbench,
  CollectorTransferRun,
  CollectorWorkbenchItem,
  CollectorWorkbenchPhotoSlot,
  CollectorWorkbenchSummary,
} from '@/api/types'
import Code128Barcode from '@/components/Code128Barcode.vue'
import { useWorkspaceStore } from '@/stores/workspace'

type WorkbenchMode = 'install' | 'removal'
type RecoverableActionKind = 'completion' | 'load'
type CompletionActionContext = {
  advance: boolean
  completed: boolean
  itemId: string
  projectId: string
  runId: string
  terminalId: string
  wasCompleted: boolean
}

const workspace = useWorkspaceStore()
const projectId = ref('')
const loadedProjectId = ref('')
const runs = ref<CollectorTransferRun[]>([])
const runId = ref('')
const loadedRunId = ref('')
const summary = ref<CollectorWorkbenchSummary | null>(null)
const terminalId = ref('')
const loadedTerminalId = ref('')
const terminalDetail = ref<CollectorTerminalWorkbench | null>(null)
const mode = ref<WorkbenchMode>('install')
const activeItemId = ref('')
const loading = ref(false)
const actionPending = ref(false)
const errorMessage = ref('')
const retryAction = ref<null | (() => Promise<void>)>(null)
const retryActionKind = ref<RecoverableActionKind | null>(null)
const viewportWidth = ref(typeof window === 'undefined' ? 1440 : window.innerWidth)
let loadGeneration = 0

const selectedTerminal = computed(() => summary.value?.terminals.find((terminal) => terminal.id === terminalId.value) || null)
const installItems = computed(() => terminalDetail.value?.items.filter((item) => item.kind === 'meter_install') || [])
const removalItems = computed(() => terminalDetail.value?.items.filter((item) => item.kind === 'collector_removal') || [])
const modeItems = computed(() => mode.value === 'install' ? installItems.value : removalItems.value)
const activeItem = computed<CollectorWorkbenchItem | null>(() => (
  modeItems.value.find((item) => item.id === activeItemId.value) || modeItems.value[0] || null
))
const activeIndex = computed(() => Math.max(0, modeItems.value.findIndex((item) => item.id === activeItem.value?.id)))
const activeBlockingReasons = computed(() => completionBlockingReasons(activeItem.value))
const activeItemCanComplete = computed(() => Boolean(activeItem.value) && activeBlockingReasons.value.length === 0)
const terminalProgress = computed(() => selectedTerminal.value
  ? `${selectedTerminal.value.completed_count} / ${selectedTerminal.value.total_count}`
  : '0 / 0')
const progressWidth = computed(() => `${Math.max(0, Math.min(100, selectedTerminal.value?.progress || 0))}%`)
const workbenchColumns = computed(() => {
  if (viewportWidth.value <= 900) return 'minmax(190px, 230px) minmax(0, 1fr)'
  if (viewportWidth.value <= 1180) return '230px minmax(0, 1fr)'
  return '250px minmax(0, 1fr) 270px'
})
const controlsGridColumn = computed(() => viewportWidth.value <= 1180 ? '1 / -1' : '')

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  window.addEventListener('resize', handleResize)
  void bootstrapWorkspace()
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('resize', handleResize)
})

function handleResize() {
  viewportWidth.value = window.innerWidth
}

async function bootstrapWorkspace() {
  loading.value = true
  clearRecoverableLoadError()
  try {
    if (!workspace.projects.length) await workspace.loadProjects()
    projectId.value = workspace.activeProject?.id || workspace.projects[0]?.id || ''
    if (projectId.value) await loadRuns(projectId.value)
    else loading.value = false
  } catch (error) {
    loading.value = false
    setRecoverableError(error, '项目列表加载失败，请重试', bootstrapWorkspace)
  }
}

async function loadRuns(targetProjectId = projectId.value) {
  if (actionPending.value) {
    projectId.value = loadedProjectId.value
    return
  }
  if (!targetProjectId) return
  const generation = ++loadGeneration
  loading.value = true
  clearRecoverableLoadError()
  try {
    const nextRuns = await fetchCollectorTransferRuns(targetProjectId)
    if (generation !== loadGeneration) return
    const nextRunId = nextRuns[0]?.id || ''
    let nextSummary: CollectorWorkbenchSummary | null = null
    let nextTerminalId = ''
    let nextDetail: CollectorTerminalWorkbench | null = null
    if (nextRunId) {
      nextSummary = await fetchCollectorWorkbench(nextRunId)
      if (generation !== loadGeneration) return
      nextTerminalId = nextSummary.terminals[0]?.id || ''
      if (nextTerminalId) nextDetail = await fetchCollectorTerminalWorkbench(nextRunId, nextTerminalId)
      if (generation !== loadGeneration) return
    }
    projectId.value = targetProjectId
    loadedProjectId.value = targetProjectId
    runs.value = nextRuns
    runId.value = nextRunId
    loadedRunId.value = nextRunId
    summary.value = nextSummary
    terminalId.value = nextTerminalId
    loadedTerminalId.value = nextTerminalId
    applyTerminalDetail(nextDetail)
  } catch (error) {
    if (generation !== loadGeneration) return
    projectId.value = loadedProjectId.value
    setRecoverableError(error, '项目批次加载失败，请重试', () => loadRuns(targetProjectId))
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

async function loadWorkbench(targetRunId = runId.value) {
  if (actionPending.value) {
    runId.value = loadedRunId.value
    return
  }
  if (!targetRunId) return
  const generation = ++loadGeneration
  loading.value = true
  clearRecoverableLoadError()
  try {
    const nextSummary = await fetchCollectorWorkbench(targetRunId)
    if (generation !== loadGeneration) return
    const nextTerminalId = nextSummary.terminals[0]?.id || ''
    const nextDetail = nextTerminalId
      ? await fetchCollectorTerminalWorkbench(targetRunId, nextTerminalId)
      : null
    if (generation !== loadGeneration) return
    runId.value = targetRunId
    loadedRunId.value = targetRunId
    summary.value = nextSummary
    terminalId.value = nextTerminalId
    loadedTerminalId.value = nextTerminalId
    applyTerminalDetail(nextDetail)
  } catch (error) {
    if (generation !== loadGeneration) return
    runId.value = loadedRunId.value
    setRecoverableError(error, '工作台批次加载失败，请重试', () => loadWorkbench(targetRunId))
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

async function loadTerminal(targetTerminalId = terminalId.value) {
  if (actionPending.value) {
    terminalId.value = loadedTerminalId.value
    return
  }
  if (!runId.value || !targetTerminalId) return
  const generation = ++loadGeneration
  loading.value = true
  clearRecoverableLoadError()
  try {
    const nextDetail = await fetchCollectorTerminalWorkbench(runId.value, targetTerminalId)
    if (generation !== loadGeneration) return
    terminalId.value = targetTerminalId
    loadedTerminalId.value = targetTerminalId
    applyTerminalDetail(nextDetail)
  } catch (error) {
    if (generation !== loadGeneration) return
    terminalId.value = loadedTerminalId.value
    setRecoverableError(error, '终端资料加载失败，请重试', () => loadTerminal(targetTerminalId))
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

function applyTerminalDetail(nextDetail: CollectorTerminalWorkbench | null) {
  terminalDetail.value = nextDetail
  const hasInstall = nextDetail?.items.some((item) => item.kind === 'meter_install') || false
  mode.value = hasInstall ? 'install' : 'removal'
  const items = nextDetail?.items.filter((item) => item.kind === (hasInstall ? 'meter_install' : 'collector_removal')) || []
  activeItemId.value = items[0]?.id || ''
}

function clearRecoverableError() {
  errorMessage.value = ''
  retryAction.value = null
  retryActionKind.value = null
}

function clearRecoverableLoadError() {
  if (retryActionKind.value !== 'completion') clearRecoverableError()
}

function setRecoverableError(
  error: unknown,
  fallback: string,
  retry: () => Promise<void>,
  kind: RecoverableActionKind = 'load',
) {
  errorMessage.value = error instanceof Error ? error.message : fallback
  retryAction.value = retry
  retryActionKind.value = kind
}

function selectMode(nextMode: WorkbenchMode) {
  if (actionPending.value) return
  mode.value = nextMode
  activeItemId.value = (nextMode === 'install' ? installItems.value : removalItems.value)[0]?.id || ''
}

function moveItem(delta: number) {
  if (actionPending.value) return
  moveItemWithinCurrentContext(delta)
}

function moveItemWithinCurrentContext(delta: number) {
  if (!modeItems.value.length) return
  const nextIndex = Math.max(0, Math.min(modeItems.value.length - 1, activeIndex.value + delta))
  activeItemId.value = modeItems.value[nextIndex]?.id || ''
}

function selectItem(itemId: string) {
  if (!actionPending.value) activeItemId.value = itemId
}

function completionContextIsDisplayed(context: CompletionActionContext) {
  return projectId.value === context.projectId
    && runId.value === context.runId
    && terminalId.value === context.terminalId
    && terminalDetail.value?.run_id === context.runId
    && activeItem.value?.id === context.itemId
}

async function executeCompletion(context: CompletionActionContext) {
  if (actionPending.value) return
  actionPending.value = true
  clearRecoverableError()
  try {
    const status = await setCollectorWorkbenchItemCompleted(context.itemId, context.completed)
    if (!completionContextIsDisplayed(context)) return
    const item = terminalDetail.value?.items.find((candidate) => candidate.id === context.itemId)
    const terminal = summary.value?.terminals.find((candidate) => candidate.id === context.terminalId)
    if (!item || !terminal) return
    item.status = status.status
    if (context.wasCompleted !== (status.status === 'completed')) {
      const change = status.status === 'completed' ? 1 : -1
      terminal.completed_count = Math.max(0, terminal.completed_count + change)
      terminal.progress = terminal.total_count
        ? Math.round((terminal.completed_count / terminal.total_count) * 100)
        : 0
    }
    if (context.advance && status.status === 'completed' && activeItem.value?.id === context.itemId) {
      moveItemWithinCurrentContext(1)
    }
  } catch (error) {
    setRecoverableError(
      error,
      '工作项状态更新失败，请重试',
      () => executeCompletion(context),
      'completion',
    )
  } finally {
    actionPending.value = false
  }
}

function setCompleted(completed: boolean, advance = false) {
  const item = activeItem.value
  if (!item || actionPending.value || (completed && completionBlockingReasons(item).length > 0)) return
  void executeCompletion({
    advance,
    completed,
    itemId: item.id,
    projectId: projectId.value,
    runId: runId.value,
    terminalId: terminalId.value,
    wasCompleted: item.status === 'completed',
  })
}

function retryError() {
  const retry = retryAction.value
  if (retry) void retry()
}

function handleKeydown(event: KeyboardEvent) {
  if (actionPending.value) return
  const target = event.target
  if (target instanceof Element && target.matches('input, select, textarea, [contenteditable="true"]')) return
  if (event.key === 'ArrowLeft') {
    event.preventDefault()
    moveItem(-1)
  } else if (event.key === 'ArrowRight') {
    event.preventDefault()
    moveItem(1)
  } else if (event.key === 'Enter' && activeItem.value?.status !== 'completed' && activeItemCanComplete.value) {
    event.preventDefault()
    void setCompleted(true, true)
  }
}

function requiredPhotoSlots(item: CollectorWorkbenchItem | null): Array<{ slot: CollectorWorkbenchPhotoSlot['slot']; label: string }> {
  if (item?.kind === 'meter_install') {
    return [
      { slot: 'module_meter', label: '步骤 3 · 模块与电表合照' },
      { slot: 'after_box', label: '步骤 4 · 改造完成照片' },
    ]
  }
  if (item?.kind === 'collector_removal') {
    return [{ slot: 'collector', label: '步骤 2 · 翻拍采集器照片' }]
  }
  return []
}

function photoForItem(item: CollectorWorkbenchItem | null, slot: CollectorWorkbenchPhotoSlot['slot']) {
  return item?.photos.find((photo) => photo.slot === slot)?.photo || null
}

function photoUrlForItem(item: CollectorWorkbenchItem | null, slot: CollectorWorkbenchPhotoSlot['slot']) {
  const itemPhoto = photoForItem(item, slot)
  return itemPhoto?.preview_url || itemPhoto?.image_url || itemPhoto?.thumbnail_url || itemPhoto?.canonical_image_url || ''
}

function completionBlockingReasons(item: CollectorWorkbenchItem | null) {
  if (!item) return ['当前没有可完成的工作项']
  const reasons: string[] = []
  if (selectedTerminal.value?.status === 'blocked' || terminalDetail.value?.terminal.status === 'blocked') {
    reasons.push('终端状态为资料有阻塞')
  }
  for (const diagnostic of selectedTerminal.value?.diagnostics || []) {
    if (diagnostic.message && !reasons.includes(diagnostic.message)) reasons.push(diagnostic.message)
  }
  if (item.kind === 'meter_install') {
    if (!item.meter_barcode.trim()) reasons.push('缺少表号条形码')
    if (!item.module_barcode.trim()) reasons.push('缺少模块号条形码')
    if (!photoUrlForItem(item, 'module_meter')) reasons.push('缺少模块与电表合照')
    if (!photoUrlForItem(item, 'after_box')) reasons.push('缺少改造完成照片')
  } else {
    if (!item.collector_barcode.trim()) reasons.push('缺少最终采集器号')
    if (!photoUrlForItem(item, 'collector')) reasons.push('缺少采集器实物照片')
  }
  return reasons
}

function photoFor(slot: CollectorWorkbenchPhotoSlot['slot']) {
  return photoForItem(activeItem.value, slot)
}

function photoUrl(slot: CollectorWorkbenchPhotoSlot['slot']) {
  return photoUrlForItem(activeItem.value, slot)
}
</script>

<template>
  <main class="collector-workbench" :aria-busy="loading">
    <header class="page-heading">
      <div>
        <h1>甲方平台翻拍工作台</h1>
        <p>以终端为单位，按新装和拆除顺序展示可扫描条形码与大图，掌机直接对屏翻拍。</p>
      </div>
      <p class="manual-boundary">本页仅辅助掌机人工翻拍与人工录入，不会登录或自动上传甲方平台。</p>
    </header>

    <section class="selection-bar" aria-label="工作台选择">
      <label>
        <span>当前项目</span>
        <select v-model="projectId" aria-label="当前项目" :disabled="actionPending" @change="loadRuns(projectId)">
          <option v-for="project in workspace.projects" :key="project.id" :value="project.id">{{ project.name }}</option>
        </select>
      </label>
      <label>
        <span>当前批次</span>
        <select v-model="runId" aria-label="当前批次" :disabled="actionPending" @change="loadWorkbench(runId)">
          <option v-for="run in runs" :key="run.id" :value="run.id">{{ run.name }}</option>
        </select>
      </label>
      <label>
        <span>当前终端</span>
        <select v-model="terminalId" aria-label="当前终端" :disabled="actionPending" @change="loadTerminal(terminalId)">
          <option v-for="terminal in summary?.terminals || []" :key="terminal.id" :value="terminal.id">
            {{ terminal.terminal_code }} · {{ terminal.installation_address }}
          </option>
        </select>
      </label>
    </section>

    <aside v-if="errorMessage" class="recoverable-error" role="alert">
      <span>{{ errorMessage }}</span>
      <button type="button" data-testid="retry-error" @click="retryError">重试</button>
    </aside>

    <section class="workspace">
      <header class="workspace-header">
        <div class="crumb">
          当前终端：<strong>{{ selectedTerminal?.terminal_code || '未选择' }} · {{ selectedTerminal?.installation_address || '请选择终端' }}</strong>
          <span v-if="selectedTerminal"> / {{ selectedTerminal.status === 'blocked' ? '资料有阻塞' : '资料可翻拍' }}</span>
        </div>
        <div class="progress">
          <span>完成 {{ terminalProgress }}</span>
          <div class="progress-track" aria-hidden="true"><div class="progress-fill" :style="{ width: progressWidth }"></div></div>
        </div>
      </header>

      <div class="transfer-grid" :style="{ gridTemplateColumns: workbenchColumns }">
        <aside class="terminal-side" data-region="queue" aria-label="终端工作项队列">
          <div class="mode-switch">
            <button class="mode-button" :class="{ active: mode === 'install' }" data-testid="mode-install" type="button" :disabled="actionPending" @click="selectMode('install')">
              新装 {{ installItems.length }}
            </button>
            <button class="mode-button" :class="{ active: mode === 'removal' }" data-testid="mode-removal" type="button" :disabled="actionPending" @click="selectMode('removal')">
              拆除 {{ removalItems.length }}
            </button>
          </div>
          <div class="item-list">
            <button
              v-for="(item, index) in modeItems"
              :key="item.id"
              type="button"
              class="work-item"
              :class="{ active: item.id === activeItem?.id }"
              :disabled="actionPending"
              @click="selectItem(item.id)"
            >
              <strong>{{ String(index + 1).padStart(2, '0') }} · {{ item.kind === 'meter_install' ? item.meter_no : item.collector_barcode }}</strong>
              <small>{{ item.status === 'completed' ? '已完成' : item.id === activeItem?.id ? '当前翻拍' : '待处理' }}</small>
            </button>
          </div>
        </aside>

        <section class="transfer-main" data-region="canvas" aria-label="当前翻拍资料">
          <template v-if="activeItem">
            <div class="record-title">
              <div>
                <h2>{{ activeItem.kind === 'meter_install' ? '新装资料' : '拆除资料' }} · 第 {{ activeIndex + 1 }} / {{ modeItems.length }} 条</h2>
                <p v-if="activeItem.kind === 'meter_install'">请先扫表号和模块号，再依次翻拍两张照片。</p>
                <p v-else>扫描最终采集器号后，直接翻拍已绑定的实物照片。</p>
              </div>
              <div class="record-chips">
                <span v-if="activeItem.status === 'completed'" class="record-chip">已完成</span>
                <span class="record-chip" :class="{ incomplete: !activeItemCanComplete }">
                  {{ activeItemCanComplete ? '资料完整' : '资料不完整' }}
                </span>
              </div>
            </div>

            <ul v-if="activeBlockingReasons.length" class="blocking-reasons" data-testid="blocking-reasons">
              <li v-for="reason in activeBlockingReasons" :key="reason">{{ reason }}</li>
            </ul>

            <div v-if="activeItem.kind === 'meter_install'" class="barcode-row">
              <div class="barcode-card">
                <label>步骤 1 · 扫描表号</label>
                <Code128Barcode :value="activeItem.meter_barcode" label="表号 Code 128" />
              </div>
              <div class="barcode-card">
                <label>步骤 2 · 扫描模块号</label>
                <Code128Barcode :value="activeItem.module_barcode" label="模块号 Code 128" />
              </div>
            </div>
            <div v-else class="barcode-row single">
              <div class="barcode-card">
                <label>步骤 1 · 扫描最终采集器号</label>
                <Code128Barcode :value="activeItem.collector_barcode" label="最终采集器号 Code 128" />
              </div>
            </div>

            <div class="photo-grid" :class="{ single: activeItem.kind === 'collector_removal' }">
              <figure
                v-for="photoSlot in requiredPhotoSlots(activeItem)"
                :key="photoSlot.slot"
                class="photo-frame"
                :data-slot="photoSlot.slot"
              >
                <figcaption>{{ photoSlot.label }}</figcaption>
                <img
                  v-if="photoUrl(photoSlot.slot)"
                  :src="photoUrl(photoSlot.slot)"
                  :alt="`${photoSlot.label} · ${photoFor(photoSlot.slot)?.id || '已绑定照片'}`"
                  style="object-fit: contain"
                />
                <div v-else class="photo-missing">该槽位缺少已绑定照片</div>
              </figure>
            </div>
          </template>
          <div v-else class="empty-state">当前终端没有可翻拍工作项</div>
        </section>

        <aside
          class="transfer-controls"
          data-region="controls"
          aria-label="终端进度与操作"
          :style="{ gridColumn: controlsGridColumn }"
        >
          <section class="control-section">
            <h3>终端进度</h3>
            <div class="stat-grid">
              <div class="stat"><strong>{{ installItems.length }}</strong><small>新装总数</small></div>
              <div class="stat"><strong>{{ removalItems.length }}</strong><small>拆除总数</small></div>
              <div class="stat"><strong>{{ selectedTerminal?.completed_count || 0 }}</strong><small>已完成</small></div>
              <div class="stat"><strong>{{ selectedTerminal?.total_count || 0 }}</strong><small>总工作项</small></div>
            </div>
          </section>
          <section class="control-section">
            <h3>当前操作</h3>
            <div class="control-actions navigation-actions">
              <button type="button" class="secondary" aria-label="上一条" :disabled="activeIndex <= 0 || actionPending" @click="moveItem(-1)">上一条</button>
              <button type="button" class="secondary" aria-label="下一条" :disabled="activeIndex >= modeItems.length - 1 || actionPending" @click="moveItem(1)">下一条</button>
            </div>
            <div class="control-actions">
              <button
                v-if="activeItem?.status !== 'completed'"
                type="button"
                class="primary"
                data-testid="complete-and-next"
                :disabled="!activeItem || !activeItemCanComplete || actionPending"
                @click="setCompleted(true, true)"
              >
                标记完成并下一条
              </button>
              <button
                v-else
                type="button"
                class="secondary"
                data-testid="undo-completion"
                :disabled="actionPending"
                @click="setCompleted(false)"
              >
                撤销完成
              </button>
            </div>
            <p class="key-hint">键盘快捷键<br />← 上一条　→ 下一条<br />Enter 完成</p>
          </section>
        </aside>
      </div>
    </section>
  </main>
</template>

<style scoped>
.collector-workbench { min-height: 100%; padding: 28px; background: #f4f6f2; color: #17211b; font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif; }
button, select { font-family: inherit; }
.page-heading { display: flex; max-width: 1380px; align-items: flex-end; justify-content: space-between; gap: 24px; margin: 0 auto 18px; }
.page-heading h1 { margin: 0 0 7px; font-size: 26px; letter-spacing: -0.02em; }
.page-heading p { margin: 0; color: #68746c; font-size: 14px; }
.manual-boundary { max-width: 430px; padding: 8px 11px; border: 1px solid #dfe6df; border-radius: 9px; background: #fff; text-align: right; }
.selection-bar { display: grid; max-width: 1380px; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 0 auto 12px; }
.selection-bar label { display: grid; gap: 5px; color: #68746c; font-size: 12px; font-weight: 700; }
.selection-bar select { width: 100%; min-height: 38px; padding: 7px 10px; border: 1px solid #dfe6df; border-radius: 9px; background: #fff; color: #17211b; font-size: 13px; }
.recoverable-error { display: flex; max-width: 1380px; align-items: center; justify-content: space-between; gap: 12px; margin: 0 auto 12px; padding: 10px 12px; border: 1px solid #e6b5b0; border-radius: 9px; background: #fff0ee; color: #9f3630; font-size: 13px; }
.recoverable-error button { padding: 6px 11px; border: 1px solid #9f3630; border-radius: 7px; background: #fff; color: #9f3630; cursor: pointer; font-size: 12px; font-weight: 700; }
.workspace { max-width: 1380px; margin: 0 auto; overflow: hidden; border: 1px solid #dfe6df; border-radius: 16px; background: #fff; box-shadow: 0 14px 32px rgba(31, 48, 38, 0.07); }
.workspace-header { display: flex; min-height: 66px; align-items: center; justify-content: space-between; gap: 18px; padding: 14px 18px; border-bottom: 1px solid #dfe6df; }
.crumb { color: #68746c; font-size: 14px; }
.crumb strong { color: #17211b; }
.progress { display: flex; align-items: center; gap: 10px; color: #68746c; font-size: 13px; }
.progress-track { width: 170px; height: 7px; overflow: hidden; border-radius: 20px; background: #e4e9e4; }
.progress-fill { height: 100%; border-radius: inherit; background: #176b43; }
.transfer-grid { display: grid; min-height: 690px; grid-template-columns: 250px minmax(0, 1fr) 270px; }
.terminal-side, .transfer-controls { padding: 18px; background: #f9faf8; }
.terminal-side { border-right: 1px solid #dfe6df; }
.transfer-controls { border-left: 1px solid #dfe6df; }
.mode-switch { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; padding: 4px; margin-bottom: 16px; border-radius: 10px; background: #e9eeea; }
.mode-button { padding: 9px; border: 0; border-radius: 7px; background: transparent; color: #68746c; cursor: pointer; font-size: 13px; font-weight: 700; }
.mode-button.active { background: #fff; box-shadow: 0 2px 8px rgba(20, 40, 25, 0.08); color: #17211b; }
.item-list { display: grid; max-height: 560px; gap: 7px; overflow: auto; }
.work-item { padding: 10px; border: 1px solid #dfe6df; border-radius: 9px; background: #fff; color: #17211b; cursor: pointer; text-align: left; }
.work-item.active { border-color: #176b43; box-shadow: inset 3px 0 #176b43; }
.work-item strong, .work-item small { display: block; overflow-wrap: anywhere; }
.work-item strong { font-size: 13px; }
.work-item small { margin-top: 3px; color: #68746c; font-size: 12px; }
.transfer-main { min-width: 0; padding: 22px; background: #fff; }
.record-title { display: flex; align-items: flex-start; justify-content: space-between; gap: 15px; margin-bottom: 17px; }
.record-title h2 { margin: 0 0 5px; font-size: 21px; }
.record-title p { margin: 0; color: #68746c; font-size: 13px; }
.record-chips { display: flex; flex: none; align-items: center; gap: 7px; }
.record-chip { flex: none; padding: 7px 11px; border-radius: 999px; background: #e9f5ee; color: #176b43; font-size: 12px; font-weight: 800; }
.record-chip.incomplete { background: #fff0ee; color: #9f3630; }
.blocking-reasons { padding: 10px 12px 10px 30px; margin: -5px 0 16px; border: 1px solid #e6b5b0; border-radius: 9px; background: #fff0ee; color: #9f3630; font-size: 13px; line-height: 1.6; }
.barcode-row, .photo-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.barcode-row { margin-bottom: 16px; }
.barcode-row.single, .photo-grid.single { grid-template-columns: minmax(0, 520px); }
.barcode-card { min-width: 0; padding: 13px; border: 1px solid #dfe6df; border-radius: 12px; background: #fbfcfa; }
.barcode-card > label { display: block; margin-bottom: 8px; color: #68746c; font-size: 12px; }
.photo-frame { display: flex; min-width: 0; min-height: 330px; flex-direction: column; overflow: hidden; margin: 0; border: 1px solid #dfe6df; border-radius: 12px; background: #eef1ed; }
.photo-frame figcaption { padding: 10px 12px; border-bottom: 1px solid #dfe6df; background: #fff; font-size: 13px; font-weight: 700; }
.photo-frame img { width: 100%; min-height: 0; flex: 1; object-fit: contain; background: #eef1ed; }
.photo-grid.single .photo-frame { min-height: 430px; }
.photo-missing, .empty-state { display: grid; min-height: 260px; place-items: center; padding: 18px; color: #9f3630; text-align: center; }
.control-section { padding-bottom: 16px; margin-bottom: 16px; border-bottom: 1px solid #dfe6df; }
.control-section h3 { margin: 0 0 12px; font-size: 15px; }
.stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.stat { padding: 10px; border: 1px solid #dfe6df; border-radius: 9px; background: #fff; }
.stat strong, .stat small { display: block; }
.stat strong { font-size: 18px; }
.stat small, .key-hint { color: #68746c; font-size: 12px; }
.key-hint { line-height: 1.7; }
.control-actions { display: grid; gap: 9px; margin-bottom: 9px; }
.navigation-actions { grid-template-columns: 1fr 1fr; }
.primary, .secondary { min-height: 40px; padding: 9px 12px; border-radius: 9px; cursor: pointer; font-size: 13px; font-weight: 700; }
.primary { border: 1px solid #176b43; background: #176b43; color: #fff; }
.secondary { border: 1px solid #dfe6df; background: #fff; color: #17211b; }
.primary:disabled, .secondary:disabled { cursor: not-allowed; opacity: 0.5; }
@media (max-width: 1180px) {
  .page-heading { align-items: flex-start; flex-direction: column; gap: 10px; }
  .manual-boundary { max-width: none; text-align: left; }
  .transfer-grid { grid-template-columns: 230px minmax(0, 1fr); }
  .transfer-controls { grid-column: 1 / -1; border-top: 1px solid #dfe6df; border-left: 0; }
}
@media (max-width: 900px) {
  .collector-workbench { padding: 16px; overflow-x: clip; }
  .selection-bar { grid-template-columns: 1fr; }
  .workspace-header { align-items: flex-start; flex-direction: column; }
  .transfer-grid { grid-template-columns: minmax(190px, 230px) minmax(0, 1fr); }
  .barcode-row, .photo-grid { grid-template-columns: 1fr; }
}
</style>
