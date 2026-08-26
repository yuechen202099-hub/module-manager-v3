<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  fetchGlobalCollectorTerminals,
  openReviewWorkbenchTerminal,
  refreshGlobalCollectorTerminal,
  replaceGlobalTerminalMissing,
  rollbackCollectorAssignment,
  setCollectorWorkbenchItemCompleted,
} from '@/api/services'
import type { CollectorRequirementWorkbenchRow, GlobalCollectorTerminalCandidate, ReviewWorkbenchMeter, ReviewWorkbenchOpenResult } from '@/api/types'
import Code128Barcode from '@/components/Code128Barcode.vue'
import DataCenterGroupReviewPanel from '@/components/data-center/DataCenterGroupReviewPanel.vue'
import { canMutateRephoto, candidateLabel, completionBlockers, meterCompletionBlockers, normalizeMeterPhotoSlots } from '@/features/collectorTransfer/state'

const candidates = ref<GlobalCollectorTerminalCandidate[]>([])
const terminalInput = ref('')
const opened = ref<ReviewWorkbenchOpenResult | null>(null)
const selectedGroupId = ref('')
const loading = ref(false)
const mutationPending = ref(false)
const errorMessage = ref('')
let searchSerial = 0
let openSerial = 0
let searchTimer = 0

const constructedMeters = computed(() => opened.value?.meters.filter((meter) => meter.construction_state === 'constructed') || [])
const unconstructedMeters = computed(() => opened.value?.meters.filter((meter) => meter.construction_state === 'unconstructed') || [])
const selectedMeter = computed<ReviewWorkbenchMeter | null>(() => constructedMeters.value.find((meter) => meter.group_id === selectedGroupId.value) || constructedMeters.value[0] || null)
const rephoto = computed(() => opened.value?.rephoto || null)
const sourceChanged = computed(() => Boolean(rephoto.value?.source_changed))
const reviewUnlocked = computed(() => Boolean(opened.value && opened.value.review_required_count === 0 && canMutateRephoto({ rephoto: rephoto.value, source_changed: rephoto.value?.source_changed })))
const mutable = computed(() => reviewUnlocked.value && !mutationPending.value)
const deduplicatedCollectors = computed(() => {
  const rows = rephoto.value?.collector_items || []
  const result = new Map<string, CollectorRequirementWorkbenchRow>()
  for (const row of rows) {
    const current = result.get(row.original_collector_no)
    if (!current || collectorPriority(row) > collectorPriority(current)) result.set(row.original_collector_no, row)
  }
  return [...result.values()]
})
const terminalBlockers = computed(() => {
  if (!opened.value) return []
  if (sourceChanged.value) return ['来源资料已变化，请刷新后继续']
  if (opened.value.review_required_count) return ['终端审阅未完成', ...opened.value.review_blockers.flatMap((item) => item.codes)]
  if (opened.value.workflow_state === 'pool_shortage') return ['替换池数量不足']
  if (opened.value.workflow_state === 'no_construction') return ['终端没有已施工表计']
  return []
})

onMounted(() => {
  const groupId = new URLSearchParams(window.location.search).get('group_id') || ''
  void loadCandidates(groupId)
})
onBeforeUnmount(() => { if (searchTimer) window.clearTimeout(searchTimer) })

