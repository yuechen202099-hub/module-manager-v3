<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, CircleCheck, Rank, Refresh } from '@element-plus/icons-vue'

import type { Project, ProjectWorkflow, ProjectWorkflowNode } from '@/api/types'

const props = defineProps<{
  project: Project | null
  workflow: ProjectWorkflow | null
  loading?: boolean
  saving?: boolean
  resetting?: boolean
}>()

const emit = defineEmits<{
  save: [workflow: ProjectWorkflow]
  reset: []
  close: []
}>()

const fallbackNodeLabels: Record<string, string> = {
  project_setup: '项目建立',
  field_schema: '字段配置',
  template_import: '模板导入',
  work_order_plan: '工单计划',
  construction_collection: '现场施工采集',
  review: '审阅',
  rework: '返工',
  exception: '异常处理',
  delivery_archive: '交付归档',
  delivery_export: '交付导出',
}

const draft = ref<ProjectWorkflow>(emptyWorkflow())
const selectedNodeId = ref('')
const draggingNodeId = ref('')

const enabledNodes = computed(() => draft.value.nodes.filter((node) => node.enabled).sort(compareNodes))
const disabledNodes = computed(() => draft.value.nodes.filter((node) => !node.enabled).sort(compareNodes))
const selectedNode = computed(() => draft.value.nodes.find((node) => node.id === selectedNodeId.value) || enabledNodes.value[0] || disabledNodes.value[0])
const editable = computed(() => props.project?.status === 'draft')
const enabledNodeIds = computed(() => new Set(enabledNodes.value.map((node) => node.id)))
const enabledModuleIds = computed(() => Array.from(new Set(enabledNodes.value.map((node) => node.moduleId).filter(Boolean))))
const workflowModuleRows = computed(() => {
  const moduleNameById = new Map((props.project?.modules || []).map((module) => [module.id, module.name]))
  const moduleIds = new Set<string>()
  draft.value.nodes.forEach((node) => {
    if (node.moduleId) moduleIds.add(node.moduleId)
  })
  return Array.from(moduleIds).map((moduleId) => {
    const totalCount = moduleNodeCount(moduleId)
    const enabledCount = moduleEnabledNodeCount(moduleId)
    const requiredCount = moduleRequiredNodeCount(moduleId)
    return {
      id: moduleId,
      name: moduleNameById.get(moduleId) || fallbackModuleName(moduleId),
      totalCount,
      enabledCount,
      requiredCount,
      enabled: enabledCount > 0,
    }
  })
})
const moduleImpactLabels = computed(() => {
  const moduleNameById = new Map((props.project?.modules || []).map((module) => [module.id, module.name]))
  return enabledModuleIds.value.map((moduleId) => moduleNameById.get(moduleId) || fallbackModuleName(moduleId))
})
const previewEdges = computed(() => {
  const existingEdges = draft.value.edges.filter((edge) => enabledNodeIds.value.has(edge.source) && enabledNodeIds.value.has(edge.target))
  if (existingEdges.length) return existingEdges
  return enabledNodes.value.slice(1).map((node, index) => ({
    id: `${enabledNodes.value[index].id}__${node.id}`,
    source: enabledNodes.value[index].id,
    target: node.id,
    label: '下一步',
  }))
})

watch(
  () => props.workflow,
  (workflow) => {
    draft.value = cloneWorkflow(workflow)
    selectedNodeId.value = enabledNodes.value[0]?.id || disabledNodes.value[0]?.id || ''
  },
  { immediate: true },
)

function emptyWorkflow(): ProjectWorkflow {
  return {
    version: 1,
    nodes: [],
    edges: [],
    updatedAt: '',
    updatedBy: '',
  }
}

