import assert from 'node:assert/strict'
import fs from 'node:fs'

import {
  createConstructionPriorityImportSession,
  parseContentDispositionFilename,
} from '../v2-web/src/api/constructionPriorityImportState.mjs'

function deferred() {
  let reject
  let resolve
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, reject, resolve }
}

function createDialogHarness() {
  const importSession = createConstructionPriorityImportSession()
  const downloadSession = createConstructionPriorityImportSession()
  const state = {
    confirming: false,
    downloading: false,
    error: '',
    imported: 0,
    preview: null,
    previewing: false,
  }

  function reset() {
    importSession.invalidate()
    downloadSession.invalidate()
    state.confirming = false
    state.downloading = false
    state.error = ''
    state.preview = null
    state.previewing = false
  }

  async function previewRequest(request) {
    const token = importSession.begin()
    state.error = ''
    state.previewing = true
    try {
      const result = await request
      if (importSession.isCurrent(token)) state.preview = result
    } catch (error) {
      if (importSession.isCurrent(token)) state.error = error instanceof Error ? error.message : String(error)
    } finally {
      if (importSession.isCurrent(token)) state.previewing = false
    }
  }

  async function downloadRequest(request) {
    const token = downloadSession.begin()
    state.downloading = true
    state.error = ''
    try {
      await request
    } catch (error) {
      if (downloadSession.isCurrent(token)) state.error = error instanceof Error ? error.message : String(error)
    } finally {
      if (downloadSession.isCurrent(token)) state.downloading = false
    }
  }

  async function confirmRequest(request) {
    const token = importSession.begin()
    state.confirming = true
    state.error = ''
    try {
      const result = await request
      if (importSession.isCurrent(token) && result.confirmed) state.imported += 1
    } catch (error) {
      if (importSession.isCurrent(token)) state.error = error instanceof Error ? error.message : String(error)
    } finally {
      if (importSession.isCurrent(token)) state.confirming = false
    }
  }

  function selectFile() {
    importSession.invalidate()
  }

  return { confirmRequest, downloadRequest, previewRequest, reset, selectFile, state }
}

const previewRace = createDialogHarness()
const previewA = deferred()
const previewB = deferred()
const previewAPromise = previewRace.previewRequest(previewA.promise)
assert.equal(previewRace.state.previewing, true)
previewRace.reset()
const previewBPromise = previewRace.previewRequest(previewB.promise)
assert.equal(previewRace.state.previewing, true)
previewA.resolve({ source: 'A' })
await previewAPromise
assert.equal(previewRace.state.preview, null)
assert.equal(previewRace.state.previewing, true)
previewB.resolve({ source: 'B' })
await previewBPromise
assert.deepEqual(previewRace.state.preview, { source: 'B' })
assert.equal(previewRace.state.previewing, false)

const confirmRace = createDialogHarness()
const confirmA = deferred()
const confirmB = deferred()
const confirmAPromise = confirmRace.confirmRequest(confirmA.promise)
assert.equal(confirmRace.state.confirming, true)
confirmRace.reset()
const confirmBPromise = confirmRace.confirmRequest(confirmB.promise)
confirmA.resolve({ confirmed: true })
await confirmAPromise
assert.equal(confirmRace.state.imported, 0)
assert.equal(confirmRace.state.confirming, true)
confirmB.reject(new Error('B failed'))
await confirmBPromise
assert.equal(confirmRace.state.imported, 0)
assert.equal(confirmRace.state.error, 'B failed')
assert.equal(confirmRace.state.confirming, false)

const staleConfirmError = createDialogHarness()
const rejectedConfirm = deferred()
const currentConfirm = deferred()
const rejectedConfirmPromise = staleConfirmError.confirmRequest(rejectedConfirm.promise)
staleConfirmError.reset()
const currentConfirmPromise = staleConfirmError.confirmRequest(currentConfirm.promise)
rejectedConfirm.reject(new Error('stale confirm failed'))
await rejectedConfirmPromise
assert.equal(staleConfirmError.state.error, '')
assert.equal(staleConfirmError.state.confirming, true)
currentConfirm.resolve({ confirmed: true })
await currentConfirmPromise
assert.equal(staleConfirmError.state.imported, 1)
assert.equal(staleConfirmError.state.confirming, false)

const loadingRace = createDialogHarness()
const stalePreview = deferred()
const currentPreview = deferred()
const stalePreviewPromise = loadingRace.previewRequest(stalePreview.promise)
const currentPreviewPromise = loadingRace.previewRequest(currentPreview.promise)
stalePreview.reject(new Error('stale failed'))
await stalePreviewPromise
assert.equal(loadingRace.state.previewing, true)
assert.equal(loadingRace.state.error, '')
currentPreview.resolve({ source: 'current' })
await currentPreviewPromise
assert.equal(loadingRace.state.previewing, false)