function collectorPriority(row: CollectorRequirementWorkbenchRow) {
  return row.physical_state === 'replaced' ? 3 : row.physical_state === 'missing' ? 2 : 1
}
function workflowLabel(state: string) {
  return ({ no_construction: '无已施工表计', needs_review: '终端审阅未完成', blocked: '终端资料阻断', needs_replacement: '需要替换采集器', pool_shortage: '替换池不足', ready: '可翻拍', in_progress: '翻拍进行中', completed: '已完成' } as Record<string, string>)[state] || state
}
function imageUrl(photo: { image_url?: string; preview_url?: string; thumbnail_url?: string; canonical_image_url?: string } | null) {
  return photo?.preview_url || photo?.image_url || photo?.thumbnail_url || photo?.canonical_image_url || ''
}
function selectMeter(meter: ReviewWorkbenchMeter) { if (meter.construction_state === 'constructed') selectedGroupId.value = meter.group_id }
function showError(error: unknown) { errorMessage.value = error instanceof Error ? error.message : '请求失败，请重试' }
async function loadCandidates(query = '') {
  const serial = ++searchSerial
  loading.value = true
  try {
    const response = await fetchGlobalCollectorTerminals({ query, page: 1, pageSize: 50, includeBlocked: true })
    if (serial !== searchSerial) return
    candidates.value = response.items
    const matchingGroup = query ? response.items.filter((item) => item.selectable) : []
    const candidate = matchingGroup.length === 1 ? matchingGroup[0] : response.items.find((item) => item.selectable)
    if (candidate) await openCandidate(candidate)
    else if (query) errorMessage.value = '未找到唯一可授权终端，请重新搜索。'
  } catch (error) {
    if (serial === searchSerial) showError(error)
  } finally {
    if (serial === searchSerial) loading.value = false
  }
}
function searchCandidates() {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = 0
  ++searchSerial
  void loadCandidates(terminalInput.value.trim())
}
function scheduleSearch() {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(searchCandidates, 250)
}
async function openCandidate(candidate: GlobalCollectorTerminalCandidate) {
  const serial = ++openSerial
  loading.value = true
  errorMessage.value = ''
  try {
    const next = await openReviewWorkbenchTerminal({ terminal_key: candidate.terminal_key, source_revision: candidate.source_revision })
    if (serial !== openSerial) return
    opened.value = next
    terminalInput.value = candidateLabel({ ...candidate, terminal_code: next.terminal.terminal_code, installation_address: next.terminal.installation_address })
    selectedGroupId.value = next.meters.find((meter) => meter.construction_state === 'constructed')?.group_id || ''
  } catch (error) {
    if (serial === openSerial) showError(error)
  } finally {
    if (serial === openSerial) loading.value = false
  }
}
async function reopenCurrent() {
  const candidate = candidates.value.find((item) => item.terminal_key === opened.value?.terminal.terminal_key)
  if (candidate) await openCandidate({ ...candidate, source_revision: opened.value?.source_revision || candidate.source_revision })
}
async function runMutation(action: () => Promise<unknown>) {
  if (!mutable.value) return
  mutationPending.value = true
  errorMessage.value = ''
  try { await action(); await reopenCurrent() } catch (error) { showError(error) } finally { mutationPending.value = false }
}
function replaceMissing() {
  const terminalId = rephoto.value?.terminal.id
  if (!terminalId || opened.value?.workflow_state === 'pool_shortage') return
  void runMutation(() => replaceGlobalTerminalMissing(terminalId))
}
function rollback(row: CollectorRequirementWorkbenchRow) {
  if (!row.assignment_id) return
  void runMutation(() => rollbackCollectorAssignment(row.assignment_id!))
}
function refresh() {
  const terminalId = rephoto.value?.terminal.id
  if (!terminalId) return
  void runMutation(() => refreshGlobalCollectorTerminal(terminalId))
}
function completeTerminal() {
  const item = rephoto.value?.collector_items.find((row) => row.workbench_item_id)
  if (!item?.workbench_item_id || opened.value?.workflow_state === 'pool_shortage' || completionBlockers(item).length) return
  void runMutation(() => setCollectorWorkbenchItemCompleted(item.workbench_item_id!, true))
}
function completeMeter(item: NonNullable<ReviewWorkbenchOpenResult['rephoto']>['meter_install_items'][number]) {
  if (!item.workbench_item_id || meterCompletionBlockers(item).length) return
  void runMutation(() => setCollectorWorkbenchItemCompleted(item.workbench_item_id!, true))
}
</script>