function cloneWorkflow(workflow: ProjectWorkflow | null): ProjectWorkflow {
  if (!workflow) return emptyWorkflow()
  return {
    version: workflow.version || 1,
    nodes: workflow.nodes.map((node) => ({
      ...node,
      label: node.label || fallbackNodeLabels[node.id] || node.id,
      config: { ...(node.config || {}) },
    })),
    edges: workflow.edges.map((edge) => ({ ...edge })),
    updatedAt: workflow.updatedAt || '',
    updatedBy: workflow.updatedBy || '',
  }
}

function compareNodes(left: ProjectWorkflowNode, right: ProjectWorkflowNode) {
  return left.order - right.order || left.id.localeCompare(right.id)
}

function fallbackModuleName(moduleId: string) {
  const fallbackNames: Record<string, string> = {
    progress: '项目进度',
    delivery: '项目交付能力',
    field: '现场施工数据采集',
    review: '审阅功能',
    risks: '风险预警',
    tasks: '任务执行',
  }
  return fallbackNames[moduleId] || moduleId
}

function moduleNodeCount(moduleId: string) {
  return draft.value.nodes.filter((node) => node.moduleId === moduleId).length
}

function moduleEnabledNodeCount(moduleId: string) {
  return draft.value.nodes.filter((node) => node.moduleId === moduleId && node.enabled).length
}

function moduleRequiredNodeCount(moduleId: string) {
  return draft.value.nodes.filter((node) => node.moduleId === moduleId && node.required).length
}

function normalizeOrders(nodes: ProjectWorkflowNode[]) {
  nodes.forEach((node, index) => {
    node.order = (index + 1) * 10
  })
}

function rebuildEdges(nodes = enabledNodes.value) {
  draft.value.edges = nodes.slice(1).map((node, index) => ({
    id: `${nodes[index].id}__${node.id}`,
    source: nodes[index].id,
    target: node.id,
    label: '下一步',
  }))
}

function selectNode(nodeId: string) {
  selectedNodeId.value = nodeId
}

function moveNode(nodeId: string, direction: -1 | 1) {
  if (!editable.value) return
  const nodes = [...enabledNodes.value]
  const index = nodes.findIndex((node) => node.id === nodeId)
  const targetIndex = index + direction
  if (index < 0 || targetIndex < 0 || targetIndex >= nodes.length) return
  const [node] = nodes.splice(index, 1)
  nodes.splice(targetIndex, 0, node)
  normalizeOrders(nodes)
  rebuildEdges(nodes)
}

function toggleNode(node: ProjectWorkflowNode, enabled: boolean) {
  if (!editable.value || node.required) return
  node.enabled = enabled
  const nodes = enabledNodes.value
  normalizeOrders(nodes)
  rebuildEdges(nodes)
  selectedNodeId.value = node.id
}

function toggleModule(moduleId: string, enabled: boolean) {
  if (!editable.value) return
  draft.value.nodes.forEach((node) => {
    if (node.moduleId === moduleId) {
      node.enabled = enabled || node.required
    }
  })
  const nodes = enabledNodes.value
  normalizeOrders(nodes)
  rebuildEdges(nodes)
  const firstModuleNode = nodes.find((node) => node.moduleId === moduleId)
  if (firstModuleNode) selectedNodeId.value = firstModuleNode.id
}

function onDragStart(nodeId: string) {
  draggingNodeId.value = nodeId
}

function onDrop(targetNodeId: string) {
  if (!editable.value || !draggingNodeId.value || draggingNodeId.value === targetNodeId) {
    draggingNodeId.value = ''
    return
  }
  const nodes = [...enabledNodes.value]
  const sourceIndex = nodes.findIndex((node) => node.id === draggingNodeId.value)
  const targetIndex = nodes.findIndex((node) => node.id === targetNodeId)
  if (sourceIndex >= 0 && targetIndex >= 0) {
    const [node] = nodes.splice(sourceIndex, 1)
    nodes.splice(targetIndex, 0, node)
    normalizeOrders(nodes)
    rebuildEdges(nodes)
  }
  draggingNodeId.value = ''
}

