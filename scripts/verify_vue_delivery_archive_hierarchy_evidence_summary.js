const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const boardSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ProjectBoardView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requiredTokens = [
  ['type ArchiveEvidenceHierarchySummaryCard', 'board must define archive evidence hierarchy summary card type'],
  ['const platformArchiveEvidenceHierarchySummary', 'board must compute archive evidence hierarchy summary'],
  ['function archiveEvidenceHierarchyIntentLabel', 'board must map archive evidence relation roles to hierarchy labels'],
  ['function archiveEvidenceHierarchyClassName', 'board must style archive evidence hierarchy groups'],
  ['class="platform-archive-evidence-summary"', 'board must render archive evidence summary'],
  ['交付证据覆盖摘要', 'board must label delivery evidence coverage summary'],
  ['主设备本体', 'delivery archive summary must include main-device evidence'],
  ['任务对象下的附属设备', 'delivery archive summary must include accessory evidence under task object'],
  ['附属设备确认', 'delivery archive summary must include accessory confirmation evidence'],
  ['换模块：任务对象下换附属设备', 'summary must explain module replacement as accessory replacement under task object'],
  ['换终端：主设备更换并确认附属设备', 'summary must explain terminal replacement as main-device replacement with accessory confirmation'],
  ['条件补采', 'delivery archive summary must include conditional follow-up evidence'],
  ['照片证据', 'delivery archive summary must include photo evidence'],
  ['KPI资料', 'delivery archive summary must include KPI evidence'],
  ["id: 'task-core', label: '任务核心'", 'delivery archive summary must keep task-core evidence visible'],
  ['deliveryArchiveManifest.value?.requiredEvidence.fields', 'summary must read field evidence'],
  ['deliveryArchiveManifest.value?.requiredEvidence.photos', 'summary must read photo evidence'],
  ['evidence.requiredWhen?.fieldKey', 'summary must treat required_when evidence as conditional follow-up'],
  ['uploaded_at', 'summary must keep upload time under KPI evidence'],
  ['platform-archive-evidence-summary-card', 'summary cards must have focused styling'],
]

for (const [token, message] of requiredTokens) {
  if (!boardSource.includes(token)) fail(message)
}

const kpiIndex = boardSource.indexOf("if (archiveEvidenceIsKpiKey(evidence.key)) return 'KPI资料'")
const relationIndex = boardSource.indexOf("if (evidence.relationRole === 'replacement_device') return '主设备本体'")
if (kpiIndex < 0 || relationIndex < 0 || kpiIndex > relationIndex) {
  fail('KPI evidence must be classified before general device relation roles')
}

console.log('[OK] Vue delivery archive hierarchy evidence summary is visible.')
