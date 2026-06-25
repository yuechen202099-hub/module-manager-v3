export type ConstructionDraftIdentity = {
  groupId?: string | number
  group_id?: string | number
  meter_no?: string | number
  address?: string
  collector?: string
  work_order_id?: string | number
  photos?: unknown[]
}

export type ConstructionGroupIdentity = {
  id?: string | number
  meterNo?: string | number
  meterMatchKey?: string | number
  address?: string
}

export function isAllZeroConstructionCode(value?: string | number) {
  const normalized = String(value ?? '').replace(/\D/g, '')
  return normalized.length > 0 && /^0+$/.test(normalized)
}

export function isPlaceholderConstructionAddress(value?: string) {
  return String(value || '').includes('待导入总清单地址')
}

export function isPlaceholderConstructionDraft(draft: ConstructionDraftIdentity) {
  return (
    isAllZeroConstructionCode(draft.groupId) ||
    isAllZeroConstructionCode(draft.group_id) ||
    isAllZeroConstructionCode(draft.meter_no) ||
    isPlaceholderConstructionAddress(draft.address)
  )
}

export function isEmptyPlaceholderConstructionDraft(draft: ConstructionDraftIdentity) {
  const noPhotos = !(draft.photos || []).length
  const noCollector = !String(draft.collector || '').trim()
  const noWorkOrder = !String(draft.work_order_id || '').trim()
  return isPlaceholderConstructionDraft(draft) && noPhotos && noCollector && noWorkOrder
}

export function constructionDraftUploadBlockReason(draft: ConstructionDraftIdentity) {
  if (!isPlaceholderConstructionDraft(draft)) return ''
  return '无工单：扫码结果不在当前施工工单中（00000000 占位资料组不能上传）'
}

export function isUploadableConstructionDraft(draft: ConstructionDraftIdentity) {
  return !constructionDraftUploadBlockReason(draft)
}

export function isPlaceholderConstructionGroup(group: ConstructionGroupIdentity) {
  return (
    isAllZeroConstructionCode(group.id) ||
    isAllZeroConstructionCode(group.meterNo) ||
    isAllZeroConstructionCode(group.meterMatchKey) ||
    isPlaceholderConstructionAddress(group.address)
  )
}

export function constructionGroupOpenBlockReason(group: ConstructionGroupIdentity) {
  if (!isPlaceholderConstructionGroup(group)) return ''
  return '无工单：扫码结果不在当前施工工单中'
}

export function isCollectableConstructionGroup(group: ConstructionGroupIdentity) {
  return !constructionGroupOpenBlockReason(group)
}