function saveWorkflow() {
  const nodes = enabledNodes.value
  normalizeOrders(nodes)
  rebuildEdges(nodes)
  emit('save', cloneWorkflow(draft.value))
}
</script>

<template>
  <div class="workflow-editor" v-loading="loading">
    <div class="workflow-toolbar">
      <div>
        <strong>{{ project?.name || '项目流程' }}</strong>
        <span>{{ editable ? '草稿流程可调整' : '正式项目仅查看流程' }}</span>
      </div>
      <div class="workflow-actions">
        <ElButton :icon="Refresh" :loading="resetting" :disabled="!editable" @click="emit('reset')">
          恢复默认
        </ElButton>
        <ElButton type="primary" :loading="saving" :disabled="!editable" @click="saveWorkflow">
          保存流程
        </ElButton>
      </div>
    </div>

    <div class="workflow-layout">
      <section class="workflow-canvas">
        <div class="workflow-lane">
          <div
            v-for="(node, index) in enabledNodes"
            :key="node.id"
            class="workflow-node"
            :class="{ selected: selectedNode?.id === node.id }"
            draggable="true"
            @dragstart="onDragStart(node.id)"
            @dragover.prevent
            @drop="onDrop(node.id)"
            @click="selectNode(node.id)"
          >
            <div class="node-grip">
              <ElIcon><Rank /></ElIcon>
            </div>
            <div class="node-body">
              <span>{{ index + 1 }}</span>
              <strong>{{ node.label || fallbackNodeLabels[node.id] || node.id }}</strong>
              <small>{{ node.type }}</small>
            </div>
            <ElTag v-if="node.required" size="small" type="success" effect="plain">必备</ElTag>
            <div class="node-move">
              <ElButton :icon="ArrowUp" circle size="small" :disabled="!editable || index === 0" @click.stop="moveNode(node.id, -1)" />
              <ElButton :icon="ArrowDown" circle size="small" :disabled="!editable || index === enabledNodes.length - 1" @click.stop="moveNode(node.id, 1)" />
            </div>
          </div>
        </div>

        <div class="workflow-edge-preview">
          <span v-for="edge in previewEdges" :key="edge.id">
            {{ fallbackNodeLabels[edge.source] || edge.source }} -> {{ fallbackNodeLabels[edge.target] || edge.target }}
          </span>
        </div>
      </section>

      <aside class="workflow-side-panel">
        <section class="module-toggle-panel">
          <div class="panel-heading">
            <strong>模块开关</strong>
            <span>按项目启用需要的功能模块</span>
          </div>
          <div class="module-toggle-list">
            <article v-for="row in workflowModuleRows" :key="row.id" class="module-toggle-row">
              <div>
                <strong>{{ row.name }}</strong>
                <span>
                  影响节点 {{ moduleEnabledNodeCount(row.id) }} / {{ moduleNodeCount(row.id) }}，
                  必备 {{ moduleRequiredNodeCount(row.id) }}
                </span>
              </div>
              <ElSwitch
                :model-value="row.enabled"
                :disabled="!editable || row.requiredCount === row.totalCount"
                active-text="启用"
                inactive-text="停用"
                @change="toggleModule(row.id, Boolean($event))"
              />
            </article>
          </div>
          <p class="module-toggle-note">必备节点不可停用；保存后同步项目模块。</p>
        </section>

        <section class="node-config-panel">
          <div class="panel-heading">
            <strong>{{ selectedNode?.label || '流程节点' }}</strong>
            <ElTag v-if="selectedNode?.enabled" type="success" effect="light">已启用</ElTag>
            <ElTag v-else type="info" effect="light">未启用</ElTag>
          </div>
          <div v-if="selectedNode" class="node-fields">
            <label>
              <span>节点名称</span>
              <ElInput v-model="selectedNode.label" :disabled="!editable || selectedNode.required" />
            </label>
            <label>
              <span>节点类型</span>
              <ElInput v-model="selectedNode.type" disabled />
            </label>
            <label>
              <span>关联模块</span>
              <ElInput v-model="selectedNode.moduleId" disabled />
            </label>
            <ElSwitch
              :model-value="selectedNode.enabled"
              :disabled="!editable || selectedNode.required"
              active-text="启用"
              inactive-text="停用"
              @change="toggleNode(selectedNode, Boolean($event))"
            />
          </div>
        </section>

        <section class="disabled-node-list">
          <div class="panel-heading">
            <strong>可选节点</strong>
            <span>{{ disabledNodes.length }} 个未启用</span>
          </div>
          <button
            v-for="node in disabledNodes"
            :key="node.id"
            type="button"
            class="disabled-node"
            :disabled="!editable"
            @click="toggleNode(node, true)"
          >
            <ElIcon><CircleCheck /></ElIcon>
            <span>{{ node.label || fallbackNodeLabels[node.id] || node.id }}</span>
          </button>
        </section>

        <section class="module-impact-panel">
          <div class="panel-heading">
            <strong>模块入口</strong>
            <span>保存后同步项目模块</span>
          </div>
          <div class="module-impact-tags">
            <ElTag v-for="moduleName in moduleImpactLabels" :key="moduleName" effect="plain">
              {{ moduleName }}
            </ElTag>
          </div>
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.workflow-editor {
  display: grid;
  gap: 14px;
}

