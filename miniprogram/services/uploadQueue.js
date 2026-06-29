const { uploadFile, request } = require('../utils/api')
const { PHOTO_SLOTS } = require('../utils/constants')
const drafts = require('./drafts')

function draftPhotoEntries(draft) {
  return PHOTO_SLOTS
    .map((slot) => {
      const photo = draft.photos && draft.photos[slot.key]
      return photo && photo.path ? { slot, photo } : null
    })
    .filter(Boolean)
}

function recordNonIdle(draft, eventType) {
  return request('/miniprogram/activity/non-idle-events', {
    method: 'POST',
    data: {
      event_type: eventType,
      task_id: draft.taskId,
      group_id: draft.groupId,
      client_batch_id: draft.clientBatchId,
      occurred_at: new Date().toISOString()
    }
  }).catch(() => null)
}

async function uploadDraft(draft) {
  if (!drafts.draftIsSubmittable(draft)) {
    throw new Error('必填照片未完成')
  }
  const entries = draftPhotoEntries(draft)
  let result = null
  for (let index = 0; index < entries.length; index += 1) {
    const entry = entries[index]
    result = await uploadFile(
      `/miniprogram/groups/${encodeURIComponent(draft.groupId)}/upload-file`,
      entry.photo.path,
      {
        client_batch_id: draft.clientBatchId,
        client_completed_at: new Date().toISOString(),
        collector: draft.collector || '',
        module_asset_no: draft.moduleAssetNo || '',
        photo_slot: entry.slot.key,
        client_photo_id: entry.photo.clientPhotoId || `${entry.slot.key}-${index}`,
        expected_count: String(entries.length),
        commit: index === entries.length - 1 ? 'true' : 'false'
      }
    )
  }
  drafts.deleteDraft(draft.taskId, draft.groupId)
  await recordNonIdle(draft, 'group_uploaded')
  return result
}

async function uploadDrafts(items) {
  const results = []
  for (const draft of items) {
    try {
      const result = await uploadDraft(draft)
      results.push({ draft, ok: true, result })
    } catch (error) {
      draft.lastError = error.message || '上传失败'
      drafts.saveDraft(draft)
      results.push({ draft, ok: false, error: draft.lastError })
    }
  }
  return results
}

module.exports = {
  uploadDraft,
  uploadDrafts,
  recordNonIdle
}
