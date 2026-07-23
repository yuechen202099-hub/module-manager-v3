<script setup lang="ts">
import { Download } from '@element-plus/icons-vue'

import type { ExportJob } from '@/api/types'

const props = defineProps<{
  jobs: ExportJob[]
  labels?: Record<string, string>
  loading?: boolean
  downloadingJobId?: string
}>()

const emit = defineEmits<{
  download: [job: ExportJob]
}>()

function typeLabel(value: string) {
  return props.labels?.[value] || value || '-'
}

function statusType(value: string) {
  if (value === 'succeeded') return 'success'
  if (value === 'failed') return 'danger'
  if (value === 'pending' || value === 'processing') return 'warning'
  return 'info'
}

function formatDateTime(value = '') {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('zh-CN', { hour12: false })
}

function scopeSummary(job: ExportJob) {
  const filters = job.filters || {}
  const parts: string[] = []
  const terminal = String(filters.terminal || '')
  const reviewScope = String(filters.review_scope || '')
  if (terminal) parts.push(`终端 ${terminal}`)
  if (reviewScope) parts.push(reviewScope === 'all' ? '全部' : '已审阅')
  if (!parts.length) {
    const entries = Object.entries(filters)
      .filter(([, value]) => String(value || '').trim())
      .slice(0, 2)
      .map(([key, value]) => `${key} ${String(value)}`)
    return entries.length ? entries.join(' / ') : '-'
  }
  return parts.join(' / ')
}
</script>

<template>
  <el-empty v-if="!loading && !jobs.length" description="暂无记录" />

  <el-table v-else v-loading="loading" :data="jobs" row-key="id" class="jobs-table">
    <el-table-column label="类型" min-width="168" show-overflow-tooltip>
      <template #default="{ row }">{{ typeLabel(row.jobType) }}</template>
    </el-table-column>
    <el-table-column label="范围" min-width="188" show-overflow-tooltip>
      <template #default="{ row }">{{ scopeSummary(row) }}</template>
    </el-table-column>
    <el-table-column prop="rowCount" label="行数" width="82" />
    <el-table-column label="创建人" min-width="120" show-overflow-tooltip>
      <template #default="{ row }">{{ row.createdBy || '-' }}</template>
    </el-table-column>
    <el-table-column label="时间" min-width="200">
      <template #default="{ row }">
        <div class="stack-cell">
          <span>{{ formatDateTime(row.createdAt) }}</span>
          <span class="stack-subtle">{{ formatDateTime(row.finishedAt) }}</span>
        </div>
      </template>
    </el-table-column>
    <el-table-column label="状态" width="96">
      <template #default="{ row }">
        <el-tag size="small" effect="plain" :type="statusType(row.status)">
          {{ row.status || '-' }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column label="失败原因" min-width="220" show-overflow-tooltip>
      <template #default="{ row }">{{ row.errorMessage || '-' }}</template>
    </el-table-column>
    <el-table-column label="下载" width="82" fixed="right">
      <template #default="{ row }">
        <div class="row-actions">
          <el-tooltip content="下载" placement="top">
            <el-button
              circle
              :icon="Download"
              :loading="downloadingJobId === row.id"
              :disabled="row.status !== 'succeeded'"
              @click="emit('download', row)"
            />
          </el-tooltip>
        </div>
      </template>
    </el-table-column>
  </el-table>
</template>

<style scoped>
.jobs-table {
  width: 100%;
}

.row-actions {
  display: flex;
  justify-content: flex-end;
}

.stack-cell {
  display: grid;
  gap: 4px;
}

.stack-subtle {
  color: var(--v2-text-muted);
  font-size: 12px;
}
</style>
