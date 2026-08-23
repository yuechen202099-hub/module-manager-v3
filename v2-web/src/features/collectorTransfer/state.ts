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

export function inventoryResultPresentation(input: InventoryDecisionInput): InventoryResultPresentation {
  if (input.decision === 'assignment_reuse') {
    return {
      tone: 'success',
      title: '已有分配',
      description: '该采集器已有分配记录，不重复入池。',
      primaryAction: '继续扫码',
    }
  }
  if (!input.requiresPhoto && !input.addToPool) {
    return {
      tone: 'success',
      title: '无需拍照，已登记',
      description: '同号采集器照片可复用，不加入替换池。',
      primaryAction: '继续扫码',
    }
  }
  if (!input.addToPool) {
    return {
      tone: 'warning',
      title: '需要补拍',
      description: '同号但缺照片，补拍后直接匹配，不入池。',
      primaryAction: '立即补拍',
    }
  }
  return {
    tone: 'warning',
    title: '需要补拍',
    description: '没有同号，补图后加入替换池。',
    primaryAction: '立即补拍',
  }
}

export type WorkbenchMode = 'install' | 'removal'

export type WorkbenchKindItem = {
  id: string
  kind: 'meter_install' | 'collector_removal'
}

export function workbenchItemsForMode<T extends WorkbenchKindItem>(items: readonly T[], mode: WorkbenchMode): T[] {
  const kind = mode === 'install' ? 'meter_install' : 'collector_removal'
  return items.filter((item) => item.kind === kind)
}

export function nextWorkbenchItemIndex(length: number, currentIndex: number, direction: -1 | 1): number {
  if (length <= 0) return 0
  return Math.max(0, Math.min(length - 1, currentIndex + direction))
}
