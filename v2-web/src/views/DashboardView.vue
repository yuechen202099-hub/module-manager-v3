<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'

import StatusTag from '@/components/StatusTag.vue'
import { useWorkspaceStore } from '@/stores/workspace'

const workspace = useWorkspaceStore()
</script>

<template>
  <div class="page-stack">
    <div class="toolbar">
      <div>
        <h2>项目进度</h2>
        <p>按资料组维度展示审阅进度和异常积压。</p>
      </div>
      <ElButton :icon="Refresh" :loading="workspace.loading" @click="workspace.bootstrap()">刷新</ElButton>
    </div>

    <section class="metric-grid">
      <div class="metric-card">
        <span>总资料组</span>
        <strong>{{ workspace.dashboardStats.totalGroups.toLocaleString() }}</strong>
      </div>
      <div class="metric-card">
        <span>已完成</span>
        <strong>{{ workspace.dashboardStats.completedGroups.toLocaleString() }}</strong>
      </div>
      <div class="metric-card">
        <span>异常组</span>
        <strong>{{ workspace.dashboardStats.exceptionGroups.toLocaleString() }}</strong>
      </div>
      <div class="metric-card">
        <span>进行中任务</span>
        <strong>{{ workspace.dashboardStats.activeTasks }}</strong>
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <h3>任务概览</h3>
      </div>
      <div class="panel-body">
        <ElTable :data="workspace.tasks" stripe>
          <ElTableColumn prop="name" label="任务" min-width="220" />
          <ElTableColumn prop="stage" label="阶段" width="110" />
          <ElTableColumn label="状态" width="120">
            <template #default="{ row }">
              <StatusTag :status="row.status" />
            </template>
          </ElTableColumn>
          <ElTableColumn prop="totalGroups" label="资料组" width="110" />
          <ElTableColumn prop="completedGroups" label="已完成" width="110" />
          <ElTableColumn prop="ownerName" label="负责人" width="140" />
        </ElTable>
      </div>
    </section>
  </div>
</template>