.workflow-toolbar,
.workflow-actions,
.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.workflow-toolbar > div:first-child,
.panel-heading {
  min-width: 0;
}

.workflow-actions {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.workflow-toolbar strong,
.panel-heading strong {
  color: var(--el-text-color-primary);
  font-size: 15px;
}

.workflow-toolbar span,
.panel-heading span,
.node-body small,
.node-fields span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.workflow-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 14px;
}

.workflow-canvas,
.workflow-side-panel {
  min-width: 0;
}

.workflow-lane {
  display: grid;
  gap: 10px;
}

.workflow-node {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 10px;
  min-height: 66px;
  padding: 10px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
}

.workflow-node.selected {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 2px var(--el-color-primary-light-8);
}

.node-grip {
  display: grid;
  place-items: center;
  color: var(--el-text-color-secondary);
}

.node-body {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.node-body span {
  color: var(--el-color-primary);
  font-size: 12px;
  font-weight: 700;
}

.node-body strong {
  overflow-wrap: anywhere;
  color: var(--el-text-color-primary);
  font-size: 14px;
}

.node-move {
  display: flex;
  gap: 4px;
}

.workflow-edge-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
}

.workflow-edge-preview span {
  padding: 4px 8px;
  border-radius: 999px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.workflow-side-panel {
  display: grid;
  align-content: start;
  gap: 12px;
}

.module-toggle-panel,
.node-config-panel,
.disabled-node-list,
.module-impact-panel {
  display: grid;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.module-toggle-list {
  display: grid;
  gap: 8px;
}

.module-toggle-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.module-toggle-row > div {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.module-toggle-row strong {
  overflow-wrap: anywhere;
  color: var(--el-text-color-primary);
  font-size: 13px;
}

.module-toggle-row span,
.module-toggle-note {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.module-toggle-note {
  margin: 0;
}

.node-fields {
  display: grid;
  gap: 10px;
}

.node-fields label {
  display: grid;
  gap: 6px;
}

.disabled-node {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: #fff;
  color: var(--el-text-color-primary);
  cursor: pointer;
  text-align: left;
}

.disabled-node:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.module-impact-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

@media (max-width: 900px) {
  .workflow-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .workflow-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .workflow-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .workflow-node {
    grid-template-columns: 24px minmax(0, 1fr);
  }

  .workflow-node > .el-tag,
  .node-move {
    grid-column: 2;
  }
}
</style>
