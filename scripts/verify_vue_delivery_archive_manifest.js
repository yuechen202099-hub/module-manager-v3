const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const typesSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'api', 'types.ts'), 'utf8')
const servicesSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'api', 'services.ts'), 'utf8')
const boardSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ProjectBoardView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requiredTokens = [
  [typesSource, 'export type PlatformDeliveryArchiveManifest', 'types must expose delivery archive manifest'],
  [typesSource, 'requiredEvidence', 'manifest type must expose required evidence'],
  [typesSource, 'sections: PlatformDeliveryArchiveManifestSection[]', 'manifest type must expose sections'],
  [servicesSource, 'type BackendPlatformDeliveryArchiveManifest', 'services must define backend manifest contract'],
  [servicesSource, 'function mapPlatformDeliveryArchiveManifest', 'services must map archive manifest'],
  [servicesSource, 'export async function fetchProjectDeliveryArchiveManifest', 'services must fetch archive manifest'],
  [servicesSource, '/delivery/archive-manifest', 'services must call archive manifest route'],
  [boardSource, 'deliveryArchiveManifest', 'board must store archive manifest'],
  [boardSource, 'platformArchiveManifestSummary', 'board must summarize archive manifest'],
  [boardSource, '交付包预览', 'board must label manifest preview for operators'],
  [boardSource, '必备证据', 'board must show required evidence count'],
  [boardSource, '可纳入交付包', 'board must show ready package count'],
  [boardSource, '阻塞清单', 'board must show blocker count'],
]

for (const [source, token, message] of requiredTokens) {
  if (!source.includes(token)) fail(message)
}

if (!/fetchProjectDeliveryArchiveManifest\(activeProjectId\)\.catch\(\(\) => null\)/.test(boardSource)) {
  fail('board must load archive manifest without breaking the legacy dashboard')
}

console.log('[OK] Vue delivery archive manifest is wired.')
