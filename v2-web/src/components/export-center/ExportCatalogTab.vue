<script setup lang="ts">
import { Download } from '@element-plus/icons-vue'

import type { ExportCatalogItem } from '@/api/types'

defineProps<{
  items: ExportCatalogItem[]
  loading?: boolean
  launchingKey?: string
}>()

const emit = defineEmits<{
  launch: [item: ExportCatalogItem]
}>()

function modeLabel(mode: ExportCatalogItem['mode']) {
  return mode === 'background' ? '后台' : '即时'
}
</script>

<template>
  <el-empty v-if="!loading && !items.length" description="暂无清单" />

  <el-table v-else v-loading="loading" :data="items" row-key="key" class="catalog-table">
    <el-table-column prop="label" label="名称" min-width="220" />
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
