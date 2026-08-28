<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  createReviewWorkbenchManualDemand,
  fetchGlobalCollectorTerminals,
  openReviewWorkbenchTerminal,
  refreshGlobalCollectorTerminal,
  replaceGlobalTerminalMissing,
  rollbackCollectorAssignment,
  setCollectorWorkbenchItemCompleted,
} from '@/api/services'
import type { CollectorRequirementWorkbenchRow, GlobalCollectorTerminalCandidate, ReviewWorkbenchMeter, ReviewWorkbenchOpenResult } from '@/api/types'
import Code128Barcode from '@/components/Code128Barcode.vue'
import PhotoLightbox from '@/components/PhotoLightbox.vue'
import DataCenterGroupReviewPanel from '@/components/data-center/DataCenterGroupReviewPanel.vue'
import { canMutateRephoto, completionBlockers, meterCompletionBlockers, normalizeMeterPhotoSlots } from '@/features/collectorTransfer/state'

const candidates = ref<GlobalCollectorTerminalCandidate[]>([])
const candidatePage = ref(1)
const candidateTotal = ref(0)
const lastSearchQuery = ref('')
const terminalInput = ref('')
const opened = ref<ReviewWorkbenchOpenResult | null>(null)
const selectedGroupId = ref('')
const loading = ref(false)
const mutationPending = ref(false)
const errorMessage = ref('')
const photoPreview = ref({ src: '', alt: '' })
const manualDemandQuantity = ref('')
let searchSerial = 0
let openSerial = 0
let searchTimer = 0
const candidatePageSize = 50

const rephoto = computed(() => opened.value?.rephoto || null)
const activeMeters = computed(() => {
  const completedMeterNumbers = new Set(
    (rephoto.value?.meter_install_items || [])
      .filter((item) => item.status === 'completed')
      .map((item) => item.meter_no),
  )
  return (opened.value?.meters || []).filter((meter) => !completedMeterNumbers.has(meter.meter_no))
})
const constructedMeters = computed(() => activeMeters.value.filter((meter) => meter.construction_state === 'constructed'))
const unconstructedMeters = computed(() => activeMeters.value.filter((meter) => meter.construction_state === 'unconstructed'))
const selectedMeter = computed<ReviewWorkbenchMeter | null>(() => activeMeters.value.find((meter) => meter.group_id === selectedGroupId.value) || constructedMeters.value[0] || null)
const sourceChanged = computed(() => Boolean(rephoto.value?.source_changed))
const rephotoUnlocked = computed(() => canMutateRephoto({ rephoto: rephoto.value, source_changed: rephoto.value?.source_changed }))
const mutable = computed(() => rephotoUnlocked.value && !mutationPending.value)
const selectedRephotoItem = computed(() => rephoto.value?.meter_install_items.find((item) => item.meter_no === selectedMeter.value?.meter_no && item.status !== 'completed') || null)
const parsedManualDemandQuantity = computed(() => {
  const value = String(manualDemandQuantity.value).trim()
  if (!value || !/^\d+$/.test(value)) return null
  const quantity = Number(value)
  return Number.isSafeInteger(quantity) && quantity > 0 ? quantity : null
})
const canSubmitManualDemand = computed(() => mutable.value && parsedManualDemandQuantity.value !== null)
const deduplicatedCollectors = computed(() => {
  const rows = (rephoto.value?.collector_items || []).filter((row) => row.status !== 'completed')
  const result = new Map<string, CollectorRequirementWorkbenchRow>()
  for (const row of rows) {
    const current = result.get(row.original_collector_no)
    if (!current || collectorPriority(row) > collectorPriority(current)) result.set(row.original_collector_no, row)
  }
  return [...result.values()]
})
type CollectorDisplayRow = {
  key: string
  original_collector_no: string
  physical_state: CollectorRequirementWorkbenchRow['physical_state'] | 'pending'
  final_collector_no: string | null
  collector_barcode: string | null
  photo: CollectorRequirementWorkbenchRow['photo']
  source: CollectorRequirementWorkbenchRow | null
}
const collectorRows = computed<CollectorDisplayRow[]>(() => {
  if (rephoto.value) {
    return deduplicatedCollectors.value.map((row) => ({
      key: row.requirement_id,
      original_collector_no: row.original_collector_no,
      physical_state: row.physical_state,
      final_collector_no: row.final_collector_no,
      collector_barcode: row.collector_barcode,
      photo: row.photo,
      source: row,
    }))
  }
  const numbers = new Set(constructedMeters.value.map((meter) => meter.collector_no).filter(Boolean))
  return [...numbers].map((collectorNo) => ({
    key: `pending-${collectorNo}`,
    original_collector_no: collectorNo,
    physical_state: 'pending',
    final_collector_no: null,
    collector_barcode: null,
    photo: null,
    source: null,
  }))
})
const terminalNotice = computed(() => {
  if (!opened.value) return ''
  if (sourceChanged.value) return '来源资料已变化，请刷新后继续。'
  if (opened.value.review_required_count) return '部分表计仍待审阅，分类不影响翻拍；已确认分类的表计仍可能存在资料异常。'
  if (opened.value.workflow_state === 'pool_shortage') return '采集器池数量不足，暂不能完成随机替换。'
  if (opened.value.workflow_state === 'no_construction') return '终端没有已施工表计，无需生成翻拍资料。'
  return '照片分类已完成，可以按表计查看翻拍资料。'
})

