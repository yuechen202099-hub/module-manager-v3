<script setup lang="ts">
defineProps<{
  selectedCount: number
  allSelected: boolean
  running: boolean
  paused: boolean
  hasJob: boolean
  progressText: string
}>()

defineEmits<{
  selectAll: [selected: boolean]
  export: []
  pause: []
  resume: []
  release: []
}>()
</script>

<template>
  <div class="material-export-toolbar" data-testid="material-export-toolbar">
    <ElCheckbox :model-value="allSelected" @change="$emit('selectAll', Boolean($event))">全选当前结果</ElCheckbox>
    <span>已选 {{ selectedCount }} 个终端</span>
    <ElButton
      data-testid="material-export-batch"
      size="small"
      type="success"
      :loading="running"
      :disabled="!selectedCount"
      @click="$emit('export')"
    >
      一键导出已勾选终端
    </ElButton>
    <ElButton
      v-if="running && hasJob"
      data-testid="material-export-pause"
      size="small"
      type="warning"
      plain
      @click="$emit('pause')"
    >
      当前文件完成后暂停
    </ElButton>
    <ElButton
      v-if="paused && hasJob"
      data-testid="material-export-resume"
      size="small"
      type="primary"
      plain
      @click="$emit('resume')"
    >
      继续导出
    </ElButton>
    <ElButton
      v-if="paused && hasJob"
      data-testid="material-export-release"
      size="small"
      type="danger"
      text
      @click="$emit('release')"
    >
      取消并释放占用
    </ElButton>
    <span v-if="progressText" class="material-export-progress">{{ progressText }}</span>
  </div>
</template>

<style scoped>
.material-export-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; color: #5e6b7a; font-size: 13px; }
.material-export-progress { color: #15803d; }
</style>
