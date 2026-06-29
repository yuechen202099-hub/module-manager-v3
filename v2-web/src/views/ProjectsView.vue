<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { useWorkspaceStore } from '@/stores/workspace'
import type { Project, ProjectModule } from '@/api/types'

const workspace = useWorkspaceStore()
const route = useRoute()
const router = useRouter()
const fallbackModules: ProjectModule[] = [
  { id: 'progress', name: '项目进度', priority: 10, endpoint: '', routePath: '/project-board' },
  { id: 'delivery', name: '项目交付能力', priority: 20, endpoint: '', routePath: '/project-board' },
  { id: 'field', name: '现场采集', priority: 30, endpoint: '', routePath: '/construction' },
  { id: 'review', name: '审阅功能', priority: 40, endpoint: '', routePath: '/task-hall' },
]
const defaultModuleIds = ['progress', 'delivery', 'field', 'review']
const createDialogVisible = ref(false)
const creatingProject = ref(false)
const createForm = reactive({
  name: '',
  description: '',
  moduleIds: [...defaultModuleIds],
})

const moduleOptions = computed(() => {
  const knownModules = workspace.projects.flatMap((project) => project.modules)
  const modules = knownModules.length ? knownModules : fallbackModules
  const uniqueModules = new Map(modules.map((module) => [module.id, module]))
  return Array.from(uniqueModules.values()).sort((left, right) => left.priority - right.priority)
})

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
  workspace.selectRouteProject(route.query.project_id)
}

function openCreateDialog() {
  createDialogVisible.value = true
}

function resetCreateForm() {
  createForm.name = ''
  createForm.description = ''
  createForm.moduleIds = [...defaultModuleIds]
}

async function submitCreateProject() {
  const name = createForm.name.trim()
  if (!name) {
    ElMessage.warning('请填写项目名称')
    return
  }
  if (!createForm.moduleIds.length) {
    ElMessage.warning('请至少选择一个模块')
    return
  }
  creatingProject.value = true
  try {
    const project = await workspace.createProjectDraft({
      name,
      description: createForm.description.trim(),
      moduleIds: createForm.moduleIds,
    })
    createDialogVisible.value = false
    resetCreateForm()
    ElMessage.success(`已创建项目草稿：${project.name}`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '项目草稿创建失败')
  } finally {
    creatingProject.value = false
  }
}

function openRoute(path: string, project: Project) {
  workspace.selectProject(project.id)
  void router.push({ path, query: { project_id: project.id } })
}

function projectActionModules(project: Project) {
  const modules = project.modules.length ? project.modules : fallbackModules
  return modules.filter((module) => module.routePath)
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

function statusLabel(status: Project['status']) {
  if (status === 'draft') return '草稿'
  return status === 'active' ? '进行中' : '已归档'
}

function statusType(status: Project['status']) {
  if (status === 'active') return 'success'
  if (status === 'draft') return 'warning'
  return 'info'
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
        <ElButton type="primary" :icon="Plus" @click="openCreateDialog">新建项目</ElButton>
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
              <ElTag :type="statusType(row.status)">{{ statusLabel(row.status) }}</ElTag>
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
          <ElTableColumn label="操作" width="360" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <ElButton
                  v-for="module in projectActionModules(row)"
                  :key="module.id"
                  size="small"
                  @click="openRoute(module.routePath, row)"
                >
                  {{ module.name }}
                </ElButton>
              </div>
            </template>
          </ElTableColumn>
        </ElTable>
      </div>
    </section>

    <ElDialog v-model="createDialogVisible" title="新建项目草稿" width="520px" @closed="resetCreateForm">
      <ElForm label-position="top">
        <ElFormItem label="项目名称" required>
          <ElInput v-model="createForm.name" maxlength="40" show-word-limit placeholder="例如：线路巡检项目" />
        </ElFormItem>
        <ElFormItem label="项目说明">
          <ElInput
            v-model="createForm.description"
            type="textarea"
            :rows="3"
            maxlength="160"
            show-word-limit
            placeholder="说明这个项目的现场范围、交付目标或接入计划"
          />
        </ElFormItem>
        <ElFormItem label="启用模块" required>
          <ElCheckboxGroup v-model="createForm.moduleIds" class="module-checkboxes">
            <ElCheckbox v-for="module in moduleOptions" :key="module.id" :label="module.id">
              {{ module.name }}
            </ElCheckbox>
          </ElCheckboxGroup>
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="createDialogVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="creatingProject" @click="submitCreateProject">创建草稿</ElButton>
      </template>
    </ElDialog>
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

.module-checkboxes {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 12px;
}

:deep(.active-project-row td) {
  background: rgba(37, 99, 235, 0.06) !important;
}
</style>
