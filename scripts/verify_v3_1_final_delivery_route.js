const fs = require('fs')

const read = (path) => fs.readFileSync(path, 'utf8')
const router = read('v2-web/src/router/index.ts')
const layout = read('v2-web/src/layouts/AppLayout.vue')
const claimTasks = read('v2-web/src/views/ClaimTasksView.vue')
const services = read('v2-web/src/api/services.ts')

function assertContains(source, pattern, message) {
  if (!pattern.test(source)) throw new Error(message)
}

function assertNotContains(source, pattern, message) {
  if (pattern.test(source)) throw new Error(message)
}

assertContains(router, /component:\s*AppLayout/, 'real routed pages must render through AppLayout')
assertContains(
  router,
  /'claim-tasks':\s*\(\)\s*=>\s*import\('@\/views\/ClaimTasksView\.vue'\)/,
  'claim-tasks must use the native routed Vue view',
)
assertContains(
  claimTasks,
  /module-manager:start-terminal-export/,
  'the routed claim-tasks view must dispatch formal terminal delivery through the shell',
)
assertContains(
  layout,
  /exportTerminalDeliveryPackage\([\s\S]{0,300}taskId,[\s\S]{0,300}terminal,[\s\S]{0,300}reviewScope/,
  'AppLayout must call the authenticated formal delivery client with the routed scope',
)
assertContains(
  services,
  /export async function exportTerminalDeliveryPackage[\s\S]{0,1400}fetchWithAuth\('\/exports\/final-delivery'/,
  'the routed delivery client must call POST /exports/final-delivery',
)
assertContains(
  services,
  /export async function exportTerminalDeliveryPackage[\s\S]{0,1800}response\.blob\(\)[\s\S]{0,600}triggerBrowserDownload/,
  'the routed delivery client must download the formal API Blob',
)
assertNotContains(
  services,
  /\/local-test\/export-manifest\/final-delivery/,
  'the production client must not reach the legacy delivery manifest',
)
assertNotContains(services, /createZipBlob|buildCsv|fetchImageBlob/, 'the production client must not build partial ZIP/CSV packages')
assertNotContains(services, /photo-proxy\?url=/, 'the production client must not fall back to original-photo proxy reads')

console.log('V3.1 formal delivery route source checks passed')
