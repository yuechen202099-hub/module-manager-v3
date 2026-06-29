const fs = require('fs')

function read(path) {
  return fs.readFileSync(path, 'utf8')
}

function assertContains(source, pattern, message) {
  if (!source.includes(pattern)) {
    throw new Error(message)
  }
}

function assertNotContains(source, pattern, message) {
  if (source.includes(pattern)) {
    throw new Error(message)
  }
}

const board = read('v2-web/src/views/ProjectBoardView.vue')
const claimTasks = read('v2-web/src/views/ClaimTasksView.vue')
const accountManagement = read('v2-web/src/views/AccountManagementView.vue')
const syncConfig = read('v2-web/src/views/SyncConfigView.vue')
const globalSearch = read('v2-web/src/views/GlobalSearchView.vue')
const construction = read('v2-web/src/views/ConstructionView.vue')
const releaseNotes = read('v2-web/src/constants/releaseNotes.ts')
const types = read('v2-web/src/api/types.ts')
const services = read('v2-web/src/api/services.ts')
const stateRepository = read('v2-api/app/services/state_repository.py')
const localSimulation = read('v2-api/app/services/local_simulation.py')
const apiMain = read('v2-api/app/main.py')
const opsStatus = read('v2-api/app/services/ops_status.py')
const packageJson = read('v2-web/package.json')
const expectedVersion = '3.0.68'

for (const label of ['终端总数', '已完成施工', '未完成施工', '待归档', '已归档']) {
  assertContains(board, label, `ProjectBoardView must expose the ${label} terminal card`)
}

for (const removed of [
  '有上传',
  '待审阅',
  '已闭环',
  '仅展示聚合态势',
  '保留项目级导入',
  '进度、风险、采集与审阅态势',
  '导入形成的终端范围',
  '已有现场照片回流',
  '仍有未审照片',
  '终端审阅完成',
]) {
  assertNotContains(board, removed, `ProjectBoardView must remove explanatory or obsolete copy: ${removed}`)
}

assertContains(board, 'fetchTasks', 'ProjectBoardView must load terminal detail rows from the task API')
assertContains(board, 'terminalStatusDialogVisible', 'ProjectBoardView must have a terminal detail dialog')
assertContains(board, 'terminalStatusPageSize = ref(20)', 'terminal detail dialog must default to 20 rows per page')
assertContains(board, 'openTerminalStatusDialog', 'terminal cards must open a detail dialog')
assertContains(board, '<el-pagination', 'terminal detail dialog must be paginated')
assertContains(board, ':page-size="terminalStatusPageSize"', 'terminal detail dialog pagination must use the 20-row page-size state')
assertNotContains(board, 'terminalArchivedCount.value || taskStatus.value.archived', 'archived card and dialog must use the same task-row source')
assertContains(types, 'installerDistribution', 'ReviewTask must expose installerDistribution')
assertContains(services, 'installer_distribution', 'BackendTask must map installer_distribution')
assertContains(board, 'task.installerDistribution', 'terminal installer display must use grouped material-group installer distribution')
assertContains(board, 'formatInstallerShare', 'terminal installer display must show completion share percent')
assertContains(stateRepository, 'installer_distribution', 'task payload must include backend installer_distribution')
assertContains(localSimulation, 'installer_distribution', 'JSON task payload must include installer_distribution')
for (const column of ['终端号', '已施工数量', '安装人员', '总资料组', '未施工数量', '待归档数量']) {
  assertContains(board, column, `terminal detail dialog must include ${column}`)
}

for (const [source, text] of [
  [board, '异常与缺照记录可直接派发给施工员'],
  [board, '效率权重：同楼/同区集中地址降低权重'],
  [board, '点击日期异常数后展示该安装人员当天产生的异常资料组'],
  [claimTasks, '审阅员只看到仍有未审阅照片的终端'],
  [claimTasks, '按终端领取审阅任务'],
  [accountManagement, '统一维护账号入口'],
  [accountManagement, '姓名作为安装人员、施工统计与 KPI 的统一人员口径'],
  [syncConfig, '该页面只保留历史说明'],
  [syncConfig, '供应商后台不提供稳定 API'],
  [globalSearch, '所有保存和回退操作都会写入审计记录'],
  [construction, '未施工也会显示，便于现场逐户核对'],
]) {
  assertNotContains(source, text, `production UI must remove explanatory copy: ${text}`)
}

assertContains(releaseNotes, `APP_VERSION = '${expectedVersion}'`, `APP_VERSION must be ${expectedVersion}`)
assertContains(releaseNotes, '驾驶舱终端卡片', 'release notes must describe the dashboard terminal card change in Chinese')
assertContains(releaseNotes, '安装人员完成占比', 'release notes must describe terminal installer completion share in Chinese')
assertContains(apiMain, `version="${expectedVersion}"`, `FastAPI app version must be ${expectedVersion}`)
assertContains(opsStatus, `return "${expectedVersion}"`, `system status version must be ${expectedVersion}`)
assertContains(packageJson, `"version": "${expectedVersion}"`, `web package version must be ${expectedVersion}`)

console.log('project board terminal card checks passed')
