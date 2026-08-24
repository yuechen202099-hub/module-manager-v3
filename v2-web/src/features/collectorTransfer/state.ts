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
      description: '同号采集器照片可复用，不加入替换池。',
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
