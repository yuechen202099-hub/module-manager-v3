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
  [typesSource, 'export type PlatformDeliveryArchiveReadiness', 'types must expose delivery archive readiness'],
  [typesSource, 'readyForArchive: number', 'types must expose readyForArchive count'],
  [typesSource, 'evidenceGap: number', 'types must expose evidenceGap count'],
  [typesSource, 'blockers: PlatformDeliveryArchiveBlocker[]', 'types must expose blockers'],
  [servicesSource, 'type BackendPlatformDeliveryArchiveReadiness', 'services must define backend readiness contract'],
  [servicesSource, 'function mapPlatformDeliveryArchiveReadiness', 'services must map archive readiness'],
  [servicesSource, 'export async function fetchProjectDeliveryArchiveReadiness', 'services must fetch archive readiness'],
  [servicesSource, '/delivery/archive-readiness', 'services must call archive readiness route'],
  [boardSource, 'fetchProjectDeliveryArchiveReadiness', 'board must load archive readiness'],
  [boardSource, 'deliveryArchiveReadiness', 'board must store archive readiness'],
  [boardSource, 'platformArchiveReadinessCards', 'board must render archive readiness cards'],
  [boardSource, 'platformArchiveBlockerCards', 'board must summarize blockers'],
  [boardSource, '交付归档就绪', 'board must label archive readiness for operators'],
  [boardSource, '可归档', 'board must show ready-for-archive count'],
  [boardSource, '证据缺口', 'board must show evidence gap count'],
  [boardSource, '待审阅', 'board must show pending review count'],
  [boardSource, '返工', 'board must show returned rework count'],
  [boardSource, '异常', 'board must show exception count'],
]

for (const [source, token, message] of requiredTokens) {
  if (!source.includes(token)) fail(message)
}

const platformKpiSectionStart = boardSource.indexOf('<section v-if="platformProject?.tasks" class="panel platform-kpi-band">')
const archiveSectionStart = boardSource.indexOf('浜や粯褰掓。灏辩华')
if (platformKpiSectionStart >= 0 && archiveSectionStart >= platformKpiSectionStart) {
  const nextSectionStart = boardSource.indexOf('<section', platformKpiSectionStart + 1)
  if (nextSectionStart < 0 || archiveSectionStart < nextSectionStart) {
    fail('archive readiness must not be hidden inside the platform tasks KPI section')
  }
}

if (!boardSource.includes('v-if="deliveryArchiveReadiness"')) {
  fail('archive readiness section must render from deliveryArchiveReadiness even when platform task KPIs are absent')
}

console.log('[OK] Vue delivery archive readiness is wired.')
