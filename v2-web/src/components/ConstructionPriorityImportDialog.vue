<script setup lang="ts">
import { Download, Upload } from '@element-plus/icons-vue'
import { computed, ref, watch } from 'vue'
import type { UploadFile } from 'element-plus'

import {
  confirmConstructionPriorityImport,
  downloadConstructionPriorityTemplate,
  previewConstructionPriorityImport,
} from '@/api/services'
import { createConstructionPriorityImportSession } from '@/api/constructionPriorityImportState.mjs'
import type { ConstructionPriorityImportResult } from '@/api/types'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  imported: []
}>()

const pageSize = 20
const selectedFile = ref<File | null>(null)
const preview = ref<ConstructionPriorityImportResult | null>(null)
const currentPage = ref(1)
const errorMessage = ref('')
const previewing = ref(false)
const confirming = ref(false)
const downloadingTemplate = ref(false)
const requestSession = createConstructionPriorityImportSession()

const items = computed(() => preview.value?.items || [])
const totalPages = computed(() => Math.max(1, Math.ceil(items.value.length / pageSize)))
const pagedItems = computed(() => items.value.slice((currentPage.value - 1) * pageSize, currentPage.value * pageSize))
const blockingPreview = computed(() => Boolean(preview.value?.counts.conflict || preview.value?.counts.malformed))
const canConfirm = computed(() => Boolean(selectedFile.value && preview.value && !blockingPreview.value && !previewing.value && !confirming.value))

const statusLabels = {
  valid: '有效',
  duplicate: '重复',
  conflict: '冲突',
  unknown: '未知',
  completed: '已完成',
  unchanged: '未变化',
  malformed: '格式错误',
} as const

function statusLabel(status: string) {
  return statusLabels[status as keyof typeof statusLabels] || status
}

function reset() {
  requestSession.invalidate()
  selectedFile.value = null
  preview.value = null
  currentPage.value = 1
  errorMessage.value = ''
  previewing.value = false
  confirming.value = false
}

function closeDialog() {
  reset()
  emit('update:modelValue', false)
}

function selectFile(file: UploadFile) {
  requestSession.invalidate()
  selectedFile.value = file.raw || null
  preview.value = null
  currentPage.value = 1
  errorMessage.value = ''
}

async function downloadTemplate() {
  if (downloadingTemplate.value) return
  downloadingTemplate.value = true
  errorMessage.value = ''
  try {
    await downloadConstructionPriorityTemplate()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '下载模板失败'
  } finally {
    downloadingTemplate.value = false
  }
}

async function previewImport() {
  if (!selectedFile.value || previewing.value || confirming.value) return
  const requestToken = requestSession.begin()
  previewing.value = true
  errorMessage.value = ''
  try {
    const result = await previewConstructionPriorityImport(selectedFile.value)
    if (!requestSession.isCurrent(requestToken)) return
    preview.value = result
    currentPage.value = 1
  } catch (error) {
    if (!requestSession.isCurrent(requestToken)) return
    errorMessage.value = error instanceof Error ? error.message : '预览失败'
  } finally {
    if (!requestSession.isCurrent(requestToken)) return
    previewing.value = false
  }
}

async function confirmImport() {
  if (!selectedFile.value || !canConfirm.value) return
  const requestToken = requestSession.begin()
  confirming.value = true
  errorMessage.value = ''
  try {
    const result = await confirmConstructionPriorityImport(selectedFile.value)
    if (requestSession.isCurrent(requestToken) && result.confirmed) emit('imported')
  } catch (error) {
    if (!requestSession.isCurrent(requestToken)) return
    errorMessage.value = error instanceof Error ? error.message : '确认导入失败'
  } finally {
    if (!requestSession.isCurrent(requestToken)) return
    confirming.value = false
  }
}

watch(
  () => props.modelValue,
  () => {
    reset()
  },
)

watch(totalPages, (pages) => {
  if (currentPage.value > pages) currentPage.value = pages
})
</script>

<template>
  <ElDialog
    :model-value="modelValue"
    width="min(980px, 96vw)"
    class="construction-priority-import-dialog"
    append-to-body
    :close-on-click-modal="false"
    @update:model-value="closeDialog"
    @closed="reset"
  >
    <template #header><strong>批量标记优先施工</strong></template>

    <ElAlert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon />

    <div class="priority-import-actions">
      <ElTooltip content="下载模板">
        <ElButton circle :icon="Download" :loading="downloadingTemplate" aria-label="下载模板" @click="downloadTemplate" />
      </ElTooltip>
      <ElUpload accept=".xlsx" :auto-upload="false" :show-file-list="false" :on-change="selectFile" :disabled="previewing || confirming">
        <ElButton :icon="Upload">选择文件</ElButton>
      </ElUpload>
      <span class="priority-import-file">{{ selectedFile?.name || '未选择文件' }}</span>
      <ElButton :loading="previewing" :disabled="!selectedFile || confirming" @click="previewImport">预览</ElButton>
    </div>

    <template v-if="preview">
      <div class="priority-import-counts">
        <ElTag v-for="(count, status) in preview.counts" :key="status" size="small" effect="plain">
          {{ statusLabel(status) }} {{ count }}
        </ElTag>
      </div>

      <div class="priority-import-table-wrap">
        <ElTable :data="pagedItems" size="small" border class="priority-import-table">
          <ElTableColumn prop="row_number" label="行号" width="72" align="center" />
          <ElTableColumn prop="terminal" label="终端号" min-width="150" show-overflow-tooltip />
          <ElTableColumn label="目标值" width="94" align="center">
            <template #default="{ row }">{{ row.priority === null ? '-' : row.priority ? '是' : '否' }}</template>
          </ElTableColumn>
          <ElTableColumn label="分类" width="104" align="center">
            <template #default="{ row }">{{ statusLabel(row.status) }}</template>
          </ElTableColumn>
          <ElTableColumn label="原因" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">{{ row.reason || '-' }}</template>
          </ElTableColumn>
        </ElTable>
      </div>

      <div class="priority-import-footer">
        <ElPagination
          v-model:current-page="currentPage"
          background
          small
          layout="total, prev, pager, next"
          :total="items.length"
          :page-size="pageSize"
        />
        <ElButton type="primary" :loading="confirming" :disabled="!canConfirm" @click="confirmImport">确认导入</ElButton>
      </div>
    </template>

    <template #footer><ElButton @click="closeDialog">关闭</ElButton></template>
  </ElDialog>
</template>

<style scoped>
.priority-import-actions, .priority-import-footer { display: flex; min-width: 0; align-items: center; gap: 8px; }
.priority-import-actions { flex-wrap: wrap; }
.priority-import-file { min-width: 0; flex: 1 1 180px; overflow: hidden; color: var(--el-text-color-secondary); text-overflow: ellipsis; white-space: nowrap; }
.priority-import-counts { display: flex; flex-wrap: wrap; gap: 6px; padding: 14px 0; }
.priority-import-table-wrap { overflow-x: auto; }
.priority-import-table { min-width: 720px; }
.priority-import-footer { justify-content: space-between; padding-top: 14px; }

@media (max-width: 640px) {
  .priority-import-footer { align-items: stretch; flex-direction: column; }
  .priority-import-footer :deep(.el-pagination) { justify-content: center; }
  .priority-import-footer :deep(.el-button) { width: 100%; }
}
</style>
