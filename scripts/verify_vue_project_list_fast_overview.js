const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const servicesPath = path.join(root, 'v2-web', 'src', 'api', 'services.ts')
const source = fs.readFileSync(servicesPath, 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const match = source.match(/export async function fetchProjectsWithModules\(\): Promise<Project\[]> \{([\s\S]*?)\n\}/)
if (!match) {
  fail('fetchProjectsWithModules must exist in services.ts')
}

const body = match[1]
if (!body.includes("api<{ items: BackendPlatformProject[] }>('/projects')")) {
  fail('fetchProjectsWithModules must load the /projects overview endpoint')
}
if (!body.includes('return projects')) {
  fail('fetchProjectsWithModules must return the mapped overview projects directly')
}
if (body.includes('fetchProjectModuleSections') || body.includes('Promise.all')) {
  fail('project list loading must not block on per-project module section requests')
}

console.log('[OK] Vue project list uses fast overview data without per-project module fan-out.')