<template>
  <main class="review-rephoto-workbench" :aria-busy="loading || mutationPending">
    <header class="page-heading"><h1>审阅与翻拍工作台</h1></header>
    <section class="terminal-search"><label for="terminal-search">输入终端号</label><input id="terminal-search" v-model="terminalInput" aria-label="输入终端号" placeholder="输入终端号" @input="scheduleSearch" /><button type="button" data-testid="search-terminal" @click="searchCandidates">搜索</button></section>
    <p v-if="errorMessage" role="alert" class="warning">{{ errorMessage }}</p>
    <template v-if="opened">
      <section class="terminal-summary"><div><strong>终端 {{ opened.terminal.terminal_code }}</strong><span>{{ opened.terminal.installation_address }}</span></div><div><span>已施工表计 {{ opened.constructed_meter_count }}</span><span>未施工表计 {{ opened.unconstructed_meter_count }}</span></div><strong :class="{ locked: !reviewUnlocked }">{{ workflowLabel(opened.workflow_state) }}</strong><ul v-if="terminalBlockers.length"><li v-for="reason in terminalBlockers" :key="reason">{{ reason }}</li></ul></section>
      <section class="workbench-grid">
        <aside class="meter-queue"><h2>已施工表计</h2><button v-for="meter in constructedMeters" :key="meter.group_id" type="button" class="meter-row" :class="{ active: meter.group_id === selectedMeter?.group_id }" @click="selectMeter(meter)"><strong>{{ meter.meter_no }}</strong><span>{{ meter.module_no }}</span><em>{{ meter.review_ready ? '通过' : '终端审阅未完成' }}</em></button><h2>未施工表计</h2><div v-for="meter in unconstructedMeters" :key="meter.group_id" class="meter-row unconstructed"><strong>{{ meter.meter_no }}</strong><span>未施工，不参与本次翻拍</span></div></aside>
        <section class="evidence-stage"><h2>当前资料 / 翻拍</h2><DataCenterGroupReviewPanel v-if="selectedMeter" :group-id="selectedMeter.group_id" :rephoto-item="rephoto?.meter_install_items.find((item) => item.meter_no === selectedMeter?.meter_no) || null" default-stage="source" @review-decided="reopenCurrent" @updated="reopenCurrent" /><section v-if="rephoto" class="slot-summary"><article v-for="item in rephoto.meter_install_items" :key="item.meter_item_id" class="meter-slots"><header>{{ item.meter_no }} / {{ item.module_no }}</header><Code128Barcode :value="item.meter_barcode" /><Code128Barcode :value="item.module_barcode" /><figure v-for="slot in normalizeMeterPhotoSlots(item.photos)" :key="slot.slot" class="rephoto-slot"><figcaption>{{ slot.label }}</figcaption><img v-if="imageUrl(slot.photo)" :src="imageUrl(slot.photo)" :alt="slot.label" /><span v-else>暂无照片</span></figure><button type="button" class="rephoto-mutation" :disabled="!mutable || meterCompletionBlockers(item).length > 0" @click="completeMeter(item)">完成</button></article></section></section>
        <aside class="review-actions"><h2>审阅与操作</h2><p v-for="reason in terminalBlockers" :key="reason" class="lock-reason">{{ reason }}</p><button type="button" class="rephoto-mutation" data-testid="refresh-terminal" :disabled="!mutable || !sourceChanged" @click="refresh">刷新</button><button type="button" class="rephoto-mutation" data-testid="replace-all-missing" :disabled="!mutable || opened.workflow_state === 'pool_shortage' || !(rephoto?.pool_summary.required)" @click="replaceMissing">随机替换全部缺失采集器</button><button type="button" class="rephoto-mutation" data-testid="complete-terminal" :disabled="!mutable || opened.workflow_state === 'pool_shortage'" @click="completeTerminal">完成</button></aside>
      </section>
      <section v-if="rephoto" class="collector-rail"><h2>采集器</h2><article v-for="row in deduplicatedCollectors" :key="row.original_collector_no" class="collector-card"><strong>{{ row.original_collector_no }}</strong><span>{{ row.physical_state === 'present' ? '有实物' : row.physical_state === 'missing' ? '无实物' : '已替换' }}</span><span v-if="row.final_collector_no && row.final_collector_no !== row.original_collector_no">{{ row.final_collector_no }}</span><Code128Barcode v-if="row.collector_barcode" :value="row.collector_barcode" /><button v-if="row.assignment_id" type="button" class="rephoto-mutation" data-testid="rollback-assignment" :disabled="!mutable" @click="rollback(row)">回滚</button></article></section>
    </template>
  </main>
