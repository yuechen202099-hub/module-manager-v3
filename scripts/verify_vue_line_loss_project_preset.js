const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const projectsView = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ProjectsView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requiredTokens = [
  "id: 'line-loss-investigation'",
  "key: 'station_area_no'",
  "key: 'power_supply_unit'",
  "key: 'master_meter_no'",
  "key: 'user_no'",
  "key: 'line_loss_issue_type'",
  "key: 'master_meter_photo'",
  "key: 'user_meter_sample_photo'",
  "key: 'site_check_note'",
]

for (const token of requiredTokens) {
  if (!projectsView.includes(token)) fail(`ProjectsView.vue missing line-loss preset token: ${token}`)
}

const patterns = [
  [
    /id: 'line-loss-investigation'[\s\S]*?key: 'station_area_no'[\s\S]*?source: 'import'[\s\S]*?captureMethod: 'manual'[\s\S]*?relationRole: 'task_object'/,
    'line-loss preset primary field must be station_area_no task_object',
  ],
  [
    /id: 'line-loss-investigation'[\s\S]*?key: 'power_supply_unit'[\s\S]*?source: 'import'[\s\S]*?captureMethod: 'manual'[\s\S]*?relationRole: 'aggregate'/,
    'line-loss preset must aggregate by one active aggregate field',
  ],
  [
    /key: 'master_meter_no'[\s\S]*?source: 'import'[\s\S]*?parentKey: 'station_area_no'[\s\S]*?relationRole: 'task_detail'/,
    'line-loss preset master meter must be a task detail under station_area_no',
  ],
  [
    /key: 'user_no'[\s\S]*?source: 'import'[\s\S]*?parentKey: 'station_area_no'[\s\S]*?relationRole: 'task_detail'/,
    'line-loss preset user must be a task detail under station_area_no',
  ],
  [
    /key: 'line_loss_issue_type'[\s\S]*?dataType: 'enum'[\s\S]*?source: 'field_collection'[\s\S]*?captureMethod: 'select'[\s\S]*?parentKey: 'station_area_no'[\s\S]*?relationRole: 'supporting_field'/,
    'line-loss preset issue type must be selected during field collection',
  ],
  [
    /key: 'master_meter_photo'[\s\S]*?dataType: 'image'[\s\S]*?captureMethod: 'photo'[\s\S]*?parentKey: 'station_area_no'[\s\S]*?relationRole: 'evidence_photo'/,
    'line-loss preset master meter photo must be evidence under station_area_no',
  ],
  [
    /key: 'user_meter_sample_photo'[\s\S]*?dataType: 'image'[\s\S]*?captureMethod: 'photo'[\s\S]*?parentKey: 'station_area_no'[\s\S]*?relationRole: 'evidence_photo'/,
    'line-loss preset user meter sample photo must be evidence under station_area_no',
  ],
]

for (const [pattern, message] of patterns) {
  if (!pattern.test(projectsView)) fail(message)
}

console.log('[OK] Vue line-loss project preset is represented.')
