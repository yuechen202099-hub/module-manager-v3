const QUEUE_KEY = "construction_upload_queue_v1";
const GROUP_DRAFT_KEY = "construction_group_drafts_v1";
const TERMINAL_SNAPSHOT_KEY = "construction_terminal_snapshots_v1";
const REQUIRED_SLOTS = ["before_box", "module_meter", "after_box"];

function uuid(prefix = "id") {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function loadQueue() {
  return wx.getStorageSync(QUEUE_KEY) || [];
}

function saveQueue(items) {
  wx.setStorageSync(QUEUE_KEY, items || []);
}

function getQueueCount() {
  return loadQueue().length;
}

function currentSession() {
  const api = require("./api");
  return api.session() || {};
}

function currentActor() {
  return currentSession()?.user?.username || "constructor";
}

function currentTeamId() {
  const api = require("./api");
  return api.teamId ? api.teamId() : (currentSession()?.team_id || "default-team");
}

function legacyGroupDraftKey(taskId, groupId) {
  return `${taskId || "task"}::${groupId || "group"}`;
}

function groupDraftKey(taskId, groupId, teamId = currentTeamId(), actor = currentActor()) {
  return `${teamId || "default-team"}::${actor || "constructor"}::${taskId || "task"}::${groupId || "group"}`;
}

function terminalSnapshotKey(taskId, teamId = currentTeamId(), actor = currentActor()) {
  return `${teamId || "default-team"}::${actor || "constructor"}::${taskId || "task"}`;
}

function loadGroupDrafts() {
  return wx.getStorageSync(GROUP_DRAFT_KEY) || {};
}

function saveGroupDrafts(drafts) {
  wx.setStorageSync(GROUP_DRAFT_KEY, drafts || {});
}

function loadTerminalSnapshots() {
  return wx.getStorageSync(TERMINAL_SNAPSHOT_KEY) || {};
}

function saveTerminalSnapshots(snapshots) {
  wx.setStorageSync(TERMINAL_SNAPSHOT_KEY, snapshots || {});
}

function saveTerminalSnapshot(task, groups) {
  if (!task?.id) return null;
  const snapshots = loadTerminalSnapshots();
  const key = terminalSnapshotKey(task.id);
  const snapshot = {
    key,
    teamId: currentTeamId(),
    actor: currentActor(),
    taskId: task.id,
    task,
    terminal: task.terminal || "",
    groups: groups || [],
    updated_at: new Date().toISOString()
  };
  snapshots[key] = snapshot;
  saveTerminalSnapshots(snapshots);
  return snapshot;
}

function loadTerminalSnapshot(taskId) {
  const snapshots = loadTerminalSnapshots();
  return snapshots[terminalSnapshotKey(taskId)] || null;
}

function listTerminalSnapshots() {
  const teamId = currentTeamId();
  const actor = currentActor();
  return Object.values(loadTerminalSnapshots()).filter((item) => item.teamId === teamId && item.actor === actor);
}

function getCachedGroup(taskId, groupId) {
  const snapshot = loadTerminalSnapshot(taskId);
  return (snapshot?.groups || []).find((group) => String(group.id) === String(groupId)) || null;
}

function loadGroupDraft(taskId, groupId) {
  const drafts = loadGroupDrafts();
  return drafts[groupDraftKey(taskId, groupId)] || drafts[legacyGroupDraftKey(taskId, groupId)] || null;
}

function saveGroupDraft(taskId, groupId, draft) {
  const drafts = loadGroupDrafts();
  drafts[groupDraftKey(taskId, groupId)] = {
    ...draft,
    teamId: draft.teamId || currentTeamId(),
    actor: draft.actor || currentActor(),
    taskId,
    groupId,
    updated_at: new Date().toISOString()
  };
  delete drafts[legacyGroupDraftKey(taskId, groupId)];
  saveGroupDrafts(drafts);
}

function removeGroupDraft(taskId, groupId) {
  const drafts = loadGroupDrafts();
  delete drafts[groupDraftKey(taskId, groupId)];
  delete drafts[legacyGroupDraftKey(taskId, groupId)];
  saveGroupDrafts(drafts);
}

function enqueueDraft(draft) {
  const items = loadQueue();
  const index = items.findIndex((item) => item.client_batch_id === draft.client_batch_id);
  const next = {
    ...draft,
    status: "queued",
    updated_at: new Date().toISOString()
  };
  if (index >= 0) items[index] = next;
  else items.unshift(next);
  saveQueue(items);
  return next;
}

function groupDraftToUploadDraft(draft) {
  const actor = draft.actor || currentActor();
  const photos = (draft.slots || [])
    .filter((slot) => slot.filePath)
    .map((slot) => ({
      slot: slot.key,
      label: slot.label,
      filePath: slot.filePath,
      client_photo_id: slot.client_photo_id || uuid(slot.key)
    }));
  return {
    client_batch_id: draft.client_batch_id || uuid("batch"),
    actor,
    teamId: draft.teamId || currentTeamId(),
    taskId: draft.taskId,
    groupId: draft.groupId,
    meter_no: draft.meter_no || "",
    terminal: draft.terminal || "",
    address: draft.address || "",
    collector: draft.collector || "",
    module_asset_no: draft.module_asset_no || "",
    work_order_id: draft.work_order_id || "",
    exception_category: draft.exception_category || "",
    exception_note: draft.exception_note || "",
    covered_slots: draft.covered_slots || [],
    photos,
    kind: "group-draft",
    updated_at: draft.updated_at
  };
}

function coveredSlotSet(draft, photos = draft.photos || []) {
  return new Set([
    ...(draft.covered_slots || []),
    ...(draft.existing_photo_slots || []),
    ...photos.filter((photo) => photo.filePath).map((photo) => photo.slot)
  ].filter(Boolean));
}

function exceptionNeedsPhotoSlots(draft) {
  if (!draft.work_order_id) return true;
  const text = `${draft.exception_category || ""} ${draft.exception_note || ""}`.toLowerCase();
  if (!text.trim()) return true;
  return /photo|image|missing|\u7167\u7247|\u7f3a|\u56fe|\u5716/.test(text);
}

function cacheMissingFields(draft) {
  const missing = [];
  if (!String(draft.module_asset_no || "").trim()) missing.push("模块号");
  const photos = draft.photos || [];
  const covered = coveredSlotSet(draft, photos);
  if (exceptionNeedsPhotoSlots(draft)) {
    REQUIRED_SLOTS.forEach((slot) => {
      if (!covered.has(slot)) {
        missing.push(slot === "before_box" ? "改造前照片" : slot === "module_meter" ? "模块与电表照片" : "改造后照片");
      }
    });
  }
  return missing;
}

function markCacheScope(item, activeGroupIds) {
  const teamId = currentTeamId();
  const actor = currentActor();
  let staleReason = "";
  if (item.teamId !== teamId) staleReason = item.teamId ? "来自其他团队" : "早期版本缓存缺少团队标识";
  else if (item.actor !== actor) staleReason = item.actor ? "来自其他账号" : "早期版本缓存缺少账号标识";
  else if (activeGroupIds && !activeGroupIds[String(item.groupId || "")]) staleReason = "当前项目没有对应资料组";
  return {
    ...item,
    stale: Boolean(staleReason),
    staleReason
  };
}

function listCacheItems(options = {}) {
  const queued = loadQueue().map((item) => ({ ...item, kind: "queued" }));
  const saved = Object.values(loadGroupDrafts()).map(groupDraftToUploadDraft);
  const merged = new Map();
  function cacheKey(item) {
    return item.taskId && item.groupId
      ? `${item.teamId || currentTeamId()}::${item.actor || currentActor()}::${item.taskId}::${item.groupId}`
      : item.client_batch_id;
  }
  [...saved, ...queued].forEach((item) => {
    merged.set(cacheKey(item), item);
  });
  return [...merged.values()].map((item) => {
    const missing = cacheMissingFields(item);
    const decorated = markCacheScope({
      ...item,
      missing,
      covered_slots: [...coveredSlotSet(item)],
      ready: missing.length === 0 && ((item.photos || []).length > 0 || Boolean(item.work_order_id))
    }, options.activeGroupIds || null);
    return decorated;
  }).filter((item) => options.includeStale || !item.stale);
}

function getCacheSummary(options = {}) {
  const items = listCacheItems(options);
  const currentItems = items.filter((item) => !item.stale);
  return {
    total: currentItems.length,
    ready: currentItems.filter((item) => item.ready).length,
    blocked: currentItems.filter((item) => !item.ready).length,
    queued: currentItems.filter((item) => item.kind === "queued").length,
    saved: currentItems.filter((item) => item.kind === "group-draft").length,
    stale: items.filter((item) => item.stale).length
  };
}

function removeDraft(clientBatchId) {
  saveQueue(loadQueue().filter((item) => item.client_batch_id !== clientBatchId));
}

function removeCacheItem(item) {
  if (!item) return;
  removeDraft(item.client_batch_id);
  if (item.taskId && item.groupId) removeGroupDraft(item.taskId, item.groupId);
}

function updateCacheItem(clientBatchId, changes = {}) {
  const patch = {
    ...changes,
    updated_at: new Date().toISOString()
  };
  let updated = null;
  const queueItems = loadQueue().map((item) => {
    if (item.client_batch_id !== clientBatchId) return item;
    updated = { ...item, ...patch };
    return updated;
  });
  if (updated) {
    saveQueue(queueItems);
    return updated;
  }
  const drafts = loadGroupDrafts();
  const draftKey = Object.keys(drafts).find((key) => (
    key === clientBatchId || drafts[key]?.client_batch_id === clientBatchId
  ));
  if (draftKey) {
    updated = { ...drafts[draftKey], ...patch };
    drafts[draftKey] = updated;
    saveGroupDrafts(drafts);
  }
  return updated;
}

function removeLocalFile(filePath) {
  if (!filePath) return;
  try {
    wx.getFileSystemManager().unlink({ filePath });
  } catch {}
}

function setDraftError(clientBatchId, message) {
  saveQueue(loadQueue().map((item) => (
    item.client_batch_id === clientBatchId
      ? { ...item, status: "failed", error: message, updated_at: new Date().toISOString() }
      : item
  )));
}

async function processQueue(onProgress) {
  return processDraftList(loadQueue().map((item) => ({ ...item, kind: "queued" })), onProgress);
}

async function processDraftList(items, onProgress) {
  const api = require("./api");
  let uploaded = 0;
  let failed = 0;
  for (const draft of items) {
    const missing = cacheMissingFields(draft);
    if (missing.length) {
      setDraftError(draft.client_batch_id, `缺少：${missing.join("、")}`);
      failed += 1;
      continue;
    }
    try {
      const photos = draft.photos || [];
      if (!photos.length && draft.work_order_id) {
        await api.submitConstructionExceptionOrder(draft.work_order_id, draft);
      } else {
        for (let index = 0; index < photos.length; index += 1) {
          await api.uploadPhoto(draft.groupId, draft, photos[index], (progress) => {
            if (typeof onProgress === "function") {
              onProgress({ draft, photo: photos[index], index, total: photos.length, progress });
            }
          });
        }
        if (draft.work_order_id) await api.submitConstructionExceptionOrder(draft.work_order_id, draft);
      }
      photos.forEach((photo) => removeLocalFile(photo.filePath));
      removeDraft(draft.client_batch_id);
      removeGroupDraft(draft.taskId, draft.groupId);
      uploaded += 1;
    } catch (error) {
      setDraftError(draft.client_batch_id, error.message || "上传失败");
      failed += 1;
    }
  }
  return { uploaded, failed, remaining: getQueueCount() };
}

async function processAllCaches(onProgress, options = {}) {
  let readyItems = listCacheItems(options).filter((item) => item.ready && !item.stale);
  if (options.taskId) {
    readyItems = readyItems.filter((item) => String(item.taskId || "") === String(options.taskId));
  }
  return processDraftList(readyItems, onProgress);
}

module.exports = {
  uuid,
  loadQueue,
  saveQueue,
  getQueueCount,
  listCacheItems,
  getCacheSummary,
  loadGroupDraft,
  loadGroupDrafts,
  saveGroupDraft,
  removeGroupDraft,
  saveTerminalSnapshot,
  loadTerminalSnapshot,
  listTerminalSnapshots,
  getCachedGroup,
  enqueueDraft,
  removeDraft,
  removeCacheItem,
  updateCacheItem,
  removeLocalFile,
  processQueue,
  processAllCaches
};
