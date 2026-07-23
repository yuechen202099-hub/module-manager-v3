<script setup lang="ts">
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, ref, watch } from 'vue'

import ExportCatalogTab from '@/components/export-center/ExportCatalogTab.vue'
import ExportJobsTable from '@/components/export-center/ExportJobsTable.vue'
import TerminalDeliveryTab from '@/components/export-center/TerminalDeliveryTab.vue'
import { createExportJob, downloadExportJob, fetchExportTaskOptions } from '@/api/services'
import type { ExportCatalogItem, ExportCenterPageSize, ExportCenterTab, ExportJob, ExportTaskOption } from '@/api/types'
import { EXPORT_CENTER_PAGE_SIZES, useExportCenterQuery } from '@/composables/useExportCenterQuery'

const DEVICE_JOB_TYPES = ['device_terminal', 'device_meter', 'device_module', 'device_collector'] as const
const BUSINESS_JOB_TYPES = [
  'task_detail',
  'exception_meter',
  'exception_missing_photo',
  'replacement',
  'unmatched',
  'project_outside',
] as const
const STATISTICS_JOB_TYPES = ['barcode_review', 'installer_kpi', 'installer_daily_completion'] as const

const TAB_JOB_TYPES: Record<ExportCenterTab, readonly string[]> = {
  terminal: ['final_delivery'],
  device: DEVICE_JOB_TYPES,
  business: BUSINESS_JOB_TYPES,
  statistics: STATISTICS_JOB_TYPES,
}

const {
  query,
  catalog,
  terminalPage,
  jobsPage,
  loading,
  jobsLoading,
  errorMessage,
  setTab,
  setTerminalPage,
  setTerminalPageSize,
  setJobPage,
  setJobPageSize,
  setFilter,
  refresh,
} = useExportCenterQuery()

const filterDraft = ref('')
const launchingKey = ref('')
const downloadingJobId = ref('')
const selectedTaskId = ref('')
const taskLoading = ref(false)
const taskOptions = ref<ExportTaskOption[]>([])
let taskQueryTimer: ReturnType<typeof setTimeout> | null = null
let taskQuerySerial = 0
let taskController: AbortController | null = null

watch(
  () => query.filter,
  (value) => {
    filterDraft.value = value
  },
  { immediate: true },
)

watch(
  () => query.tab,
  (tab) => {
    if (tab === 'business' && !taskOptions.value.length && !taskLoading.value) {
      handleTaskQuery('')
    }
  },
  { immediate: true },
)

const filterPlaceholder = computed(() => {
  if (query.tab === 'terminal') return '筛选终端'
  if (query.tab === 'device') return '筛选设备清单'
  if (query.tab === 'business') return '筛选业务清单'
  return '筛选统计报表'
})

const catalogLabels = computed<Record<string, string>>(() =>
  Object.fromEntries(catalog.value.map((item) => [item.key, item.label])),
)

const filteredCatalogItems = computed(() => {
  const allowed = new Set(TAB_JOB_TYPES[query.tab])
  const needle = query.filter.trim().toLowerCase()
  const items = catalog.value.filter((item) => allowed.has(item.key))
  if (!needle) return items
  return items.filter((item) => `${item.label} ${item.key}`.toLowerCase().includes(needle))
})

const pagedCatalogItems = computed(() => {
  const offset = (query.terminalPage - 1) * query.terminalPageSize
  return filteredCatalogItems.value.slice(offset, offset + query.terminalPageSize)
})

const primaryTotal = computed(() => (query.tab === 'terminal' ? terminalPage.value.total : filteredCatalogItems.value.length))
const visibleJobs = computed(() => jobsPage.value.items)

function handlePrimaryPageSize(size: number) {
  void setTerminalPageSize(size as ExportCenterPageSize)
}

function handleJobPageSize(size: number) {
  void setJobPageSize(size as ExportCenterPageSize)
}

function handleTabChange(value: string | number) {
  void setTab(value as ExportCenterTab)
}

function applyFilter(next = filterDraft.value) {
  void setFilter(next)
}

function handleSelectedTaskId(value: string) {
  selectedTaskId.value = value
}

async function loadTaskOptions(queryText: string) {
  const serial = taskQuerySerial + 1
  taskQuerySerial = serial
  taskController?.abort()
  taskController = new AbortController()
  taskLoading.value = true
  try {
    const items = await fetchExportTaskOptions(queryText, 50, taskController.signal)
    if (serial !== taskQuerySerial) return
    taskOptions.value = items
  } catch (error) {
    if (serial !== taskQuerySerial || (error instanceof DOMException && error.name === 'AbortError')) return
    taskOptions.value = []
    ElMessage.error(error instanceof Error ? error.message : '任务加载失败')
  } finally {
    if (serial === taskQuerySerial) {
      taskLoading.value = false
    }
  }
}

function handleTaskQuery(queryText: string) {
  if (taskQueryTimer) clearTimeout(taskQueryTimer)
  taskQueryTimer = setTimeout(() => {
    void loadTaskOptions(queryText)
  }, 250)
}

async function handleDownloadJob(job: ExportJob) {
  downloadingJobId.value = job.id
  try {
    const result = await downloadExportJob(job.id)
    ElMessage.success(result.filename)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '下载失败')
  } finally {
    downloadingJobId.value = ''
  }
}

