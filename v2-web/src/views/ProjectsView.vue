<script setup lang="ts">
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { useWorkspaceStore } from '@/stores/workspace'

const workspace = useWorkspaceStore()
</script>

<template>
  <div class="page-stack">
    <div class="toolbar">
      <div>
        <h2>项目管理</h2>
        <p>项目创建、状态查看和导入入口占位。</p>
      </div>
      <ElButton type="primary" :icon="Plus" @click="ElMessage.info('项目创建接口待接入')">新建项目</ElButton>
    </div>

    <section class="panel">
      <div class="panel-body">
        <ElTable :data="workspace.projects" stripe>
          <ElTableColumn prop="name" label="项目名称" min-width="220" />
          <ElTableColumn prop="status" label="状态" width="120">
            <template #default="{ row }">
              <ElTag :type="row.status === 'active' ? 'success' : 'info'">
                {{ row.status === 'active' ? '进行中' : '已归档' }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="totalGroups" label="资料组总数" width="130" />
          <ElTableColumn prop="completedGroups" label="已完成" width="120" />
          <ElTableColumn prop="exceptionGroups" label="异常" width="100" />
          <ElTableColumn prop="updatedAt" label="更新时间" width="170" />
          <ElTableColumn label="操作" width="220" fixed="right">
            <template #default>
              <ElButton size="small" @click="ElMessage.info('总清单导入接口待接入')">导入总清单</ElButton>
              <ElButton size="small" @click="ElMessage.info('阶段清单导入接口待接入')">导入阶段清单</ElButton>
            </template>
          </ElTableColumn>
        </ElTable>
      </div>
    </section>
  </div>
</template>
