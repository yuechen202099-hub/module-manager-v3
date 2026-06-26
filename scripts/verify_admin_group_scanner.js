const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const viewPath = path.join(root, 'v2-web', 'src', 'views', 'GlobalSearchView.vue')
const packagePath = path.join(root, 'v2-web', 'package.json')

const source = fs.readFileSync(viewPath, 'utf8')
const pkg = JSON.parse(fs.readFileSync(packagePath, 'utf8'))

const checks = [
  ['@zxing/browser dependency is declared', Boolean(pkg.dependencies && pkg.dependencies['@zxing/browser'])],
  ['ZXing reader is imported', source.includes('@zxing/browser') && source.includes('BrowserMultiFormatReader')],
  ['scanner has ZXing video fallback', source.includes('decodeFromConstraints')],
  ['scanner explains HTTPS requirement', source.includes('https://') && source.includes('摄像头')],
  ['scanner has mobile photo/file fallback', source.includes('capture="environment"') && source.includes('scannerFileInput')],
  ['scanner can decode selected image fallback', source.includes('decodeFromImageElement') || source.includes('decodeFromImageUrl')],
  ['scanner cleans up on component unmount', source.includes('onUnmounted(stopScanner)')],
  ['scanner file input is visually hidden instead of display none', source.includes('position: absolute') && !source.includes('display: none')],
]

const failed = checks.filter(([, ok]) => !ok)
for (const [label, ok] of checks) {
  console.log(`${ok ? '[OK]' : '[FAIL]'} ${label}`)
}

if (failed.length) {
  process.exitCode = 1
}