async function handleDownloadTerminal(terminal: string) {
  downloadingJobId.value = terminal
  try {
    const job = await createExportJob('final_delivery', {
      terminals: [terminal],
    })
    if (job.status === 'succeeded') {
      const result = await downloadExportJob(job.id)
      ElMessage.success(result.filename)
    } else {
      ElMessage.success(`${terminal} 已提交`)
      await refresh()
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '下载失败')
  } finally {
    downloadingJobId.value = ''
  }
}

async function handleLaunchTerminal(payload: { terminal: string; reviewScope: 'reviewed' | 'all' }) {
  const nextKey = `${payload.terminal}:${payload.reviewScope}`
  launchingKey.value = nextKey
  try {
    const job = await createExportJob('final_delivery', {
      terminal: payload.terminal,
      review_scope: payload.reviewScope,
    })
    if (job.status === 'succeeded') {
      await handleDownloadJob(job)
    } else {
      ElMessage.success(`${payload.terminal} 已提交`)
    }
    await refresh()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '发起失败')
  } finally {
    launchingKey.value = ''
  }
}

function launchFiltersFor(item: ExportCatalogItem) {
  const filters: Record<string, unknown> = {}
  if (item.requiredFilters?.some((field) => field.key === 'task_id' && field.kind === 'task') && selectedTaskId.value) {
    filters.task_id = Number(selectedTaskId.value)
  }
  return filters
}

async function handleLaunchCatalog(item: ExportCatalogItem) {
  const filters = launchFiltersFor(item)
  if (item.key === 'task_detail' && !filters.task_id) {
    ElMessage.error('请选择任务')
    return
  }
  launchingKey.value = item.key
  try {
    const job = await createExportJob(item.key, filters)
    if (job.status === 'succeeded') {
      await handleDownloadJob(job)
    } else {
      ElMessage.success(item.label)
    }
    await refresh()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '发起失败')
  } finally {
    launchingKey.value = ''
  }
}
</script>

<template>
  <section class="exports-page">
    <div class="panel exports-panel">
      <div class="exports-toolbar">
        <el-tabs :model-value="query.tab" class="exports-tabs" @tab-change="handleTabChange">
          <el-tab-pane label="终端交付" name="terminal" />
          <el-tab-pane label="设备清单" name="device" />
          <el-tab-pane label="业务清单" name="business" />
          <el-tab-pane label="统计报表" name="statistics" />
        </el-tabs>

        <div class="exports-controls">
          <el-input
            v-model="filterDraft"
            :placeholder="filterPlaceholder"
            clearable
            @clear="applyFilter('')"
            @keyup.enter="applyFilter()"
          >
            <template #append>
              <el-button :icon="Search" @click="applyFilter()" />
            </template>
          </el-input>
          <el-tooltip content="刷新" placement="top">
            <el-button circle :icon="Refresh" @click="refresh" />
          </el-tooltip>
        </div>
      </div>

      <el-alert v-if="errorMessage" type="error" :title="errorMessage" show-icon :closable="false" />

      <TerminalDeliveryTab
        v-if="query.tab === 'terminal'"
        :items="terminalPage.items"
        :loading="loading"
        :launching-key="launchingKey"
        :downloading-job-id="downloadingJobId"
        @launch="handleLaunchTerminal"
        @download="handleDownloadTerminal"
        @refresh="refresh"
      />

      <ExportCatalogTab
        v-else
        :items="pagedCatalogItems"
        :loading="loading"
        :launching-key="launchingKey"
        :selected-task-id="selectedTaskId"
        :task-options="taskOptions"
        :task-loading="taskLoading"
        @update:selected-task-id="handleSelectedTaskId"
        @task-query="handleTaskQuery"
        @launch="handleLaunchCatalog"
      />

      <el-pagination
        class="exports-pagination"
        layout="sizes, prev, pager, next, total"
        :current-page="query.terminalPage"
        :page-size="query.terminalPageSize"
        :page-sizes="EXPORT_CENTER_PAGE_SIZES"
        :total="primaryTotal"
        @current-change="setTerminalPage"
        @size-change="handlePrimaryPageSize"
      />
    </div>

    <div class="panel exports-panel">
      <ExportJobsTable
        :jobs="visibleJobs"
        :labels="catalogLabels"
        :loading="jobsLoading"
        :downloading-job-id="downloadingJobId"
        @download="handleDownloadJob"
      />

      <el-pagination
        class="exports-pagination jobs-pagination"
        layout="sizes, prev, pager, next, total"
        :current-page="jobsPage.page"
        :page-size="jobsPage.pageSize"
        :page-sizes="EXPORT_CENTER_PAGE_SIZES"
        :total="jobsPage.total"
        @current-change="setJobPage"
        @size-change="handleJobPageSize"
      />
    </div>
  </section>
</template>

<style scoped>
.exports-page {
  display: grid;
  gap: 12px;
}

.exports-panel {
  padding: 18px;
}

.exports-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: end;
  margin-bottom: 14px;
}

.exports-tabs {
  min-width: 0;
}

.exports-controls {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.exports-controls .el-input {
  width: 280px;
  max-width: 100%;
}

.exports-pagination {
  margin-top: 14px;
  justify-content: flex-end;
}

.jobs-pagination {
  margin-top: 12px;
}

@media (max-width: 980px) {
  .exports-toolbar {
    grid-template-columns: 1fr;
  }

  .exports-controls {
    justify-content: stretch;
  }

  .exports-controls .el-input {
    width: 100%;
  }
}
</style>
