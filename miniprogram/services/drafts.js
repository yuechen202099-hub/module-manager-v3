const { PHOTO_SLOTS } = require('../utils/constants')

const DRAFT_KEY = 'constructionDrafts:v1'

function readAll() {
  return wx.getStorageSync(DRAFT_KEY) || {}
}

function writeAll(value) {
  wx.setStorageSync(DRAFT_KEY, value || {})
}

function draftKey(taskId, groupId) {
  return `${taskId || ''}:${groupId || ''}`
}

function createDraft(taskId, group) {
  const now = new Date().toISOString()
  return {
    taskId: String(taskId || group.task_id || ''),
    groupId: String(group.id || ''),
    clientBatchId: `wx-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    group,
    collector: group.construction_collector || group.collector || '',
    moduleAssetNo: group.construction_module_asset_no || group.module_asset_no || '',
    exceptionNote: group.exception_note || '',
    photos: {},
    status: 'editing',
    createdAt: now,
    updatedAt: now,
    lastError: ''
  }
}

function getDraft(taskId, groupId) {
  return readAll()[draftKey(taskId, groupId)] || null
}

function saveDraft(draft) {
  const all = readAll()
  const next = Object.assign({}, draft, {
    updatedAt: new Date().toISOString(),
    status: draftIsSubmittable(draft) ? 'ready' : 'editing'
  })
  all[draftKey(next.taskId, next.groupId)] = next
  writeAll(all)
  return next
}

function deleteDraft(taskId, groupId) {
  const all = readAll()
  delete all[draftKey(taskId, groupId)]
  writeAll(all)
}

function listDrafts(taskId) {
  return Object.values(readAll()).filter((draft) => !taskId || String(draft.taskId) === String(taskId))
}

function draftIsSubmittable(draft) {
  if (!draft) return false
  const photos = draft.photos || {}
  return PHOTO_SLOTS.filter((slot) => slot.required).every((slot) => Boolean(photos[slot.key] && photos[slot.key].path))
}

function mergeDraftWithGroup(taskId, group) {
  return getDraft(taskId, group.id) || createDraft(taskId, group)
}

module.exports = {
  DRAFT_KEY,
  createDraft,
  getDraft,
  saveDraft,
  deleteDraft,
  listDrafts,
  draftIsSubmittable,
  mergeDraftWithGroup
}
