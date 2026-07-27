<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { fetchInstallerWorkload } from '@/api/services'
import type { InstallerExceptionGroup, InstallerWorkSegment, InstallerWorkloadRow } from '@/api/types'
import {
  INSTALLER_KPI_PAGE_SIZE,
  buildInstallerKpiCsv,
  createInstallerKpiRequestGate,
  filterInstallerKpiRows,
  formatInstallerKpiDecimal,
  formatInstallerKpiDuration,
  installerKpiBarHeight,
  paginateInstallerKpiRows,
  summarizeInstallerKpiRows,
  type InstallerKpiScope,
} from '@/utils/installerKpi'

const props = defineProps<{
  modelValue: boolean
  installer: string
  scope: InstallerKpiScope
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'open-data-center': []
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const requestGate = createInstallerKpiRequestGate()
const workloadCache = new Map<string, InstallerWorkloadRow[]>()
const rawRows = ref<InstallerWorkloadRow[]>([])
const loadedInstaller = ref('')
const loading = ref(false)
const loadError = ref('')
const page = ref(1)
const activeTimeRow = ref<InstallerWorkloadRow | null>(null)
const timeDialogVisible = ref(false)
const activeSegment = ref<InstallerWorkSegment | null>(null)
const segmentDialogVisible = ref(false)
const activeExceptionGroups = ref<InstallerExceptionGroup[]>([])
const exceptionDialogVisible = ref(false)
const segmentPage = ref(1)
const exceptionPage = ref(1)

const workloadRows = computed(() => filterInstallerKpiRows(rawRows.value, props.scope))
const totals = computed(() => summarizeInstallerKpiRows(workloadRows.value))
const pagedRows = computed(() => paginateInstallerKpiRows(workloadRows.value, page.value))
const timeSegments = computed(() => activeTimeRow.value?.twoHourSegments || [])
const maxSegmentMinutes = computed(() => Math.max(1, ...timeSegments.value.map((segment) => Number(segment.efficiencyMinutes || 0))))
const pagedSegmentAddresses = computed(() => paginateInstallerKpiRows(activeSegment.value?.addresses || [], segmentPage.value))
const pagedExceptionGroups = computed(() => paginateInstallerKpiRows(activeExceptionGroups.value, exceptionPage.value))
const timeDialogTitle = computed(() => `${props.installer} ${activeTimeRow.value?.date || ''} 2 小时效率分布`)
const segmentDialogTitle = computed(() => `${props.installer} ${activeTimeRow.value?.date || ''} ${activeSegment.value?.label || ''} 地址清单`)
const exceptionDialogTitle = computed(() => `${props.installer} ${activeTimeRow.value?.date || ''} 异常明细`)

function resetDrilldowns() {
  activeTimeRow.value = null
  timeDialogVisible.value = false
  activeSegment.value = null
  segmentDialogVisible.value = false
  activeExceptionGroups.value = []
  exceptionDialogVisible.value = false
  segmentPage.value = 1
  exceptionPage.value = 1
}

function resetPagesAndDrilldowns() {
  page.value = 1
  resetDrilldowns()
}

function clearWorkload() {
  rawRows.value = []
  loadedInstaller.value = ''
  loadError.value = ''
  resetPagesAndDrilldowns()
}

function invalidateWorkloadRequest() {
  requestGate.invalidate()
  loading.value = false
}

function isCurrentRequest(request: number, installer: string) {
  return requestGate.isCurrent(request) && installer === props.installer.trim() && props.modelValue
}

async function loadWorkload() {
  const installer = props.installer.trim()
  if (!props.modelValue || !installer) return
  const request = requestGate.begin()
  loading.value = true
  loadError.value = ''
  try {
    let rows = workloadCache.get(installer)
    if (!rows) {
      rows = (await fetchInstallerWorkload(installer)).items
      workloadCache.set(installer, rows)
    }
    if (!isCurrentRequest(request, installer)) return
    rawRows.value = rows
    loadedInstaller.value = installer
    resetPagesAndDrilldowns()
  } catch (error) {
    if (!isCurrentRequest(request, installer)) return
    rawRows.value = []
    loadError.value = error instanceof Error ? error.message : '安装人员工作量加载失败'
  } finally {
    if (isCurrentRequest(request, installer)) loading.value = false
  }
}

function openWorkTime(row: InstallerWorkloadRow) {
  if (!row.timepointCount) return
  activeTimeRow.value = row
  activeSegment.value = null
  segmentDialogVisible.value = false
  timeDialogVisible.value = true
}

function openSegment(segment: InstallerWorkSegment) {
  if (!segment.addresses?.length) return
  activeSegment.value = segment
  segmentPage.value = 1
  segmentDialogVisible.value = true
}

function openExceptions(row: InstallerWorkloadRow) {
  if (!row.exceptionCount) return
  activeTimeRow.value = row
  activeExceptionGroups.value = row.exceptionGroups || []
  exceptionPage.value = 1
  exceptionDialogVisible.value = true
}

function openDataCenter() {
  emit('open-data-center')
}

function downloadCsv() {
  if (!workloadRows.value.length) return
  const { filename, content } = buildInstallerKpiCsv(props.installer, workloadRows.value)
  const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

watch(
  () => [props.modelValue, props.installer, props.scope.mode, props.scope.anchorDate] as const,
  ([isVisible], previous) => {
    if (!isVisible) {
      invalidateWorkloadRequest()
      resetDrilldowns()
      return
    }
    if (!previous || props.installer !== previous[1] || loadedInstaller.value !== props.installer.trim()) {
      invalidateWorkloadRequest()
      clearWorkload()
      void loadWorkload()
    }
    else resetPagesAndDrilldowns()
  },
  { immediate: true },
)
</script>

<template>
  <el-dialog v-model="visible" :title="`${installer} 每日工作量`" width="1180px" append-to-body>
    <el-alert v-if="loadError" type="error" :closable="false" :title="loadError" show-icon>
      <template #default>
        <el-button link type="primary" @click="loadWorkload">重试</el-button>
      </template>
    </el-alert>

    <div class="workload-summary">
      <article><span>资料组</span><strong>{{ totals.groupCount }}</strong></article>
      <article><span>照片</span><strong>{{ totals.photoCount }}</strong></article>
      <article><span>已归档</span><strong>{{ totals.archivedCount }}</strong></article>
      <article><span>异常</span><strong>{{ totals.exceptionCount }}</strong></article>
      <article><span>总工时</span><strong>{{ formatInstallerKpiDuration(totals.workDurationMinutes) }}</strong></article>
      <article><span>完成量</span><strong>{{ totals.completionCount }}</strong></article>
      <article><span>加权完成</span><strong>{{ formatInstallerKpiDecimal(totals.weightedCompletion) }}</strong></article>
    </div>

    <el-table v-loading="loading" :data="pagedRows.items" height="390" size="small">
      <el-table-column prop="date" label="日期" width="104" />
      <el-table-column prop="startTime" label="开工" width="82" />
      <el-table-column prop="endTime" label="收工" width="82" />
      <el-table-column label="工作时长" min-width="120">
        <template #default="{ row }">
          <el-button class="workload-exception-link" link type="primary" :disabled="!row.timepointCount" @click="openWorkTime(row)">
            {{ row.workDurationLabel || formatInstallerKpiDuration(row.workDurationMinutes) }}
          </el-button>
        </template>
      </el-table-column>
      <el-table-column label="每小时完成" width="104">
        <template #default="{ row }">{{ formatInstallerKpiDecimal(row.completionPerEffectiveHour) }}</template>
      </el-table-column>
      <el-table-column label="加权效率" width="104">
        <template #default="{ row }">{{ formatInstallerKpiDecimal(row.weightedCompletionPerEffectiveHour) }}</template>
      </el-table-column>
      <el-table-column label="计入工时" min-width="116">
        <template #default="{ row }">{{ row.fusedWorkDurationLabel || formatInstallerKpiDuration(row.fusedWorkDurationMinutes) }}</template>
      </el-table-column>
      <el-table-column label="融合效率" width="104">
        <template #default="{ row }">{{ formatInstallerKpiDecimal(row.fusedWeightedCompletionPerEffectiveHour) }}</template>
      </el-table-column>
      <el-table-column label="在线系数" width="96">
        <template #default="{ row }">{{ formatInstallerKpiDecimal(row.finalOnlineCoefficient) }}</template>
      </el-table-column>
      <el-table-column prop="denseBonusMinutesV2" label="补偿" width="78" />
      <el-table-column prop="groupCount" label="资料组" width="78" />
      <el-table-column prop="photoCount" label="照片" width="70" />
      <el-table-column prop="archivedCount" label="已归档" width="82" />
      <el-table-column label="异常" width="78">
        <template #default="{ row }">
          <el-button class="workload-exception-link" link type="danger" :disabled="!row.exceptionCount" @click="openExceptions(row)">
            {{ row.exceptionCount }}
          </el-button>
        </template>
      </el-table-column>
      <el-table-column prop="unreviewedCount" label="未审阅" width="82" />
    </el-table>
    <el-pagination
      v-if="pagedRows.total > INSTALLER_KPI_PAGE_SIZE"
      v-model:current-page="page"
      layout="prev, pager, next"
      :page-size="INSTALLER_KPI_PAGE_SIZE"
      :total="pagedRows.total"
    />
    <el-empty v-if="!loading && !loadError && !workloadRows.length" description="当前范围暂无 KPI 数据" />
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button plain :disabled="!installer" @click="openDataCenter">查看原始资料</el-button>
      <el-button type="primary" :disabled="!workloadRows.length" @click="downloadCsv">导出 KPI CSV</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="timeDialogVisible" :title="timeDialogTitle" width="900px" append-to-body>
    <div v-if="activeTimeRow" class="work-time-detail">
      <div class="work-time-stats">
        <article><span>开工</span><strong>{{ activeTimeRow.startTime || '-' }}</strong></article>
        <article><span>收工</span><strong>{{ activeTimeRow.endTime || '-' }}</strong></article>
        <article><span>有效工时</span><strong>{{ activeTimeRow.efficiencyDurationLabel }}</strong></article>
        <article><span>完成量</span><strong>{{ activeTimeRow.completionCount }}</strong></article>
        <article><span>加权完成</span><strong>{{ formatInstallerKpiDecimal(activeTimeRow.weightedCompletion) }}</strong></article>
        <article><span>在线系数</span><strong>{{ formatInstallerKpiDecimal(activeTimeRow.finalOnlineCoefficient) }}</strong></article>
      </div>
      <section class="screen-time-card" aria-label="2 小时效率分布">
        <div class="screen-time-head">
          <strong>2 小时效率分布</strong>
          <span class="screen-time-legend">点击有地址的时段查看地址清单</span>
        </div>
        <div class="work-time-chart">
          <button
            v-for="segment in timeSegments"
            :key="segment.label"
            class="work-time-segment"
            :class="{ active: Number(segment.efficiencyMinutes || 0) > 0 }"
            type="button"
            :disabled="!segment.addresses?.length"
            @click="openSegment(segment)"
          >
            <span class="work-time-value">{{ segment.completionCount }}</span>
            <span class="work-time-bar-track"><i class="work-time-bar" :style="{ height: `${installerKpiBarHeight(Number(segment.efficiencyMinutes || 0), maxSegmentMinutes)}%` }" /></span>
            <span class="work-time-label">{{ segment.label }}</span>
          </button>
        </div>
      </section>
    </div>
    <template #footer><el-button @click="timeDialogVisible = false">关闭</el-button></template>
  </el-dialog>

  <el-dialog v-model="segmentDialogVisible" :title="segmentDialogTitle" width="920px" append-to-body>
    <el-table :data="pagedSegmentAddresses.items" height="430" size="small">
      <el-table-column prop="completedTime" label="完成时间" width="92" />
      <el-table-column prop="meterNo" label="表号" min-width="130" />
      <el-table-column prop="terminal" label="终端" min-width="120" />
      <el-table-column prop="address" label="地址" min-width="180" />
      <el-table-column label="难度" min-width="150">
        <template #default="{ row }">{{ row.difficultyLabel }} / {{ row.difficultyWeight }} {{ row.difficultyReasons.join('、') }}</template>
      </el-table-column>
      <el-table-column prop="photoCount" label="照片" width="70" />
    </el-table>
    <el-pagination
      v-if="pagedSegmentAddresses.total > INSTALLER_KPI_PAGE_SIZE"
      v-model:current-page="segmentPage"
      layout="prev, pager, next"
      :page-size="INSTALLER_KPI_PAGE_SIZE"
      :total="pagedSegmentAddresses.total"
    />
    <template #footer><el-button @click="segmentDialogVisible = false">关闭</el-button></template>
  </el-dialog>

  <el-dialog v-model="exceptionDialogVisible" :title="exceptionDialogTitle" width="920px" append-to-body>
    <el-table :data="pagedExceptionGroups.items" height="430" size="small">
      <el-table-column prop="meterNo" label="表号" min-width="130" />
      <el-table-column prop="terminal" label="终端" min-width="120" />
      <el-table-column prop="address" label="地址" min-width="180" />
      <el-table-column label="原因 / 备注" min-width="190">
        <template #default="{ row }">{{ row.exceptionReasons.join('、') || row.exceptionNote || '-' }}</template>
      </el-table-column>
      <el-table-column prop="photoCount" label="照片" width="70" />
    </el-table>
    <el-pagination
      v-if="pagedExceptionGroups.total > INSTALLER_KPI_PAGE_SIZE"
      v-model:current-page="exceptionPage"
      layout="prev, pager, next"
      :page-size="INSTALLER_KPI_PAGE_SIZE"
      :total="pagedExceptionGroups.total"
    />
    <template #footer><el-button @click="exceptionDialogVisible = false">关闭</el-button></template>
  </el-dialog>
</template>

<style scoped>
.workload-summary,
.work-time-stats {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.workload-summary article,
.work-time-stats article {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.workload-summary span,
.work-time-stats span,
.screen-time-legend {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.workload-summary strong,
.work-time-stats strong {
  color: var(--el-text-color-primary);
  font-size: 18px;
}

.workload-exception-link {
  padding: 0;
  white-space: nowrap;
}

.work-time-detail {
  display: grid;
  gap: 14px;
}

.work-time-stats {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.screen-time-card {
  padding: 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}

.screen-time-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.screen-time-legend {
  text-align: right;
}

.work-time-chart {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 8px;
  min-height: 190px;
}

.work-time-segment {
  display: grid;
  grid-template-rows: auto 1fr auto;
  gap: 6px;
  min-width: 0;
  padding: 4px;
  border: 0;
  border-radius: 6px;
  color: var(--el-text-color-secondary);
  background: transparent;
}

.work-time-segment:not(:disabled) { cursor: pointer; }
.work-time-segment:disabled { opacity: .56; }
.work-time-segment.active { color: var(--el-color-primary); }
.work-time-segment:focus-visible { outline: 2px solid var(--el-color-primary); }

.work-time-value { font-weight: 700; }

.work-time-bar-track {
  display: flex;
  align-items: flex-end;
  min-height: 120px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
}

.work-time-bar {
  width: 100%;
  min-height: 0;
  border-radius: 4px;
  background: var(--el-color-primary);
}

.work-time-label {
  overflow: hidden;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 960px) {
  .workload-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .work-time-chart { grid-template-columns: repeat(6, minmax(0, 1fr)); }
}

@media (max-width: 720px) {
  .workload-summary,
  .work-time-stats { grid-template-columns: 1fr; }
  .work-time-chart { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .screen-time-head { display: grid; }
  .screen-time-legend { text-align: left; }
}
</style>
