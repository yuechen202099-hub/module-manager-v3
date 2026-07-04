const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const typesSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'api', 'types.ts'), 'utf8')
const servicesSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'api', 'services.ts'), 'utf8')
const projectsSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue'), 'utf8')
const constructionSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ConstructionView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requiredTokens = [
  [typesSource, 'export type ProjectFieldRequiredWhen', 'frontend type must define field-level conditional requirement'],
  [typesSource, 'requiredWhen?: ProjectFieldRequiredWhen', 'ProjectFieldDefinition must expose requiredWhen'],
  [typesSource, 'requiredWhen?: ProjectFieldRequiredWhen', 'Construction photo slots must be able to carry requiredWhen'],
  [servicesSource, 'type BackendProjectFieldRequiredWhen', 'service mapping must define backend required_when type'],
  [servicesSource, 'required_when?: BackendProjectFieldRequiredWhen', 'backend field mapping must accept required_when'],
  [servicesSource, 'function mapRequiredWhen', 'backend -> frontend required_when mapper missing'],
  [servicesSource, 'function mapRequiredWhenForCreate', 'frontend -> backend requiredWhen mapper missing'],
  [servicesSource, 'requiredWhen: mapRequiredWhen(raw.required_when)', 'frontend field mapper must keep requiredWhen'],
  [servicesSource, 'required_when: mapRequiredWhenForCreate(field.requiredWhen)', 'create mapper must send requiredWhen'],
  [projectsSource, "requiredWhen: { fieldKey: 'collector_replace_confirm', equals: '更换' }", 'module preset must conditionally require collector number'],
  [projectsSource, "requiredWhen: { fieldKey: 'communication_module_replace_confirm', equals: '更换' }", 'terminal preset must conditionally require communication module number'],
  [projectsSource, "requiredWhen: { fieldKey: 'sim_card_replace_confirm', equals: '更换' }", 'terminal preset must conditionally require SIM number'],
  [constructionSource, 'function fieldConditionValue', 'construction view must read controlling field values'],
  [constructionSource, 'function isFieldRequired', 'construction view must compute dynamic field requirement'],
  [constructionSource, 'function isFieldRequiredForValues', 'draft validation must compute dynamic field requirement from cached values'],
  [constructionSource, 'function conditionalRequiredHint', 'UI must explain conditional required fields'],
  [constructionSource, 'isFieldRequired(field)', 'current form validation must use dynamic requirement'],
  [constructionSource, 'isFieldRequiredForValues(field, draft.field_values || {})', 'draft upload validation must use dynamic requirement'],
  [constructionSource, 'function isPhotoSlotRequired', 'photo slot validation must support conditional requirements'],
  [constructionSource, 'function isPhotoSlotRequiredForValues', 'cached photo validation must support conditional requirements'],
]

for (const [source, token, message] of requiredTokens) {
  if (!source.includes(token)) fail(message)
}

console.log('[OK] Vue conditional required fields are wired.')
