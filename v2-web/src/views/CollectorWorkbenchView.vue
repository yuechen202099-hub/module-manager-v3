<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import {
  fetchGlobalCollectorTerminal,
  fetchGlobalCollectorTerminals,
  openGlobalCollectorTerminal,
  refreshGlobalCollectorTerminal,
  replaceGlobalTerminalMissing,
  rollbackCollectorAssignment,
  setCollectorWorkbenchItemCompleted,
} from '@/api/services'
import type { CollectorRequirementWorkbenchRow, GlobalCollectorTerminalCandidate, GlobalCollectorTerminalDetail } from '@/api/types'
import Code128Barcode from '@/components/Code128Barcode.vue'
import { canRefreshTerminal, canReplaceMissing, candidateLabel, completionBlockers, isCurrentRequest, meterCompletionBlockers, normalizeMeterPhotoSlots } from '@/features/collectorTransfer/state'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const candidates = ref<GlobalCollectorTerminalCandidate[]>([])
const selectedKey = ref('')
const detail = ref<GlobalCollectorTerminalDetail | null>(null)
const activeIndex = ref(0)
const loading = ref(false)
const mutationPending = ref(false)
const errorMessage = ref('')
const retryAction = ref<null | (() => Promise<void>)>(null)
let candidateRequest = 0
let selectionRequest = 0
let detailRequest = 0
let searchTimer = 0

const isAdmin = computed(() => Boolean(auth.user?.role === 'admin' || auth.user?.roles?.includes('admin')))
const collectorItems = computed(() => detail.value?.collector_items || [])
const activeItem = computed<CollectorRequirementWorkbenchRow | null>(() => collectorItems.value[activeIndex.value] || null)
const activeBlockers = computed(() => activeItem.value ? completionBlockers(activeItem.value) : ['当前没有可完成的工作项'])
const canComplete = computed(() => Boolean(activeItem.value?.workbench_item_id) && activeBlockers.value.length === 0)
const canReplace = computed(() => detail.value && canReplaceMissing(isAdmin.value, detail.value.pool_summary.available, detail.value.pool_summary.required))
const canRefresh = computed(() => detail.value && canRefreshTerminal(
  isAdmin.value,
  detail.value.source_changed,
  detail.value.completed_count,
  detail.value.collector_items.map((item) => item.assignment_id).filter((id): id is string => Boolean(id)),
))

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  void loadCandidates()
})
onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
  if (searchTimer) window.clearTimeout(searchTimer)
})

