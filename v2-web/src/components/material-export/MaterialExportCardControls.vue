<script setup lang="ts">
import type { MaterialExportTerminalSummary } from '../../api/types'

const props = defineProps<{
  taskId: string
  terminalCode: string
  summary?: MaterialExportTerminalSummary
  selected: boolean
  disabled: boolean
  busy: boolean
}>()

const emit = defineEmits<{
  selected: [value: boolean]
  count: [value: number]
  export: []
}>()

function countChanged(value: number | undefined) {
  emit('count', Math.max(0, Math.trunc(Number(value || 0))))
}
</script>

<template>
  <div class="material-export-card" data-testid="material-export-card">
    <ElCheckbox :model-value="selected" :disabled="disabled || busy" @change="emit('selected', Boolean($event))">导出</ElCheckbox>
    <label>
      <span>应还采集器</span>
      <ElInputNumber
        :data-testid="`material-export-count-${terminalCode}`"
        :model-value="summary?.requestedCollectorCount || 0"
        :min="0"
        :max="999"
        :disabled="disabled || busy"
        controls-position="right"
        size="small"
        @change="countChanged"
      />
    </label>
    <small v-if="summary">最终 {{ summary.finalCollectorCount }} 个</small>
    <ElButton size="small" type="success" plain :loading="busy" :disabled="disabled" @click="emit('export')">导出资料</ElButton>
  </div>
</template>

<style scoped>
.material-export-card { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding-top: 8px; border-top: 1px dashed #dfe6ee; }
.material-export-card label { display: flex; align-items: center; gap: 6px; color: #64748b; font-size: 12px; }
.material-export-card :deep(.el-input-number) { width: 96px; }
.material-export-card small { color: #64748b; }
</style>
