<script setup lang="ts">
import { Download } from '@element-plus/icons-vue'

import type { ExportCatalogItem } from '@/api/types'

const props = defineProps<{
  items: ExportCatalogItem[]
  loading?: boolean
  launchingKey?: string
  selectedTaskId?: string
  taskOptions?: Array<{ value: string; label: string }>
  taskLoading?: boolean
}>()

const emit = defineEmits<{
  launch: [item: ExportCatalogItem]
  'update:selected-task-id': [value: string]
}>()

function modeLabel(mode: ExportCatalogItem['mode']) {
  return mode === 'background' ? '后台' : '即时'
}

function requiresTask(row: ExportCatalogItem) {
  return row.requiredFilters?.some((item) => item.key === 'task_id' && item.kind === 'task') ?? false
}

function canLaunch(row: ExportCatalogItem) {
  return !requiresTask(row) || Boolean(props.selectedTaskId)
}
</script>

<template>
  <el-empty v-if="!loading && !items.length" description="暂无清单" />

  <el-table v-else v-loading="loading" :data="items" row-key="key" class="catalog-table">
    <el-table-column prop="label" label="名称" min-width="220" />
    <el-table-column label="筛选" min-width="260">
      <template #default="{ row }">
        <el-select
          v-if="requiresTask(row)"
          :model-value="selectedTaskId"
          filterable
          clearable
          :loading="taskLoading"
          placeholder="选择任务"
          @update:model-value="emit('update:selected-task-id', String($event || ''))"
        >
          <el-option v-for="item in taskOptions || []" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <span v-else>-</span>
      </template>
    </el-table-column>
    <el-table-column prop="key" label="类型" min-width="180" />
    <el-table-column prop="delivery" label="格式" width="92" />
    <el-table-column label="模式" width="92">
      <template #default="{ row }">{{ modeLabel(row.mode) }}</template>
    </el-table-column>
    <el-table-column label="操作" width="92" fixed="right">
      <template #default="{ row }">
        <div class="row-actions">
          <el-tooltip content="发起" placement="top">
            <el-button
              circle
              type="primary"
              :icon="Download"
              :loading="launchingKey === row.key"
              :disabled="!canLaunch(row)"
              @click="emit('launch', row)"
            />
          </el-tooltip>
        </div>
      </template>
    </el-table-column>
  </el-table>
</template>

<style scoped>
.catalog-table {
  width: 100%;
}

.row-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
