const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const typesPath = path.join(root, 'v2-web', 'src', 'api', 'types.ts')
const servicesPath = path.join(root, 'v2-web', 'src', 'api', 'services.ts')
const typesSource = fs.readFileSync(typesPath, 'utf8')
const servicesSource = fs.readFileSync(servicesPath, 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requiredTypeTokens = [
  'export type ProjectWorkflowNode',
  'export type ProjectWorkflowEdge',
  'export type ProjectWorkflow',
  'workflow?: ProjectWorkflow',
]

for (const token of requiredTypeTokens) {
  if (!typesSource.includes(token)) fail(`types.ts missing workflow token: ${token}`)
}

const requiredServiceTokens = [
  'type BackendProjectWorkflowNode',
  'type BackendProjectWorkflowEdge',
  'type BackendProjectWorkflow',
  'function mapProjectWorkflow',
  'function mapProjectWorkflowForSave',
  'workflow: mapProjectWorkflow(raw.workflow)',
  'export async function fetchProjectWorkflow',
  'export async function saveProjectWorkflow',
  'export async function resetProjectWorkflow',
  '/workflow/reset',
]

for (const token of requiredServiceTokens) {
  if (!servicesSource.includes(token)) fail(`services.ts missing workflow token: ${token}`)
}

console.log('[OK] Vue API exposes project workflow read, save, and reset plumbing.')

