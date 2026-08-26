<script setup lang="ts">
import { finalizeDataCenterUnmatchedToGroup } from '@/api/services'
import type { DataCenterRow } from '@/api/types'
import DataCenterGroupReviewPanel from '@/components/data-center/DataCenterGroupReviewPanel.vue'
import UnmatchedReviewDialog from '@/components/UnmatchedReviewDialog.vue'

const props = defineProps<{
  modelValue: boolean
  row: DataCenterRow | null
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'updated'): void
  (event: 'matched', value: unknown): void
}>()

function close() {
  emit('update:modelValue', false)
}

async function finalizeDataCenterUnmatchedFromDialog(payload: {
  unmatchedId: string
  terminal: string
  meterNo: string
  candidateKey: string
  expectedVersion: number
}) {
  const result = await finalizeDataCenterUnmatchedToGroup(payload.unmatchedId, {
    terminal: payload.terminal,
    meterNo: payload.meterNo,
    candidateKey: payload.candidateKey,
    expectedVersion: payload.expectedVersion,
  })
  return result.groupId
}
</script>

<template>
  <UnmatchedReviewDialog
    v-if="props.row?.kind === 'unmatched'"
    :model-value="props.modelValue"
    :unmatched-id="props.row.id"
    :data-center="true"
    :finalize-match="finalizeDataCenterUnmatchedFromDialog"
    @update:model-value="emit('update:modelValue', $event)"
    @updated="emit('updated')"
    @matched="emit('matched', $event)"
  />

  <el-dialog
    v-else
    :model-value="props.modelValue && props.row?.kind === 'group'"
    width="min(1180px, 96vw)"
    class="data-center-review-dialog"
    append-to-body
    destroy-on-close
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="review-title">
        <strong>{{ props.row?.meterNo || props.row?.id }}</strong>
        <span>{{ props.row?.terminal }}</span>
      </div>
    </template>

    <DataCenterGroupReviewPanel
      v-if="props.row?.kind === 'group'"
      :group-id="props.row.id"
      @updated="emit('updated')"
      @review-decided="emit('updated')"
    />

    <template #footer>
      <el-button @click="close">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.review-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.review-title strong {
  color: var(--v2-text-strong);
}

.review-title span {
  color: var(--v2-text-muted);
  font-size: 13px;
}
</style>