function imageUrl(photo: { image_url?: string; preview_url?: string; thumbnail_url?: string; canonical_image_url?: string } | null) {
  return photo?.preview_url || photo?.image_url || photo?.thumbnail_url || photo?.canonical_image_url || ''
}
function stateLabel(candidate: GlobalCollectorTerminalCandidate) {
  if (candidate.workflow_state === 'ready') return '可直接翻拍'
  if (candidate.workflow_state === 'needs_replacement') return `需替换 ${candidate.missing_count} 个`
  if (candidate.workflow_state === 'pool_shortage') return `池不足 ${candidate.missing_count - candidate.pool_available_count} 个`
  return '资料有阻塞'
}
function setError(error: unknown, retry: () => Promise<void>) {
  errorMessage.value = error instanceof Error ? error.message : '请求失败，请重试'
  retryAction.value = retry
}
function clearError() { errorMessage.value = ''; retryAction.value = null }
async function loadCandidates(query = '') {
  const sequence = ++candidateRequest
  const selectionAtStart = selectionRequest
  try {
    const response = await fetchGlobalCollectorTerminals({ query, page: 1, pageSize: 50, includeBlocked: isAdmin.value })
    if (!isCurrentRequest(sequence, candidateRequest) || selectionAtStart !== selectionRequest) return
    candidates.value = response.items
    const first = response.items.find((item) => item.selectable)
    if (!detail.value && first) await openCandidate(first)
  } catch (error) {
    if (isCurrentRequest(sequence, candidateRequest) && selectionAtStart === selectionRequest) setError(error, () => loadCandidates(query))
  }
}
function searchCandidates(event: Event) {
  const value = (event.target as HTMLInputElement).value
  const direct = candidates.value.find((candidate) => candidate.terminal_key === value)
  if (direct) {
    if (searchTimer) window.clearTimeout(searchTimer)
    searchTimer = 0
    candidateRequest += 1
    void openCandidate(direct)
    return
  }
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => { void loadCandidates(value) }, 250)
}
async function openCandidate(candidate: GlobalCollectorTerminalCandidate) {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = 0
  const sequence = ++selectionRequest
  loading.value = true
  try {
    const opened = await openGlobalCollectorTerminal({
      terminal_key: candidate.terminal_key,
      project_id: candidate.project_id,
      terminal_code: candidate.terminal_code,
      source_revision: candidate.source_revision,
    })
    if (!isCurrentRequest(sequence, selectionRequest)) return
    const loaded = await fetchGlobalCollectorTerminal(opened.workbench_terminal_id)
    if (!isCurrentRequest(sequence, selectionRequest)) return
    selectedKey.value = candidate.terminal_key
    detail.value = loaded
    activeIndex.value = 0
  } catch (error) {
    if (isCurrentRequest(sequence, selectionRequest)) setError(error, () => openCandidate(candidate))
  } finally {
    if (isCurrentRequest(sequence, selectionRequest)) loading.value = false
  }
}
async function reloadDetail(terminalId: string) {
  const sequence = ++detailRequest
  loading.value = true
  try {
    const loaded = await fetchGlobalCollectorTerminal(terminalId)
    if (isCurrentRequest(sequence, detailRequest) && detail.value?.terminal.id === terminalId) detail.value = loaded
  } catch (error) {
    if (isCurrentRequest(sequence, detailRequest)) setError(error, () => reloadDetail(terminalId))
  } finally {
    if (isCurrentRequest(sequence, detailRequest)) loading.value = false
  }
}
async function executeReplace(terminalId: string) {
  mutationPending.value = true; clearError()
  try { await replaceGlobalTerminalMissing(terminalId); await reloadDetail(terminalId) }
  catch (error) { setError(error, () => executeReplace(terminalId)) }
  finally { mutationPending.value = false }
}
async function replaceMissing() {
  const terminalId = detail.value?.terminal.id
  if (!terminalId || !canReplace.value || mutationPending.value) return
  await executeReplace(terminalId)
}
async function executeRefresh(terminalId: string) {
  mutationPending.value = true; clearError()
  try { await refreshGlobalCollectorTerminal(terminalId); await reloadDetail(terminalId) }
  catch (error) { setError(error, () => executeRefresh(terminalId)) }
  finally { mutationPending.value = false }
}
async function refreshTerminal() {
  const terminalId = detail.value?.terminal.id
  if (!terminalId || !canRefresh.value || mutationPending.value) return
  await executeRefresh(terminalId)
}
async function executeRollback(terminalId: string, assignmentId: string) {
  mutationPending.value = true; clearError()
  try { await rollbackCollectorAssignment(assignmentId); await reloadDetail(terminalId) }
  catch (error) { setError(error, () => executeRollback(terminalId, assignmentId)) }
  finally { mutationPending.value = false }
}
async function rollback(item: CollectorRequirementWorkbenchRow) {
  const terminalId = detail.value?.terminal.id
  const assignmentId = item.assignment_id
  if (!terminalId || !isAdmin.value || !assignmentId || mutationPending.value || !window.confirm('确认回滚这条随机替换吗？')) return
  await executeRollback(terminalId, assignmentId)
}
async function executeCompletion(terminalId: string, itemId: string, completed: boolean) {
  mutationPending.value = true; clearError()
  try { await setCollectorWorkbenchItemCompleted(itemId, completed); await reloadDetail(terminalId) }
  catch (error) { setError(error, () => executeCompletion(terminalId, itemId, completed)) }
  finally { mutationPending.value = false }
}
async function setCompleted(completed: boolean) {
  const terminalId = detail.value?.terminal.id
  const itemId = activeItem.value?.workbench_item_id
  if (!terminalId || !itemId || (completed && !canComplete.value) || mutationPending.value) return
  await executeCompletion(terminalId, itemId, completed)
}
async function completeMeter(item: GlobalCollectorTerminalDetail['meter_install_items'][number]) {
  const terminalId = detail.value?.terminal.id
  if (!terminalId || !item.workbench_item_id || meterCompletionBlockers(item).length || mutationPending.value) return
  await executeCompletion(terminalId, item.workbench_item_id, true)
}
async function reopenMeter(item: GlobalCollectorTerminalDetail['meter_install_items'][number]) {
  const terminalId = detail.value?.terminal.id
  if (!terminalId || !item.workbench_item_id || mutationPending.value) return
  await executeCompletion(terminalId, item.workbench_item_id, false)
}
function move(delta: number) { activeIndex.value = Math.max(0, Math.min(collectorItems.value.length - 1, activeIndex.value + delta)) }
function handleKeydown(event: KeyboardEvent) {
  if (event.target instanceof Element && event.target.matches('input, textarea, select')) return
  if (event.key === 'ArrowLeft') { event.preventDefault(); move(-1) }
  if (event.key === 'ArrowRight') { event.preventDefault(); move(1) }
  if (event.key === 'Enter' && activeItem.value?.status !== 'completed') { event.preventDefault(); void setCompleted(true) }
}
</script>