onMounted(() => {
  const groupId = new URLSearchParams(window.location.search).get('group_id') || ''
  lastSearchQuery.value = groupId
  void loadCandidates(groupId, 1, groupId)
})
onBeforeUnmount(() => { if (searchTimer) window.clearTimeout(searchTimer) })

function collectorPriority(row: CollectorRequirementWorkbenchRow) {
  return row.physical_state === 'replaced' ? 3 : row.physical_state === 'missing' ? 2 : 1
}
function workflowLabel(state: string) {
  return ({ no_construction: '无已施工表计', needs_review: '待完成分类', blocked: '资料受阻', needs_replacement: '可翻拍', pool_shortage: '替换池不足', ready: '可翻拍', in_progress: '翻拍进行中', completed: '已完成' } as Record<string, string>)[state] || state
}
function imageUrl(photo: { image_url?: string; preview_url?: string; thumbnail_url?: string; canonical_image_url?: string } | null) {
  return photo?.preview_url || photo?.image_url || photo?.thumbnail_url || photo?.canonical_image_url || ''
}
function largeImageUrl(photo: { image_url?: string; preview_url?: string; thumbnail_url?: string; canonical_image_url?: string } | null) {
  return photo?.image_url || photo?.canonical_image_url || photo?.preview_url || photo?.thumbnail_url || ''
}
function openPhotoPreview(src: string, alt: string) {
  if (src) photoPreview.value = { src, alt }
}
function closePhotoPreview() { photoPreview.value = { src: '', alt: '' } }
function classificationLabel(meter: ReviewWorkbenchMeter) {
  if (meter.review_ready) return '分类完成'
  return meter.classification_manually_confirmed ? '分类已确认，资料异常' : '待人工确认'
}
function collectorStateLabel(state: CollectorDisplayRow['physical_state']) {
  return ({ pending: '待确认', present: '有实物', missing: '无实物', replaced: '已替换' } as Record<string, string>)[state] || state
}
function selectMeter(meter: ReviewWorkbenchMeter) { selectedGroupId.value = meter.group_id }
function showError(error: unknown) { errorMessage.value = error instanceof Error ? error.message : '请求失败，请重试' }
async function loadCandidates(query = lastSearchQuery.value, page = candidatePage.value, preferredGroupId = '') {
  const serial = ++searchSerial
  loading.value = true
  try {
    const response = await fetchGlobalCollectorTerminals({ query, page, pageSize: candidatePageSize, includeBlocked: true })
    if (serial !== searchSerial) return
    candidates.value = response.items
    candidatePage.value = response.page
    candidateTotal.value = response.total
    const matchingGroup = query && response.total === 1 && response.items.length === 1
      ? response.items
      : []
    const candidate = preferredGroupId
      ? (matchingGroup.length === 1 ? matchingGroup[0] : undefined)
      : (query
          ? (matchingGroup.length === 1 ? matchingGroup[0] : undefined)
          : response.items.find((item) => item.selectable))
    if (candidate) await openCandidate(candidate, preferredGroupId)
    else if (query) {
      errorMessage.value = response.total > 1
        ? '匹配到多个终端，请输入完整终端号。'
        : '未找到终端，请检查终端号。'
    }
  } catch (error) {
    if (serial === searchSerial) showError(error)
  } finally {
    if (serial === searchSerial) loading.value = false
  }
}
function searchCandidates() {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = 0
  openSerial += 1
  opened.value = null
  selectedGroupId.value = ''
  lastSearchQuery.value = terminalInput.value.trim()
  candidatePage.value = 1
  ++searchSerial
  void loadCandidates(lastSearchQuery.value, 1)
}
function scheduleSearch() {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(searchCandidates, 250)
}
function changeCandidatePage(page: number) {
  if (page < 1 || page === candidatePage.value || (page - 1) * candidatePageSize >= candidateTotal.value) return
  openSerial += 1
  opened.value = null
  selectedGroupId.value = ''
  ++searchSerial
  void loadCandidates(lastSearchQuery.value, page)
}
async function openCandidate(candidate: GlobalCollectorTerminalCandidate, preferredGroupId = '') {
  const serial = ++openSerial
  loading.value = true
  errorMessage.value = ''
  try {
    const next = await openReviewWorkbenchTerminal({ terminal_key: candidate.terminal_key, source_revision: candidate.source_revision })
    if (serial !== openSerial) return
    const preferredMeter = preferredGroupId
      ? next.meters.find((meter) => meter.group_id === preferredGroupId)
      : null
    if (preferredGroupId && !preferredMeter) {
      opened.value = null
      selectedGroupId.value = ''
      errorMessage.value = '资料组不属于该终端或尚未施工，未自动选择。'
      return
    }
    opened.value = next
    terminalInput.value = next.terminal.terminal_code
    selectedGroupId.value = preferredMeter?.group_id || next.meters.find((meter) => meter.construction_state === 'constructed')?.group_id || ''
  } catch (error) {
    if (serial === openSerial) showError(error)
  } finally {
    if (serial === openSerial) loading.value = false
  }
}
async function reopenCurrent() {
  const candidate = candidates.value.find((item) => item.terminal_key === opened.value?.terminal.terminal_key)
  if (candidate) await openCandidate({ ...candidate, source_revision: opened.value?.source_revision || candidate.source_revision }, selectedGroupId.value)
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
function completeCollector(row: CollectorRequirementWorkbenchRow) {
  if (!row.workbench_item_id || opened.value?.workflow_state === 'pool_shortage' || completionBlockers(row).length) return
  void runMutation(() => setCollectorWorkbenchItemCompleted(row.workbench_item_id!, true))
}
function completeMeter(item: NonNullable<ReviewWorkbenchOpenResult['rephoto']>['meter_install_items'][number]) {
  if (!item.workbench_item_id || meterCompletionBlockers(item).length) return
  void runMutation(() => setCollectorWorkbenchItemCompleted(item.workbench_item_id!, true))
}
function addManualDemand() {
  const terminalId = rephoto.value?.terminal.id
  const quantity = parsedManualDemandQuantity.value
  if (!terminalId || quantity === null) return
  void runMutation(async () => {
    await createReviewWorkbenchManualDemand(terminalId, quantity)
    manualDemandQuantity.value = ''
  })
}
</script>

<template>
  <main class="review-rephoto-workbench" :aria-busy="loading || mutationPending">
    <header class="page-heading">
      <div><h1>审阅与翻拍</h1><p>按终端完成照片分类与查看翻拍资料。</p></div>
      <p class="scope-note">本页只负责照片分类与人工翻拍，不连接甲方平台。</p>
    </header>
    <section class="terminal-search"><label for="terminal-search">终端号</label><input id="terminal-search" v-model="terminalInput" aria-label="输入终端号" placeholder="请输入终端号" @input="scheduleSearch" /><button type="button" data-testid="search-terminal" @click="searchCandidates">查询</button></section>
    <nav v-if="candidateTotal > candidatePageSize" class="candidate-pagination" aria-label="终端搜索分页"><button type="button" data-testid="previous-candidate-page" :disabled="candidatePage <= 1" @click="changeCandidatePage(candidatePage - 1)">上一页</button><span>第 {{ candidatePage }} 页</span><button type="button" data-testid="next-candidate-page" :disabled="candidatePage * candidatePageSize >= candidateTotal" @click="changeCandidatePage(candidatePage + 1)">下一页</button></nav>
    <p v-if="errorMessage" role="alert" class="warning">{{ errorMessage }}</p>
    <template v-if="opened">
      <section class="terminal-summary">
        <div><span>终端</span><strong>{{ opened.terminal.terminal_code }}</strong></div>
        <div><span>已施工</span><strong>{{ opened.constructed_meter_count }}</strong></div>
        <div><span>未施工</span><strong>{{ opened.unconstructed_meter_count }}</strong></div>
        <div><span>分类完成</span><strong>{{ opened.review_ready_count }}/{{ opened.constructed_meter_count }}</strong></div>
        <strong class="workflow-status" :class="{ locked: !rephotoUnlocked }">{{ workflowLabel(opened.workflow_state) }}</strong>
      </section>
      <p class="terminal-notice" :class="{ unlocked: rephotoUnlocked }">{{ terminalNotice }}<button v-if="sourceChanged" type="button" class="rephoto-mutation refresh-button" data-testid="refresh-terminal" :disabled="!mutable || !sourceChanged" @click="refresh">刷新资料</button></p>

      <section class="meter-section">
        <h2>表计资料</h2>
        <article v-for="meter in constructedMeters" :key="meter.group_id" class="meter-record" :class="{ 'is-expanded': meter.group_id === selectedMeter?.group_id }">
          <button type="button" class="meter-record-header" :data-testid="`meter-record-${meter.group_id}`" @click="selectMeter(meter)">
            <span class="meter-number"><small>表号</small><strong>{{ meter.meter_no }}</strong></span>
            <span><small>模块号</small><strong>{{ meter.module_no }}</strong></span>
            <span class="classification-state" :class="{ complete: meter.review_ready }">{{ classificationLabel(meter) }}</span>
            <span class="expand-label">{{ meter.group_id === selectedMeter?.group_id ? '收起' : '展开查看' }}</span>
          </button>
          <div v-if="meter.group_id === selectedMeter?.group_id" class="meter-record-body">
            <DataCenterGroupReviewPanel :group-id="meter.group_id" :classification-only="true" @updated="reopenCurrent" />
            <section class="rephoto-material" :class="{ locked: !selectedRephotoItem }">
              <header><strong>翻拍资料</strong><span v-if="!selectedRephotoItem">资料异常，暂不可翻拍</span></header>
              <div v-if="selectedRephotoItem" class="identifier-barcodes">
                <Code128Barcode :value="selectedRephotoItem.meter_barcode" label="表号条码" />
                <Code128Barcode :value="selectedRephotoItem.module_barcode" label="模块号条码" />
              </div>
              <div class="rephoto-slots">
                <figure v-for="slot in selectedRephotoItem ? normalizeMeterPhotoSlots(selectedRephotoItem.photos) : [{ slot: 'module_meter', label: '电表和模块', photo: null }, { slot: 'after_box', label: '改造完成', photo: null }]" :key="slot.slot" class="rephoto-slot">
                  <figcaption>{{ slot.label }}</figcaption>
                  <button
                    v-if="imageUrl(slot.photo)"
                    type="button"
                    class="photo-preview-trigger"
                    :data-testid="`preview-meter-${slot.slot}`"
                    :aria-label="`查看${slot.label}大图`"
                    @click="openPhotoPreview(largeImageUrl(slot.photo), slot.label)"
                  ><img :src="imageUrl(slot.photo)" :alt="slot.label" /></button>
                  <span v-else>{{ selectedRephotoItem ? '暂无照片' : '资料异常，暂无可翻拍照片' }}</span>
                </figure>
              </div>
              <button v-if="selectedRephotoItem" type="button" class="rephoto-mutation complete-meter" :disabled="!mutable || meterCompletionBlockers(selectedRephotoItem).length > 0" @click="completeMeter(selectedRephotoItem)">完成本表翻拍</button>
            </section>
          </div>
        </article>
        <article v-for="meter in unconstructedMeters" :key="meter.group_id" class="meter-record unconstructed-record" :class="{ 'is-expanded': meter.group_id === selectedMeter?.group_id }">
          <button type="button" class="meter-record-header" :data-testid="`meter-record-${meter.group_id}`" @click="selectMeter(meter)">
            <span class="meter-number"><small>表号</small><strong>{{ meter.meter_no }}</strong></span>
            <span class="unconstructed-copy">未施工，不参与本次翻拍</span>
          </button>
        </article>
      </section>

      <section class="collector-section">
        <h2>采集器</h2>
        <div class="manual-demand-control">
          <label for="manual-demand-quantity">人工需求</label>
          <input id="manual-demand-quantity" v-model="manualDemandQuantity" type="number" min="1" step="1" inputmode="numeric" data-testid="manual-demand-quantity" aria-label="增加采集器数量" />
          <button type="button" class="rephoto-mutation" data-testid="submit-manual-demand" :disabled="!canSubmitManualDemand" @click="addManualDemand">增加并随机匹配</button>
        </div>
        <div class="collector-table">
          <header><span>采集器编号</span><span>实物状态</span><span>照片预览</span><span>条形码</span><span>翻拍资料</span></header>
          <article v-for="row in collectorRows" :key="row.key" class="collector-card">
            <strong>{{ row.original_collector_no }}</strong>
            <span class="collector-state" :class="row.physical_state">{{ collectorStateLabel(row.physical_state) }}</span>
            <button
              v-if="imageUrl(row.photo)"
              type="button"
              class="photo-preview-trigger collector-photo-trigger"
              :data-testid="`preview-collector-${row.key}`"
              :aria-label="`查看采集器 ${row.original_collector_no} 大图`"
              @click="openPhotoPreview(largeImageUrl(row.photo), `采集器 ${row.original_collector_no}`)"
            ><img :src="imageUrl(row.photo)" :alt="`采集器 ${row.original_collector_no}`" /></button>
            <span v-else class="empty-cell">-</span>
            <div><span v-if="row.final_collector_no && row.final_collector_no !== row.original_collector_no" class="replacement-number">新编号 {{ row.final_collector_no }}</span><Code128Barcode v-if="row.collector_barcode" :value="row.collector_barcode" /></div>
            <div class="collector-actions">
              <button v-if="row.physical_state === 'pending' || row.physical_state === 'missing'" type="button" class="rephoto-mutation" data-testid="replace-all-missing" :disabled="!mutable || row.physical_state === 'pending' || opened.workflow_state === 'pool_shortage'" @click="replaceMissing">随机替换</button>
              <button v-if="row.source?.workbench_item_id" type="button" class="rephoto-mutation" :data-testid="`complete-collector-${row.source.requirement_id}`" :disabled="!mutable || opened.workflow_state === 'pool_shortage' || completionBlockers(row.source).length > 0" @click="completeCollector(row.source)">完成</button>
              <button v-if="row.source?.assignment_id" type="button" class="rephoto-mutation" data-testid="rollback-assignment" :disabled="!mutable" @click="rollback(row.source)">回滚</button>
              <span v-if="row.physical_state === 'pending'" class="locked-copy">翻拍资料尚未生成</span>
              <span v-else-if="row.physical_state === 'present' && !row.source?.workbench_item_id">可直接翻拍</span>
            </div>
          </article>
        </div>
      </section>
    </template>
    <PhotoLightbox :src="photoPreview.src" :alt="photoPreview.alt" @close="closePhotoPreview" />
  </main>
</template>

<style scoped>
.review-rephoto-workbench { display: grid; gap: 16px; min-width: 0; max-width: 1040px; margin: 0 auto; padding: 28px 20px 40px; color: var(--v2-text, #2f3a4a); }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.page-heading h1, .meter-section h2, .collector-section h2 { margin: 0; color: var(--v2-text-strong, #172033); }
.page-heading h1 { font-size: 24px; line-height: 1.3; }
.page-heading p { margin: 6px 0 0; color: var(--v2-text-muted, #7a8798); font-size: 13px; }
.page-heading .scope-note { margin-top: 9px; text-align: right; }
.terminal-search { display: flex; gap: 10px; align-items: center; max-width: 540px; }
.terminal-search label { color: var(--v2-text-strong, #172033); font-size: 14px; font-weight: 600; white-space: nowrap; }
.terminal-search input { min-width: 0; flex: 1; height: 38px; padding: 0 12px; border: 1px solid var(--v2-border, #dce3ec); border-radius: 6px; background: #fff; color: inherit; font: inherit; }
.terminal-search button, .candidate-pagination button, .rephoto-mutation { min-height: 36px; padding: 0 16px; border: 1px solid var(--v2-border, #dce3ec); border-radius: 6px; background: #fff; color: inherit; cursor: pointer; font: inherit; }
.terminal-search button { color: #fff; background: var(--v2-accent, #1677ff); border-color: var(--v2-accent, #1677ff); }
.candidate-pagination { display: flex; align-items: center; gap: 10px; }
.warning { margin: 0; color: var(--el-color-danger, #d03050); }
.terminal-summary { display: grid; grid-template-columns: 1.2fr repeat(3, .8fr) auto; align-items: stretch; overflow: hidden; border: 1px solid var(--v2-border, #dce3ec); border-radius: 8px 8px 0 0; background: #fff; }
.terminal-summary > div { display: flex; align-items: center; justify-content: center; gap: 14px; min-height: 58px; padding: 0 18px; border-right: 1px solid #edf0f4; }
.terminal-summary > div:first-child { justify-content: flex-start; }
.terminal-summary span { color: var(--v2-text-muted, #7a8798); font-size: 13px; }
.terminal-summary strong { color: var(--v2-text-strong, #172033); }
.workflow-status { align-self: center; justify-self: center; margin: 0 18px; padding: 5px 10px; border: 1px solid var(--el-color-success, #67c23a); border-radius: 6px; color: var(--el-color-success, #67c23a); font-size: 13px; }
.workflow-status.locked { border-color: var(--el-color-warning, #e6a23c); color: var(--el-color-warning, #e6a23c); }
.terminal-notice { display: flex; align-items: center; gap: 12px; min-height: 34px; margin: -16px 0 0; padding: 0 18px; border: 1px solid #f6d8a8; border-top: 0; border-radius: 0 0 8px 8px; background: #fffaf2; color: #d97b0b; font-size: 13px; }
.terminal-notice.unlocked { border-color: #cde8c5; background: #f6fff3; color: #4d9b36; }
.refresh-button { margin-left: auto; min-height: 28px; }
.meter-section, .collector-section { display: grid; gap: 8px; }
.meter-section h2, .collector-section h2 { font-size: 16px; }
.manual-demand-control { display: flex; align-items: center; gap: 8px; color: var(--v2-text-muted, #7a8798); font-size: 13px; }
.manual-demand-control input { width: 72px; min-height: 32px; padding: 0 8px; border: 1px solid var(--v2-border, #dce3ec); border-radius: 6px; color: inherit; font: inherit; }
.manual-demand-control .rephoto-mutation { min-height: 32px; padding: 0 10px; }
.meter-record { overflow: hidden; border: 1px solid var(--v2-border, #dce3ec); border-radius: 7px; background: #fff; }
.meter-record.is-expanded { border-color: #cdd8e5; box-shadow: 0 4px 14px rgba(44, 63, 86, .04); }
.meter-record-header { display: grid; grid-template-columns: 1fr 1fr auto auto; gap: 22px; align-items: center; width: 100%; min-height: 50px; padding: 0 18px; border: 0; background: #fff; color: inherit; text-align: left; cursor: pointer; font: inherit; }
.meter-record-header > span { display: flex; align-items: center; gap: 12px; min-width: 0; }
.meter-record-header small { color: var(--v2-text-muted, #7a8798); font-size: 12px; }
.meter-record-header strong { overflow: hidden; color: var(--v2-text-strong, #172033); text-overflow: ellipsis; white-space: nowrap; }
.classification-state { color: var(--el-color-warning, #e6a23c); font-size: 13px; }
.classification-state.complete { color: var(--el-color-success, #67c23a); }
.expand-label { justify-self: end; color: var(--v2-text-muted, #7a8798); font-size: 12px; }
.meter-record-body { display: grid; gap: 18px; padding: 14px 18px 18px; border-top: 1px solid #edf0f4; }
.unconstructed-record { background: var(--v2-surface-soft, #f7f9fc); opacity: .72; }
.unconstructed-record .meter-record-header { grid-template-columns: 1fr 2fr; background: transparent; cursor: default; }
.unconstructed-copy { color: var(--v2-text-muted, #7a8798); font-size: 13px; }
.rephoto-material { display: grid; gap: 12px; padding-top: 14px; border-top: 1px solid #edf0f4; }
.rephoto-material > header { display: flex; justify-content: space-between; color: var(--v2-text-muted, #7a8798); font-size: 13px; }
.rephoto-material > header strong { color: var(--v2-text-strong, #172033); }
.identifier-barcodes, .rephoto-slots { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.rephoto-slot { display: grid; gap: 8px; min-height: 120px; margin: 0; padding: 12px; border: 1px solid var(--v2-border, #dce3ec); border-radius: 6px; background: #fff; }
.rephoto-slot figcaption { color: var(--v2-text-muted, #7a8798); font-size: 13px; }
.photo-preview-trigger { display: block; width: 100%; padding: 0; border: 0; background: transparent; cursor: zoom-in; }
.rephoto-slot img { display: block; width: 100%; height: 180px; object-fit: contain; }
.collector-photo-trigger img { display: block; width: 100%; height: 78px; object-fit: contain; }
.rephoto-slot span { display: grid; place-items: center; min-height: 78px; color: var(--v2-text-muted, #7a8798); background: var(--v2-surface-soft, #f7f9fc); }
.rephoto-material.locked .rephoto-slot { background: var(--v2-surface-soft, #f7f9fc); opacity: .72; }
.complete-meter { justify-self: end; }
.collector-table { overflow: hidden; border: 1px solid var(--v2-border, #dce3ec); border-radius: 7px; background: #fff; }
.collector-table > header, .collector-card { display: grid; grid-template-columns: 1fr .75fr .9fr 1.55fr 1.45fr; gap: 16px; align-items: center; min-height: 58px; padding: 10px 18px; }
.collector-table > header { min-height: 38px; border-bottom: 1px solid #edf0f4; color: var(--v2-text-muted, #7a8798); font-size: 12px; }
.collector-card + .collector-card { border-top: 1px solid #edf0f4; }
.collector-card > img { width: 84px; height: 52px; border-radius: 4px; object-fit: cover; }
.collector-card > div { display: grid; gap: 6px; min-width: 0; }
.collector-state { justify-self: start; padding: 2px 6px; border-radius: 4px; background: #f3f5f8; color: var(--v2-text-muted, #7a8798); font-size: 12px; }
.collector-state.present { background: #eef9eb; color: #4d9b36; }
.collector-state.missing { background: #fff5e9; color: #d97b0b; }
.collector-state.replaced { background: #eef5ff; color: #1677ff; }
.replacement-number { color: #1677ff; font-size: 12px; }
.collector-actions { display: flex !important; grid-auto-flow: column; justify-content: start; align-items: center; gap: 6px !important; }
.locked-copy, .empty-cell { color: var(--v2-text-muted, #7a8798); font-size: 12px; }
.rephoto-mutation:disabled, .candidate-pagination button:disabled { cursor: not-allowed; opacity: .55; }
@media (max-width: 760px) {
  .review-rephoto-workbench { padding: 18px 12px 30px; overflow-x: hidden; }
  .page-heading { flex-direction: column; gap: 4px; }
  .page-heading .scope-note { text-align: left; }
  .terminal-search { max-width: none; }
  .terminal-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .terminal-summary > div { justify-content: flex-start; border-bottom: 1px solid #edf0f4; }
  .workflow-status { min-height: 30px; grid-column: 1 / -1; }
  .meter-record-header { grid-template-columns: 1fr 1fr; padding: 10px 14px; }
  .classification-state, .expand-label { justify-self: start; }
  .identifier-barcodes, .rephoto-slots { grid-template-columns: 1fr; }
  .collector-table { overflow-x: auto; }
  .collector-table > header, .collector-card { min-width: 760px; }
}
</style>
