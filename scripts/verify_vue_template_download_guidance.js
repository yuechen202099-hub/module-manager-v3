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
  ['templateDownloadGuideCards', 'field graph must compute download guidance cards'],
  ['template-download-guide', 'field graph must render the download guidance panel'],
  ['template / fields / instructions', 'field graph must tell users the workbook has three worksheets'],
  ['Excel说明页', 'field graph must name the workbook instructions sheet in operator language'],
  ['任务对象下更换附属设备', 'field graph must explain module replacement hierarchy before download'],
  ['主设备更换后确认附属设备', 'field graph must explain terminal replacement hierarchy before download'],
  ['换模块下载前会提示附属设备挂在任务对象下', 'field graph must provide a module-specific predownload hint'],
  ['换终端下载前会提示先记录旧主设备和新主设备', 'field graph must provide a terminal-specific predownload hint'],
]

for (const [token, message] of requiredTokens) {
  if (!graphSource.includes(token)) fail(message)
}

console.log('[OK] Vue template download guidance explains workbook sheets and device hierarchy modes.')
