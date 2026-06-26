const fs = require('fs')
const path = require('path')

const repoRoot = path.resolve(__dirname, '..')
const servicesPath = path.join(repoRoot, 'v2-web', 'src', 'api', 'services.ts')
const source = fs.readFileSync(servicesPath, 'utf8')

if (/mockGroups|mockPhotos/.test(source)) {
  throw new Error('production API services must not reference mockGroups/mockPhotos placeholder construction data')
}

const start = source.indexOf('export async function fetchGroup(')
const end = source.indexOf('export async function saveReview(', start)

if (start === -1 || end === -1 || end <= start) {
  throw new Error('fetchGroup function not found')
}

const fetchGroupSource = source.slice(start, end)

if (/catch\s*\{/.test(fetchGroupSource)) {
  throw new Error('fetchGroup must let API failures bubble to callers instead of returning placeholder mock data')
}

console.log('construction fetchGroup mock fallback guard passed')
