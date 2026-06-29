<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { useWorkspaceStore } from '@/stores/workspace'
import type {
  Project,
  ProjectCaptureMethod,
  ProjectFieldDataType,
  ProjectFieldDefinition,
  ProjectFieldSource,
  ProjectModule,
  ProjectWorkItemSchema,
} from '@/api/types'

type CreateFieldForm = {
  key: string
  label: string
  dataType: ProjectFieldDataType
  source: ProjectFieldSource
  captureMethod: ProjectCaptureMethod
  required: boolean
  parentKey: string
  kpiEnabled: boolean
}

type WorkItemSchemaForm = {
  primaryField: CreateFieldForm
  aggregateField: CreateFieldForm
  customFields: CreateFieldForm[]
}

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
const sourceOptions: Array<{ value: ProjectFieldSource; label: string }> = [
  { value: 'import', label: '初始导入' },
  { value: 'field_collection', label: '现场采集' },
  { value: 'review', label: '审阅补录' },
]
const captureMethodOptions: Array<{ value: ProjectCaptureMethod; label: string }> = [
  { value: 'manual', label: '录入' },
  { value: 'scan', label: '扫码' },
  { value: 'photo', label: '拍照' },
  { value: 'select', label: '选择' },
  { value: 'datetime', label: '时间' },
  { value: 'location', label: '定位' },
]
const dataTypeOptions: Array<{ value: ProjectFieldDataType; label: string }> = [
  { value: 'text', label: '文本' },
  { value: 'number', label: '数字' },
  { value: 'datetime', label: '时间' },
  { value: 'image', label: '图片' },
  { value: 'enum', label: '选项' },
  { value: 'duration', label: '时长' },
  { value: 'location', label: '位置' },
]
const platformRequiredFields = [
  '工单编号',
  '安装人员',
  '安装时间',
  '完成时间',
  '在线时间',
  '在线时长',
  '照片数量',
  '扫码次数',
  '异常状态',
  '审阅人员',
]
const createDialogVisible = ref(false)
const creatingProject = ref(false)
const schemaDialogVisible = ref(false)
const savingSchema = ref(false)
const schemaProject = ref<Project | null>(null)
const createForm = reactive({
  name: '',
  description: '',
  moduleIds: [...defaultModuleIds],
  primaryField: defaultPrimaryField(),
  aggregateField: defaultAggregateField(),
  customFields: [defaultCustomField('module_asset_no', '模块', 'scan'), defaultCustomField('collector_no', '采集器', 'scan')],
})
const schemaForm = reactive({
  primaryField: defaultPrimaryField(),
  aggregateField: defaultAggregateField(),
  customFields: [defaultCustomField('module_asset_no', '模块', 'scan')],
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

function defaultPrimaryField(): CreateFieldForm {
  return {
    key: 'meter_no',
    label: '电能表',
    dataType: 'text',
    source: 'import',
    captureMethod: 'manual',
    required: true,
    parentKey: '',
    kpiEnabled: false,
  }
}

function defaultAggregateField(): CreateFieldForm {
  return {
    key: 'area_no',
    label: '台区',
    dataType: 'text',
    source: 'import',
    captureMethod: 'manual',
    required: true,
    parentKey: '',
    kpiEnabled: false,
  }
}

function defaultCustomField(
  key = '',
  label = '',
  captureMethod: ProjectCaptureMethod = 'manual',
): CreateFieldForm {
  return {
    key,
    label,
    dataType: captureMethod === 'photo' ? 'image' : 'text',
    source: 'field_collection',
    captureMethod,
    required: false,
    parentKey: 'meter_no',
    kpiEnabled: false,
  }
}

function resetCreateForm() {
  createForm.name = ''
  createForm.description = ''
  createForm.moduleIds = [...defaultModuleIds]
  createForm.primaryField = defaultPrimaryField()
  createForm.aggregateField = defaultAggregateField()
  createForm.customFields = [
    defaultCustomField('module_asset_no', '模块', 'scan'),
    defaultCustomField('collector_no', '采集器', 'scan'),
  ]
}

function fieldDefinitionToForm(field: ProjectFieldDefinition | undefined, fallback: CreateFieldForm): CreateFieldForm {
  return {
    key: field?.key || fallback.key,
    label: field?.label || fallback.label,
    dataType: field?.dataType || fallback.dataType,
    source: field?.source || fallback.source,
    captureMethod: field?.captureMethod || fallback.captureMethod,
    required: field?.required ?? fallback.required,
    parentKey: field?.parentKey || fallback.parentKey,
    kpiEnabled: field?.kpiEnabled ?? fallback.kpiEnabled,
  }
}

function resetSchemaForm(project: Project | null) {
  const schema = project?.workItemSchema
  schemaForm.primaryField = fieldDefinitionToForm(schema?.primaryField, defaultPrimaryField())
  schemaForm.aggregateField = fieldDefinitionToForm(schema?.aggregateField, defaultAggregateField())
  schemaForm.customFields = schema?.customFields.length
    ? schema.customFields.map((field) => fieldDefinitionToForm(field, defaultCustomField()))
    : [defaultCustomField('module_asset_no', '模块', 'scan')]
}

function fieldParentOptions() {
  return [
    { value: createForm.primaryField.key || 'primary', label: createForm.primaryField.label || '主字段' },
    { value: createForm.aggregateField.key || 'aggregate', label: createForm.aggregateField.label || '聚合字段' },
  ]
}

function schemaFieldParentOptions() {
  return [
    { value: schemaForm.primaryField.key || 'primary', label: schemaForm.primaryField.label || '主字段' },
    { value: schemaForm.aggregateField.key || 'aggregate', label: schemaForm.aggregateField.label || '聚合字段' },
  ]
}

function addCustomField() {
  createForm.customFields.push(defaultCustomField())
}

function removeCustomField(index: number) {
  createForm.customFields.splice(index, 1)
}

function addSchemaCustomField() {
  schemaForm.customFields.push(defaultCustomField())
}

function removeSchemaCustomField(index: number) {
  schemaForm.customFields.splice(index, 1)
}

function toFieldDefinition(field: CreateFieldForm, fallbackKey: string): ProjectFieldDefinition {
  return {
    key: field.key.trim() || fallbackKey,
    label: field.label.trim(),
    dataType: field.dataType,
    source: field.source,
    captureMethod: field.captureMethod,
    required: field.required,
    parentKey: field.parentKey || undefined,
    kpiEnabled: field.kpiEnabled,
    options: [],
  }
}

function buildWorkItemSchemaPayload(form: WorkItemSchemaForm = createForm): ProjectWorkItemSchema {
  return {
    primaryField: toFieldDefinition(form.primaryField, 'primary_object'),
    aggregateField: toFieldDefinition(form.aggregateField, 'aggregate_object'),
    platformRequiredFields: [],
    customFields: form.customFields
      .filter((field) => field.label.trim())
      .map((field, index) => toFieldDefinition(field, `custom_field_${index + 1}`)),
  }
}

function validateFieldForm(form: WorkItemSchemaForm) {
  if (!form.primaryField.label.trim() || !form.aggregateField.label.trim()) {
    ElMessage.warning('请填写主字段和聚合字段')
    return false
  }
  if (form.customFields.some((field) => !field.label.trim())) {
    ElMessage.warning('请补全子字段名称，或删除空字段')
    return false
  }
  return true
}

function openSchemaDialog(project: Project) {
  schemaProject.value = project
  resetSchemaForm(project)
  schemaDialogVisible.value = true
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
  if (!validateFieldForm(createForm)) return
  creatingProject.value = true
  try {
    const project = await workspace.createProjectDraft({
      name,
      description: createForm.description.trim(),
      moduleIds: createForm.moduleIds,
      workItemSchema: buildWorkItemSchemaPayload(),
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

async function submitSchemaUpdate() {
  const project = schemaProject.value
  if (!project) return
  if (project.status !== 'draft') {
    ElMessage.info('正式项目字段配置需要走变更评审，当前仅开放查看')
    return
  }
  if (!validateFieldForm(schemaForm)) return
  savingSchema.value = true
  try {
    await workspace.updateProjectWorkItemSchema(project.id, buildWorkItemSchemaPayload(schemaForm))
    schemaDialogVisible.value = false
    ElMessage.success('字段配置已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '字段配置保存失败')
  } finally {
    savingSchema.value = false
  }
}

function openRoute(path: string, project: Project) {
  if (project.status === 'draft') {
    ElMessage.info('草稿项目模块待接入，先保留在项目列表中管理')
    return
  }
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
                <ElButton size="small" type="primary" plain @click="openSchemaDialog(row)">
                  字段配置
                </ElButton>
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

    <ElDialog v-model="createDialogVisible" title="新建项目草稿" width="860px" @closed="resetCreateForm">
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

        <div class="schema-section">
          <div class="schema-heading">
            <strong>工单关键字段</strong>
            <span>定义每个工单围绕什么对象管理，以及如何按现场维度汇总。</span>
          </div>
          <div class="field-grid two-columns">
            <div class="field-block">
              <span class="field-block-title">主字段</span>
              <ElInput v-model="createForm.primaryField.label" placeholder="电能表 / 终端 / 台区" />
              <ElInput v-model="createForm.primaryField.key" placeholder="字段编码，例如 meter_no" />
            </div>
            <div class="field-block">
              <span class="field-block-title">聚合字段</span>
              <ElInput v-model="createForm.aggregateField.label" placeholder="台区 / 供电所 / 线路" />
              <ElInput v-model="createForm.aggregateField.key" placeholder="字段编码，例如 area_no" />
            </div>
          </div>
        </div>

        <div class="schema-section">
          <div class="schema-heading">
            <strong>业务子字段</strong>
            <ElButton size="small" :icon="Plus" @click="addCustomField">添加字段</ElButton>
          </div>
          <div class="custom-field-list">
            <div v-for="(field, index) in createForm.customFields" :key="index" class="custom-field-row">
              <ElInput v-model="field.label" placeholder="字段名称，例如 模块 / 通讯模块 / 总表" />
              <ElInput v-model="field.key" placeholder="字段编码" />
              <ElSelect v-model="field.source" placeholder="来源">
                <ElOption
                  v-for="option in sourceOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </ElSelect>
              <ElSelect v-model="field.captureMethod" placeholder="采集方式">
                <ElOption
                  v-for="option in captureMethodOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </ElSelect>
              <ElSelect v-model="field.dataType" placeholder="格式">
                <ElOption
                  v-for="option in dataTypeOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </ElSelect>
              <ElSelect v-model="field.parentKey" placeholder="归属">
                <ElOption
                  v-for="option in fieldParentOptions()"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </ElSelect>
              <ElSwitch v-model="field.required" active-text="必填" inactive-text="可选" />
              <ElButton size="small" :disabled="createForm.customFields.length <= 1" @click="removeCustomField(index)">
                删除
              </ElButton>
            </div>
          </div>
        </div>

        <div class="schema-section">
          <div class="schema-heading">
            <strong>平台必备字段</strong>
            <span>用于 KPI、效率、审阅和追溯，创建后由系统保留。</span>
          </div>
          <div class="required-field-tags">
            <ElTag v-for="field in platformRequiredFields" :key="field" type="info">
              {{ field }}
            </ElTag>
          </div>
        </div>
      </ElForm>
      <template #footer>
        <ElButton @click="createDialogVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="creatingProject" @click="submitCreateProject">创建草稿</ElButton>
      </template>
    </ElDialog>

    <ElDialog
      v-model="schemaDialogVisible"
      :title="schemaProject ? `字段配置：${schemaProject.name}` : '字段配置'"
      width="860px"
    >
      <ElForm label-position="top">
        <div class="schema-section first-section">
          <div class="schema-heading">
            <strong>工单关键字段</strong>
            <span>草稿项目可调整，正式项目需走变更评审。</span>
          </div>
          <div class="field-grid two-columns">
            <div class="field-block">
              <span class="field-block-title">主字段</span>
              <ElInput v-model="schemaForm.primaryField.label" :disabled="schemaProject?.status !== 'draft'" />
              <ElInput v-model="schemaForm.primaryField.key" :disabled="schemaProject?.status !== 'draft'" />
            </div>
            <div class="field-block">
              <span class="field-block-title">聚合字段</span>
              <ElInput v-model="schemaForm.aggregateField.label" :disabled="schemaProject?.status !== 'draft'" />
              <ElInput v-model="schemaForm.aggregateField.key" :disabled="schemaProject?.status !== 'draft'" />
            </div>
          </div>
        </div>

        <div class="schema-section">
          <div class="schema-heading">
            <strong>业务子字段</strong>
            <ElButton
              size="small"
              :icon="Plus"
              :disabled="schemaProject?.status !== 'draft'"
              @click="addSchemaCustomField"
            >
              添加字段
            </ElButton>
          </div>
          <div class="custom-field-list">
            <div v-for="(field, index) in schemaForm.customFields" :key="index" class="custom-field-row">
              <ElInput v-model="field.label" placeholder="字段名称" :disabled="schemaProject?.status !== 'draft'" />
              <ElInput v-model="field.key" placeholder="字段编码" :disabled="schemaProject?.status !== 'draft'" />
              <ElSelect v-model="field.source" placeholder="来源" :disabled="schemaProject?.status !== 'draft'">
                <ElOption
                  v-for="option in sourceOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </ElSelect>
              <ElSelect
                v-model="field.captureMethod"
                placeholder="采集方式"
                :disabled="schemaProject?.status !== 'draft'"
              >
                <ElOption
                  v-for="option in captureMethodOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </ElSelect>
              <ElSelect v-model="field.dataType" placeholder="格式" :disabled="schemaProject?.status !== 'draft'">
                <ElOption
                  v-for="option in dataTypeOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </ElSelect>
              <ElSelect v-model="field.parentKey" placeholder="归属" :disabled="schemaProject?.status !== 'draft'">
                <ElOption
                  v-for="option in schemaFieldParentOptions()"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </ElSelect>
              <ElSwitch
                v-model="field.required"
                active-text="必填"
                inactive-text="可选"
                :disabled="schemaProject?.status !== 'draft'"
              />
              <ElButton
                size="small"
                :disabled="schemaProject?.status !== 'draft' || schemaForm.customFields.length <= 1"
                @click="removeSchemaCustomField(index)"
              >
                删除
              </ElButton>
            </div>
          </div>
        </div>

        <div class="schema-section">
          <div class="schema-heading">
            <strong>平台必备字段</strong>
            <span>用于 KPI、效率、审阅和追溯，系统保留。</span>
          </div>
          <div class="required-field-tags">
            <ElTag
              v-for="field in schemaProject?.workItemSchema?.platformRequiredFields || []"
              :key="field.key"
              type="info"
            >
              {{ field.label }}
            </ElTag>
          </div>
        </div>
      </ElForm>
      <template #footer>
        <ElButton @click="schemaDialogVisible = false">关闭</ElButton>
        <ElButton
          type="primary"
          :loading="savingSchema"
          :disabled="schemaProject?.status !== 'draft'"
          @click="submitSchemaUpdate"
        >
          保存配置
        </ElButton>
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

.schema-section {
  display: grid;
  gap: 12px;
  padding: 14px 0;
  border-top: 1px solid var(--el-border-color-lighter);
}

.first-section {
  padding-top: 0;
  border-top: 0;
}

.schema-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.schema-heading strong,
.field-block-title {
  color: var(--el-text-color-primary);
  font-size: 14px;
}

.schema-heading span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.field-grid {
  display: grid;
  gap: 12px;
}

.two-columns {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.field-block {
  display: grid;
  gap: 8px;
}

.custom-field-list {
  display: grid;
  gap: 10px;
}

.custom-field-row {
  display: grid;
  grid-template-columns: minmax(112px, 1.2fr) minmax(110px, 1fr) repeat(4, minmax(96px, 0.9fr)) minmax(88px, auto) auto;
  gap: 8px;
  align-items: center;
}

.required-field-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

@media (max-width: 860px) {
  .two-columns,
  .custom-field-row {
    grid-template-columns: 1fr;
  }
}

:deep(.active-project-row td) {
  background: rgba(37, 99, 235, 0.06) !important;
}
</style>
