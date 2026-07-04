const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const projectsViewPath = path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue')
const editorPath = path.join(root, 'v2-web', 'src', 'components', 'project-workflow', 'WorkflowEditor.vue')
const projectsSource = fs.readFileSync(projectsViewPath, 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

if (!fs.existsSync(editorPath)) {
  fail('WorkflowEditor.vue must exist under project-workflow components')
}

const editorSource = fs.readFileSync(editorPath, 'utf8')

const requiredProjectTokens = [
  'WorkflowEditor',
  '流程配置',
  'workflowDialogVisible',
  'openWorkflowDialog',
  'fetchProjectWorkflow',
  'saveProjectWorkflow',
  'resetProjectWorkflow',
]

for (const token of requiredProjectTokens) {
  if (!projectsSource.includes(token)) fail(`ProjectsView.vue missing workflow token: ${token}`)
}

const requiredEditorTokens = [
  'defineProps',
  'defineEmits',
  'ProjectWorkflow',
  'workflow-visual-map',
  'workflow-connector-layer',
  'workflow-map-node',
  'workflowNodePositions',
  'workflowConnectors',
  'workflowNodeStyle',
  'selectedNodeOrderIndex',
  'selectedNodeOrderLabel',
  'selectedNodeNeighborSummary',
  'canMoveSelectedNodeUp',
  'canMoveSelectedNodeDown',
  'moveSelectedNode',
  'viewBox="0 0 1000 360"',
  ':d="connector.d"',
  ':style="workflowNodeStyle(node, index)"',
  'enabledNodes',
  'disabledNodes',
  'enabledModuleIds',
  'moduleImpactLabels',
  'moveNode',
  'toggleNode',
  'node-order-control-panel',
  'node-order-buttons',
  '顺序调整',
  '当前位置',
  '上一步',
  '下一步',
  '@click="moveSelectedNode(-1)"',
  '@click="moveSelectedNode(1)"',
  'dragstart',
  'drop',
  '保存流程',
  '恢复默认',
  '模块入口',
  '保存后同步项目模块',
  '项目建立',
  '字段配置',
  '模板导入',
  '现场施工采集',
  '审阅',
  '交付归档',
]

for (const token of requiredEditorTokens) {
  if (!editorSource.includes(token)) fail(`WorkflowEditor.vue missing workflow token: ${token}`)
}

console.log('[OK] Vue project workflow editor entry and component are wired.')
