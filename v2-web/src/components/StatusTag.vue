<script setup lang="ts">
import type { TaskStatus } from '@/api/types'

defineProps<{
  status: TaskStatus
}>()

const statusMap: Record<TaskStatus, { label: string; type: 'primary' | 'success' | 'warning' | 'danger' | 'info' }> = {
  pending: { label: '待领取', type: 'info' },
  in_review: { label: '审阅中', type: 'primary' },
  complete: { label: '已完成', type: 'success' },
  exception: { label: '异常', type: 'danger' },
  incomplete: { label: '不完整', type: 'warning' },
  locked: { label: '锁定', type: 'info' },
}
</script>

<template>
  <ElTag :type="statusMap[status].type" effect="light" round>
    {{ statusMap[status].label }}
  </ElTag>
</template>
