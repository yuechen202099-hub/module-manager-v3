<script setup lang="ts">
import { Download, FolderOpened, Refresh } from '@element-plus/icons-vue'

import type { TerminalReadinessItem } from '@/api/types'

const props = defineProps<{
  items: TerminalReadinessItem[]
  loading?: boolean
  launchingKey?: string
  downloadingJobId?: string
}>()

const emit = defineEmits<{
  launch: [payload: { terminal: string; reviewScope: 'reviewed' | 'all' }]
  download: [terminal: string]
  refresh: []
}>()

function statusType(value: TerminalReadinessItem['status']) {
  return value === 'ready' ? 'success' : 'danger'
}

function formatDateTime(value = '') {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('zh-CN', { hour12: false })
}

function blockerText(row: TerminalReadinessItem) {
  return row.blockers.length ? row.blockers.join('；') : '-'
}

function launchKey(terminal: string, reviewScope: 'reviewed' | 'all') {
  return `${terminal}:${reviewScope}`
}
</script>

<template>
  <el-empty v-if="!loading && !items.length" description="暂无终端" />

  <el-table v-else v-loading="loading" :data="items" row-key="terminal" class="terminal-table">
    <el-table-column prop="terminal" label="终端" min-width="140" />
    <el-table-column prop="groupCount" label="资料组" width="88" />
    <el-table-column prop="constructedCount" label="施工" width="88" />
    <el-table-column prop="archivedCount" label="归档" width="88" />
    <el-table-column prop="cacheReadyCount" label="缓存" width="88" />
    <el-table-column label="状态" width="90">
      <template #default="{ row }">
        <el-tag size="small" effect="plain" :type="statusType(row.status)">
          {{ row.status === 'ready' ? '可发起' : '阻断' }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column label="阻断" min-width="280" show-overflow-tooltip>
      <template #default="{ row }">{{ blockerText(row) }}</template>
    </el-table-column>
    <el-table-column label="最近生成" min-width="240">
      <template #default="{ row }">
        <span>{{ formatDateTime(row.latestGeneratedAt) }}</span>
      </template>
    </el-table-column>
    <el-table-column label="操作" width="154" fixed="right">
      <template #default="{ row }">
        <div class="row-actions">
          <el-tooltip content="刷新" placement="top">
            <el-button circle :icon="Refresh" @click="emit('refresh')" />
          </el-tooltip>
          <el-tooltip content="生成已审阅" placement="top">
            <el-button
              circle
              type="primary"
              :icon="FolderOpened"
              :loading="launchingKey === launchKey(row.terminal, 'reviewed')"
              :disabled="row.status !== 'ready'"
              @click="emit('launch', { terminal: row.terminal, reviewScope: 'reviewed' })"
            />
          </el-tooltip>
          <el-tooltip content="生成全部" placement="top">
            <el-button
              circle
              type="warning"
              :icon="FolderOpened"
              :loading="launchingKey === launchKey(row.terminal, 'all')"
              :disabled="row.status !== 'ready'"
              @click="emit('launch', { terminal: row.terminal, reviewScope: 'all' })"
            />
          </el-tooltip>
          <el-tooltip content="下载最近" placement="top">
            <el-button
              circle
              :icon="Download"
              :loading="downloadingJobId === row.terminal"
              :disabled="row.status !== 'ready'"
              @click="emit('download', row.terminal)"
            />
          </el-tooltip>
        </div>
      </template>
    </el-table-column>
  </el-table>
</template>

<style scoped>
.terminal-table {
  width: 100%;
}

.row-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

</style>
