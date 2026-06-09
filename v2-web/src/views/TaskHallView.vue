<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import StatusTag from '@/components/StatusTag.vue'
import { useWorkspaceStore } from '@/stores/workspace'

const router = useRouter()
const workspace = useWorkspaceStore()

async function claim(taskId: string) {
  await workspace.claimTask(taskId)
  ElMessage.success('已领取任务，占位接口已返回')
}
</script>

<template>
  <div class="page-stack">
    <div class="toolbar">
      <div>
        <h2>任务大厅</h2>
        <p>审阅员可领取已发布任务，管理员可查看全部任务。</p>
      </div>
    </div>

    <section class="panel">
      <div class="panel-body">
        <ElTable :data="workspace.tasks" stripe>
          <ElTableColumn prop="name" label="任务名称" min-width="240" />
          <ElTableColumn prop="stage" label="阶段" width="100" />
          <ElTableColumn label="状态" width="120">
            <template #default="{ row }">
              <StatusTag :status="row.status" />
            </template>
          </ElTableColumn>
          <ElTableColumn label="进度" width="210">
            <template #default="{ row }">
              <ElProgress :percentage="Math.round((row.completedGroups / row.totalGroups) * 100)" />
            </template>
          </ElTableColumn>
          <ElTableColumn prop="totalGroups" label="资料组" width="110" />
          <ElTableColumn prop="ownerName" label="领取人" width="140">
            <template #default="{ row }">
              {{ row.ownerName || '未领取' }}
            </template>
          </ElTableColumn>
          <ElTableColumn label="操作" width="190" fixed="right">
            <template #default="{ row }">
              <ElButton size="small" type="primary" :disabled="row.status === 'locked'" @click="claim(row.id)">
                领取
              </ElButton>
              <ElButton size="small" @click="router.push('/review/g-001')">审阅</ElButton>
            </template>
          </ElTableColumn>
        </ElTable>
      </div>
    </section>
  </div>
</template>