</template>

<style scoped>
.review-rephoto-workbench { display: grid; gap: 14px; min-width: 0; max-width: 1440px; margin: 0 auto; padding: 20px; color: var(--v2-text, #172033); }
.page-heading h1 { margin: 0; font-size: 22px; }.terminal-search { display: flex; gap: 8px; align-items: center; }.terminal-search input { min-width: 0; flex: 1; padding: 10px; border: 1px solid var(--v2-border, #dbe4ee); border-radius: 7px; }.terminal-search button, .rephoto-mutation, .meter-row { min-height: 40px; border: 1px solid var(--v2-border, #dbe4ee); border-radius: 7px; background: #fff; color: inherit; cursor: pointer; }.terminal-search button { padding: 0 18px; color: #fff; background: var(--v2-accent, #2563eb); border-color: var(--v2-accent, #2563eb); }.terminal-summary, .meter-queue, .evidence-stage, .review-actions, .collector-rail { display: grid; gap: 10px; padding: 14px; border: 1px solid var(--v2-border, #dbe4ee); border-radius: 8px; background: #fff; min-width: 0; }.terminal-summary { grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; }.terminal-summary div, .terminal-summary ul { display: flex; flex-wrap: wrap; gap: 10px; margin: 0; padding: 0; list-style: none; }.locked, .lock-reason, .warning { color: var(--el-color-danger, #d03050); }.workbench-grid { display: grid; grid-template-columns: minmax(210px, .72fr) minmax(420px, 1.5fr) minmax(210px, .72fr); gap: 14px; min-width: 0; }.meter-queue { align-content: start; }.meter-queue h2, .evidence-stage h2, .review-actions h2, .collector-rail h2 { margin: 0; font-size: 16px; }.meter-row { display: grid; gap: 4px; width: 100%; padding: 10px; text-align: left; }.meter-row.active { border-color: var(--v2-accent, #2563eb); outline: 1px solid var(--v2-accent, #2563eb); }.meter-row em { font-style: normal; color: var(--el-color-warning, #b76b00); }.unconstructed { opacity: .62; background: var(--v2-surface-soft, #f7f9fc); }.slot-summary, .meter-slots { display: grid; gap: 8px; }.meter-slots { grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 10px; border-top: 1px solid var(--v2-border, #dbe4ee); }.meter-slots header { grid-column: 1 / -1; }.rephoto-slot { display: grid; gap: 6px; margin: 0; padding: 8px; border: 1px solid var(--v2-border, #dbe4ee); border-radius: 6px; min-width: 0; }.rephoto-slot img { width: 100%; height: 150px; object-fit: contain; }.meter-slots .rephoto-mutation { grid-column: 1 / -1; }.collector-rail { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }.collector-rail h2 { grid-column: 1 / -1; }.collector-card { display: grid; gap: 7px; padding: 10px; border: 1px solid var(--v2-border, #dbe4ee); border-radius: 7px; min-width: 0; }.rephoto-mutation:disabled { cursor: not-allowed; opacity: .55; }
@media (max-width: 700px) { .review-rephoto-workbench { padding: 12px; overflow-x: hidden; }.terminal-search, .terminal-summary, .workbench-grid { grid-template-columns: 1fr; flex-direction: column; align-items: stretch; }.workbench-grid { display: grid; }.terminal-summary { display: grid; }.meter-slots { grid-template-columns: 1fr; }.collector-rail { grid-template-columns: 1fr; }.terminal-search button { width: 100%; } }
</style>
