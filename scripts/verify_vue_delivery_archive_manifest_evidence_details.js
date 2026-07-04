const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const boardSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ProjectBoardView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requiredTokens = [
  ['platformArchiveManifestEvidenceGroups', 'board must group manifest evidence details'],
  ['archiveEvidenceConditionLabel', 'board must explain conditional required evidence'],
  ['deliveryArchiveManifest.value?.requiredEvidence.fields', 'board must read required field evidence'],
  ['deliveryArchiveManifest.value?.requiredEvidence.photos', 'board must read required photo evidence'],
  ['必备字段', 'board must label required field evidence'],
  ['必备照片', 'board must label required photo evidence'],
  ['条件触发', 'board must show conditional trigger wording'],
  ['evidence.requiredWhen?.fieldKey', 'board must inspect requiredWhen field key'],
  ['platform-archive-evidence-groups', 'board must style evidence detail groups'],
]

for (const [token, message] of requiredTokens) {
  if (!boardSource.includes(token)) fail(message)
}

console.log('[OK] Vue delivery archive manifest evidence details are visible.')
