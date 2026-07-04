const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const graphSource = fs.readFileSync(
  path.join(root, 'v2-web', 'src', 'components', 'project-fields', 'FieldGraphDesigner.vue'),
  'utf8',
)

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requiredTokens = [
  ['localInitialTemplateFieldRows', 'field graph must build local initial import template rows for draft schemas'],
  ['localExternalCompletedTemplateFieldRows', 'field graph must build local external-completed template rows for draft schemas'],
  ['platformGeneratedTemplateRows', 'field graph must list fields generated at upload time'],
  ['templateImpactSummaryCards', 'field graph must summarize template impact by import, completed, and platform-generated data'],
  ['template-impact-summary', 'field graph must render the template impact summary panel'],
  ['platform-generated-template-list', 'field graph must render platform-generated upload-time fields'],
  ['上传时平台生成', 'field graph must explain upload-time platform generated fields in operator language'],
  ['templatePreviewRowFromField', 'field graph must convert schema fields into preview rows when backend preview is absent'],
  ['templateParentLabelForField', 'field graph must preserve parent labels in local preview rows'],
]

for (const [token, message] of requiredTokens) {
  if (!graphSource.includes(token)) fail(message)
}

const emptyRowFallbacks = [
  'initialWorkOrderFields: [] as ProjectTemplatePreviewField[]',
  'externalCompletedFields: [] as ProjectTemplatePreviewField[]',
]

for (const token of emptyRowFallbacks) {
  if (graphSource.includes(token)) fail(`field graph source must not rely on empty local rows: ${token}`)
}

console.log('[OK] Vue template impact preview is generated locally for draft schemas.')