const fileChangeDownload = createDialogHarness()
const fileChangeRequest = deferred()
const fileChangeDownloadPromise = fileChangeDownload.downloadRequest(fileChangeRequest.promise)
fileChangeDownload.selectFile()
fileChangeRequest.resolve()
await fileChangeDownloadPromise
assert.equal(fileChangeDownload.state.downloading, false)

const previewChangeDownload = createDialogHarness()
const previewChangeRequest = deferred()
const previewChangeImport = deferred()
const previewChangeDownloadPromise = previewChangeDownload.downloadRequest(previewChangeRequest.promise)
const previewChangeImportPromise = previewChangeDownload.previewRequest(previewChangeImport.promise)
previewChangeRequest.reject(new Error('download failed in current dialog'))
await previewChangeDownloadPromise
assert.equal(previewChangeDownload.state.downloading, false)
assert.equal(previewChangeDownload.state.error, 'download failed in current dialog')
previewChangeImport.resolve({ source: 'preview' })
await previewChangeImportPromise

const confirmChangeDownload = createDialogHarness()
const confirmChangeRequest = deferred()
const confirmChangeImport = deferred()
const confirmChangeDownloadPromise = confirmChangeDownload.downloadRequest(confirmChangeRequest.promise)
const confirmChangeImportPromise = confirmChangeDownload.confirmRequest(confirmChangeImport.promise)
confirmChangeRequest.resolve()
await confirmChangeDownloadPromise
assert.equal(confirmChangeDownload.state.downloading, false)
confirmChangeImport.resolve({ confirmed: false })
await confirmChangeImportPromise

const rejectedDownload = createDialogHarness()
const slowDownloadReject = deferred()
const slowDownloadRejectPromise = rejectedDownload.downloadRequest(slowDownloadReject.promise)
assert.equal(rejectedDownload.state.downloading, true)
rejectedDownload.reset()
assert.equal(rejectedDownload.state.downloading, false)
rejectedDownload.state.error = 'new session error'
slowDownloadReject.reject(new Error('stale download failed'))
await slowDownloadRejectPromise
assert.equal(rejectedDownload.state.error, 'new session error')
assert.equal(rejectedDownload.state.downloading, false)

const resolvedDownload = createDialogHarness()
const slowDownloadResolve = deferred()
const currentDownload = deferred()
const slowDownloadResolvePromise = resolvedDownload.downloadRequest(slowDownloadResolve.promise)
resolvedDownload.reset()
const currentDownloadPromise = resolvedDownload.downloadRequest(currentDownload.promise)
assert.equal(resolvedDownload.state.downloading, true)
slowDownloadResolve.resolve()
await slowDownloadResolvePromise
assert.equal(resolvedDownload.state.downloading, true)
currentDownload.resolve()
await currentDownloadPromise
assert.equal(resolvedDownload.state.downloading, false)

const dialogSource = fs.readFileSync('v2-web/src/components/ConstructionPriorityImportDialog.vue', 'utf8')
assert.match(dialogSource, /const importRequestSession = createConstructionPriorityImportSession\(\)/)
assert.match(dialogSource, /const downloadRequestSession = createConstructionPriorityImportSession\(\)/)
assert.match(dialogSource, /async function downloadTemplate\(\) \{(?:(?!\nasync function)[\s\S])*?downloadRequestSession\.begin\(\)/)
assert.match(dialogSource, /async function downloadTemplate\(\) \{(?:(?!\nasync function)[\s\S])*?downloadRequestSession\.isCurrent\(requestToken\)/)
assert.match(dialogSource, /function reset\(\) \{(?:(?!\nfunction closeDialog)[\s\S])*?importRequestSession\.invalidate\(\)[\s\S]*?downloadRequestSession\.invalidate\(\)[\s\S]*?downloadingTemplate\.value = false/)

assert.equal(
  parseContentDispositionFilename(
    "attachment; filename=priority-template.xlsx; filename*=UTF-8''%E7%BB%88%E7%AB%AF%E4%BC%98%E5%85%88%E6%96%BD%E5%B7%A5%E5%AF%BC%E5%85%A5%E6%A8%A1%E6%9D%BF.xlsx",
    'fallback.xlsx',
  ),
  '终端优先施工导入模板.xlsx',
)
assert.equal(
  parseContentDispositionFilename('attachment; filename=priority-template.xlsx; filename*=UTF-8\'\'%ZZ', 'fallback.xlsx'),
  'priority-template.xlsx',
)
assert.equal(
  parseContentDispositionFilename(
    "attachment; filename=priority-template.xlsx; filename*=\"UTF-8''%E7%BB%88%E7%AB%AF%E4%BC%98%E5%85%88%E6%96%BD%E5%B7%A5%E5%AF%BC%E5%85%A5%E6%A8%A1%E6%9D%BF.xlsx\";",
    'fallback.xlsx',
  ),
  '终端优先施工导入模板.xlsx',
)

console.log('construction priority import state behavior checks passed')