<template>
  <main class="collector-workbench" :aria-busy="loading">
    <header class="page-heading"><div><h1>甲方平台翻拍工作台</h1><p>按全局终端打开隐藏快照，掌机直接对屏翻拍。</p></div><p>本页仅辅助人工翻拍与人工录入，不会登录或自动上传甲方平台。</p></header>
    <label class="terminal-picker"><span>选择可翻拍终端</span><input v-model="selectedKey" list="collector-terminal-candidates" aria-label="选择可翻拍终端" placeholder="输入终端号或安装地址" @input="searchCandidates" /><datalist id="collector-terminal-candidates"><option v-for="candidate in candidates" :key="candidate.terminal_key" :value="candidate.terminal_key">{{ candidateLabel(candidate) }} · 表 {{ candidate.meter_count }} · 采集器 {{ candidate.collector_count }} · {{ stateLabel(candidate) }}</option></datalist></label>
    <aside v-if="errorMessage" role="alert" class="recoverable-error">{{ errorMessage }} <button type="button" data-testid="retry-error" @click="retryAction?.()">重试</button></aside>
    <section v-if="detail" class="workspace">
      <header><strong>{{ detail.terminal.terminal_code }} · {{ detail.terminal.installation_address }}</strong><span>完成 {{ detail.completed_count }} / {{ detail.total_count }}</span></header>
      <p v-if="detail.source_changed" class="warning">来源资料已变化；请在没有进度和有效分配时刷新快照。</p>
      <section class="pool-summary"><span>缺口 {{ detail.pool_summary.required }}</span><span>需要 {{ detail.pool_summary.required }} / 可用 {{ detail.pool_summary.available }}</span><button v-if="isAdmin" type="button" data-testid="replace-all-missing" :disabled="!canReplace || mutationPending" @click="replaceMissing">一键替换全部无实物采集器</button><button v-if="isAdmin && detail.source_changed" type="button" data-testid="refresh-terminal" :disabled="!canRefresh || mutationPending" @click="refreshTerminal">刷新来源快照</button></section>
      <section class="collector-list"><article v-for="(item, index) in collectorItems" :key="item.requirement_id" class="collector-card" :class="{ active: index === activeIndex }" @click="activeIndex = index"><h2>{{ item.original_collector_no }}</h2><template v-if="item.physical_state === 'present'"><strong>有实物</strong><p>无需网站照片，请直接拿实物翻拍</p><Code128Barcode :value="item.collector_barcode || ''" /></template><template v-else-if="item.physical_state === 'missing'"><strong>无实物</strong><p>该采集器没有实物，需先完成替换</p></template><template v-else><strong>已替换</strong><p>替换后号码：{{ item.final_collector_no }}</p><Code128Barcode :value="item.collector_barcode || ''" /><img v-if="imageUrl(item.photo)" :src="imageUrl(item.photo)" alt="替换采集器照片" /><button v-if="isAdmin && item.assignment_id" type="button" data-testid="rollback-assignment" :disabled="mutationPending" @click.stop="rollback(item)">回滚替换</button></template><ul v-if="index === activeIndex && activeBlockers.length"><li v-for="reason in activeBlockers" :key="reason">{{ reason }}</li></ul></article></section>
      <section class="meter-list"><h2>新装 {{ detail.meter_install_items.length }}</h2><article v-for="item in detail.meter_install_items" :key="item.meter_item_id"><Code128Barcode :value="item.meter_barcode" /><Code128Barcode :value="item.module_barcode" /><div class="meter-photos"><figure v-for="slot in normalizeMeterPhotoSlots(item.photos)" :key="slot.slot" :data-slot="slot.slot"><figcaption>{{ slot.label }}</figcaption><img v-if="imageUrl(slot.photo)" :src="imageUrl(slot.photo)" :alt="slot.label" /><span v-else>照片缺失</span></figure></div><button v-if="item.status === 'completed'" type="button" :data-testid="`undo-meter-${item.meter_item_id}`" :disabled="!item.workbench_item_id || mutationPending" @click="reopenMeter(item)">撤销完成</button><button v-else type="button" :data-testid="`complete-meter-${item.meter_item_id}`" :disabled="!item.workbench_item_id || meterCompletionBlockers(item).length > 0 || mutationPending" @click="completeMeter(item)">标记已翻拍</button></article></section>
      <footer class="controls"><span>拆除 {{ collectorItems.length }}</span><button type="button" aria-label="上一条" @click="move(-1)">上一条</button><button type="button" aria-label="下一条" @click="move(1)">下一条</button><button v-if="activeItem?.status === 'completed'" type="button" data-testid="undo-completion" @click="setCompleted(false)">撤销完成</button><button v-else-if="activeItem?.physical_state !== 'missing'" type="button" data-testid="complete-and-next" :disabled="!canComplete || mutationPending" @click="setCompleted(true)">标记完成并下一条</button></footer>
    </section>
    <p v-else-if="!loading" class="empty-state">请选择可翻拍终端</p>
  </main>
</template>

<style scoped>
.collector-workbench { display:grid; gap:16px; max-width:1180px; margin:0 auto; padding:24px; color:#172033; }.page-heading,.workspace>header,.pool-summary,.controls { display:flex; gap:12px; justify-content:space-between; align-items:center; }.page-heading p { color:#64748b; }.terminal-picker { display:grid; gap:6px; }.terminal-picker input { padding:10px; border:1px solid #cbd5e1; border-radius:8px; }.workspace,.collector-card,.meter-list,.pool-summary { padding:16px; border:1px solid #dbe4ee; border-radius:10px; }.collector-list { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; }.collector-card.active { outline:2px solid #2563eb; }.collector-card strong { color:#166534; }.collector-card img { display:block; max-width:100%; max-height:240px; margin-top:10px; object-fit:contain; }.warning,.recoverable-error { padding:10px; border-radius:8px; background:#fff7ed; color:#9a3412; }.controls { justify-content:flex-start; }.empty-state { color:#64748b; }
</style>
