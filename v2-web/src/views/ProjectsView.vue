<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { useWorkspaceStore } from '@/stores/workspace'
import type { Project } from '@/api/types'

const workspace = useWorkspaceStore()
const route = useRoute()
const router = useRouter()

onMounted(() => {
  void loadProjectsFromRoute()
})

async function refreshProjects() {
  await workspace.loadProjects()
  selectRouteProject()
  ElMessage.success('项目状态已更新')
}

async function loadProjectsFromRoute() {
  await workspace.loadProjects()
  selectRouteProject()
}

function selectRouteProject() {
  const projectId = String(route.query.project_id || '')
  if (projectId) workspace.selectProject(projectId)
}

function openRoute(path: string, project: Project) {
  workspace.selectProject(project.id)
  void router.push({ path, query: { project_id: project.id } })
}

function projectRowClass({ row }: { row: Project }) {
  return row.id === workspace.activeProjectId ? 'active-project-row' : ''
}

function formatUpdatedAt(value: string) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function deliveryLabel(status = '') {
  return status === 'ready' ? '可交付' : '准备中'
}

function deliveryType(status = '') {
  return status === 'ready' ? 'success' : 'warning'
}

function progressStatus(value = 0, riskTotal = 0) {
  if (riskTotal > 0) return 'exception'
  return value >= 100 ? 'success' : undefined
}
</script>

<template>
  <div class="page-stack">
    <div class="toolbar">
      <div>
        <h2>项目管理</h2>
        <p>进度、交付、现场采集、审阅与风险统一视图。</p>
      </div>
      <div class="toolbar-actions">
        <ElButton :icon="Refresh" @click="refreshProjects">刷新</ElButton>
        <ElButton type="primary" :icon="Plus" @click="ElMessage.info('项目创建接口待接入')">新建项目</ElButton>
      </div>
    </div>

    <section class="panel">
      <div class="panel-body">
        <ElTable :data="workspace.projects" stripe :row-class-name="projectRowClass">
          <ElTableColumn label="项目" min-width="220" fixed>
            <template #default="{ row }">
              <div class="project-cell">
                <strong>{{ row.name }}</strong>
                <span>{{ row.stage || '准备中' }}</span>
              </div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="状态" width="110">
            <template #default="{ row }">
              <ElTag :type="row.status === 'active' ? 'success' : 'info'">
                {{ row.status === 'active' ? '进行中' : '已归档' }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="项目进度" min-width="180">
            <template #default="{ row }">
              <ElProgress
                :percentage="row.managementProgress || 0"
                :status="progressStatus(row.managementProgress, row.risks?.total)"
              />
              <div class="subline">{{ row.completedGroups }} / {{ row.totalGroups }} 组</div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="交付能力" min-width="150">
            <template #default="{ row }">
              <ElTag :type="deliveryType(row.delivery?.status)">
                {{ deliveryLabel(row.delivery?.status) }}
              </ElTag>
              <div class="subline">{{ row.delivery?.completedItems || 0 }} / {{ row.delivery?.totalItems || 0 }} 项</div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="现场采集" min-width="150">
            <template #default="{ row }">
              <div class="metric-pair">
                <span>照片 {{ row.field?.photoRowsLinked || 0 }}</span>
                <span>未施工 {{ row.field?.unconstructedGroups || 0 }}</span>
              </div>
              <ElTag v-if="row.field?.exceptionCount" type="danger" size="small">
                异常 {{ row.field.exceptionCount }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="审阅" min-width="150">
            <template #default="{ row }">
              <ElProgress :percentage="row.review?.reviewRate || 0" />
              <div class="subline">待审 {{ row.review?.pendingGroups || 0 }} 组</div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="任务中心" min-width="150">
            <template #default="{ row }">
              <div class="metric-pair">
                <span>上传 {{ row.tasks?.uploaded || 0 }}</span>
                <span>审阅中 {{ row.tasks?.reviewing || 0 }}</span>
              </div>
              <div class="subline">归档 {{ row.tasks?.archived || 0 }} / {{ row.tasks?.total || 0 }}</div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="风险" width="110">
            <template #default="{ row }">
              <ElTag :type="row.risks?.total ? 'danger' : 'success'">
                {{ row.risks?.total || 0 }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="更新时间" width="130">
            <template #default="{ row }">
              {{ formatUpdatedAt(row.updatedAt) }}
            </template>
          </ElTableColumn>
          <ElTableColumn label="操作" width="310" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <ElButton size="small" @click="openRoute('/project-board', row)">看板</ElButton>
                <ElButton size="small" @click="openRoute('/claim-tasks', row)">任务</ElButton>
                <ElButton size="small" @click="openRoute('/construction', row)">现场</ElButton>
                <ElButton size="small" @click="openRoute('/task-hall', row)">审阅</ElButton>
              </div>
            </template>
          </ElTableColumn>
        </ElTable>
      </div>
    </section>
  </div>
</template>

<style scoped>
.toolbar-actions,
.row-actions,
.metric-pair {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar-actions,
.row-actions {
  flex-wrap: wrap;
}

.project-cell {
  display: grid;
  gap: 4px;
}

.project-cell strong {
  color: var(--el-text-color-primary);
}

.project-cell span,
.subline,
.metric-pair {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.metric-pair {
  justify-content: flex-start;
}

:deep(.active-project-row td) {
  background: rgba(37, 99, 235, 0.06) !important;
}
</style>
