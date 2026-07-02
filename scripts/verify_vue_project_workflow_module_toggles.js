const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const editorPath = path.join(root, 'v2-web', 'src', 'components', 'project-workflow', 'WorkflowEditor.vue')
const source = fs.readFileSync(editorPath, 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

for (const token of [
  'workflowModuleRows',
  'toggleModule',
  'moduleNodeCount',
  'moduleEnabledNodeCount',
  'moduleRequiredNodeCount',
  'module-toggle-panel',
  '模块开关',
  '按项目启用需要的功能模块',
  '影响节点',
  '必备节点不可停用',
  '保存后同步项目模块',
]) {
  if (!source.includes(token)) {
    fail(`Workflow editor must expose module toggle token: ${token}`)
  }
}

for (const token of [
  'node.moduleId === moduleId',
  'node.enabled = enabled || node.required',
  ':disabled="!editable || row.requiredCount === row.totalCount"',
  '@change="toggleModule(row.id, Boolean($event))"',
]) {
  if (!source.includes(token)) {
    fail(`Workflow editor module toggle behavior must include: ${token}`)
  }
}

if (!source.includes('moduleRequiredNodeCount(row.id)')) {
  fail('Workflow editor must show required node count per module')
}

console.log('[OK] Vue workflow editor exposes module-level enable/disable controls.')
