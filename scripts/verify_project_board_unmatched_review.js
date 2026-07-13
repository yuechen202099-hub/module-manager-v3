const fs = require('fs')

const types = fs.readFileSync('v2-web/src/api/types.ts', 'utf8')
const services = fs.readFileSync('v2-web/src/api/services.ts', 'utf8')

for (const token of [
  'UnmatchedReviewDetail',
  'UnmatchedReviewPhoto',
  'UnmatchedMatchCandidate',
  'fetchUnmatchedReview',
  'saveUnmatchedReview',
  'rescanUnmatchedReviewPhoto',
  'confirmUnmatchedReview',
  'fetchUnmatchedMatchCandidates',
  'fetchUnmatchedReviewPhotoObjectUrl',
  'finalizeUnmatchedMatch',
]) {
  if (!types.includes(token) && !services.includes(token)) throw new Error(`missing ${token}`)
}

for (const route of [
  '/review',
  '/photos/${encodeURIComponent(photoId)}/content',
  '/photos/${encodeURIComponent(photoId)}/rescan',
  '/confirm',
  '/candidates',
  '/finalize-match',
]) {
  if (!services.includes(route)) throw new Error(`missing route ${route}`)
}

if (services.includes('photoProxyUrl(url: string)')) throw new Error('must not proxy caller supplied URLs')
if (!services.includes('createVerifiedImageObjectUrl(blob)')) throw new Error('photo content must verify server-owned image blobs')

console.log('project board unmatched review API contract checks passed')
