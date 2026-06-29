const { request } = require('../utils/api')

function fetchGroups(taskId, filter) {
  return request(`/miniprogram/tasks/${encodeURIComponent(taskId)}/groups?filter=${encodeURIComponent(filter || 'todo')}`)
    .then((data) => data.items || [])
}

function matchesGroup(group, keyword) {
  const clean = String(keyword || '').trim().toLowerCase()
  if (!clean) return true
  return [
    group.meter_no,
    group.address,
    group.collector,
    group.module_asset_no,
    group.construction_collector,
    group.construction_module_asset_no
  ].some((value) => String(value || '').toLowerCase().includes(clean))
}

function groupKey(group) {
  return String((group && (group.id || group.group_id || group.meter_no)) || '')
}

function draftGroupKey(draft) {
  return String((draft && (draft.groupId || (draft.group && (draft.group.id || draft.group.group_id || draft.group.meter_no)))) || '')
}

function filterRemoteGroupsByLocalDrafts(groups, localDrafts, activeFilter) {
  if (activeFilter !== 'todo') return groups || []
  const draftKeys = new Set((localDrafts || []).map(draftGroupKey).filter(Boolean))
  if (!draftKeys.size) return groups || []
  return (groups || []).filter((group) => !draftKeys.has(groupKey(group)))
}

function findGroupByScan(groups, value) {
  const clean = String(value || '').trim()
  if (!clean) return null
  return groups.find((group) => {
    return [
      group.meter_no,
      group.collector,
      group.module_asset_no,
      group.construction_collector,
      group.construction_module_asset_no
    ].some((item) => String(item || '').trim() === clean)
  }) || null
}

module.exports = {
  fetchGroups,
  matchesGroup,
  filterRemoteGroupsByLocalDrafts,
  findGroupByScan
}
