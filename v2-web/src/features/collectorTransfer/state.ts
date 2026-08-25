import type { CollectorInventoryDecision } from '@/api/types'

export type CollectorDecision = CollectorInventoryDecision['decision']

export type InventoryDecisionInput = {
  decision: CollectorDecision
  requiresPhoto: boolean
  addToPool: boolean
}

export type InventoryResultPresentation = {
  tone: 'success' | 'warning' | 'danger'
  title: string
  description: string
  primaryAction: string
}

type GlobalCandidateLabelInput = {
  terminal_code: string
  project_name: string
  installation_address: string
  needs_disambiguation: boolean
}

type CompletionCollectorInput = {
  physical_state: 'present' | 'missing' | 'replaced'
  final_collector_no: string | null
  collector_barcode: string | null
  photo: unknown | null
}

export function candidateLabel(candidate: GlobalCandidateLabelInput) {
  const parts = [candidate.terminal_code]
  if (candidate.needs_disambiguation) parts.push(candidate.project_name)
  parts.push(candidate.installation_address)
  return parts.filter(Boolean).join(' · ')
}

export function completionBlockers(item: CompletionCollectorInput) {
  if (item.physical_state === 'missing') return ['该采集器没有实物，需先完成替换']
  if (!item.final_collector_no || !item.collector_barcode) return ['缺少最终采集器号']
  if (item.physical_state === 'replaced' && !item.photo) return ['替换采集器照片缺失']
  return []
}

export function canReplaceMissing(isAdmin: boolean, available: number, missing: number) {
  return isAdmin && missing > 0 && available >= missing
}

export function isCurrentRequest(sequence: number, currentSequence: number) {
  return sequence === currentSequence
}

export function inventoryResultPresentation(input: InventoryDecisionInput): InventoryResultPresentation {
  if (input.decision === 'existing_available') {
    return {
      tone: 'success',
      title: '已在替换池',
      description: '该采集器已登记且照片有效，无需重复拍照。',
      primaryAction: '继续扫码',
    }
  }
  if (input.decision === 'existing_reserved') {
    return {
      tone: 'warning',
      title: '已被占用',
      description: '该采集器已被任务预留，禁止重复使用。',
      primaryAction: '继续扫码',
    }
  }
  if (input.decision === 'existing_used') {
    return {
      tone: 'danger',
      title: '已使用',
      description: '该采集器已经使用，禁止再次加入替换池。',
      primaryAction: '继续扫码',
    }
  }
  if (!input.requiresPhoto && input.addToPool) {
    return {
      tone: 'success',
      title: '已加入替换池',
      description: '照片已保存，采集器已作为一次性替换资源登记。',
      primaryAction: '继续扫码',
    }
  }
  if (!input.requiresPhoto && !input.addToPool) {
    return {
      tone: 'success',
      title: '无需拍照，已确认',
      description: '已确认手上有同号实物，无需在网站拍照，也不加入替换池。',
      primaryAction: '继续扫码',
    }
  }
  if (!input.addToPool) {
    return {
      tone: 'warning',
      title: '需要拍照',
      description: '同号但缺照片，补拍后直接匹配，不入池。',
      primaryAction: '立即拍照',
    }
  }
  return {
    tone: 'warning',
    title: '需要拍照',
    description: '没有同号，补图后加入替换池。',
    primaryAction: '立即拍照',
  }
}
