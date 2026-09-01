import type { ReviewTask } from '../../api/types'

export function constructionProgressPercent(task: ReviewTask): number {
  const total = Math.max(0, Number(task.renovationCount ?? task.totalGroups ?? 0))
  const completed = Math.max(0, Number(task.constructionUploadedCount ?? task.uploadedCount ?? 0))
  return total ? Math.min(100, (completed / total) * 100) : 0
}

export function sortExportTasks(tasks: readonly ReviewTask[]): ReviewTask[] {
  return [...tasks].sort((left, right) => {
    const priority = Number(Boolean(right.constructionPriority)) - Number(Boolean(left.constructionPriority))
    if (priority) return priority
    const completion = constructionProgressPercent(right) - constructionProgressPercent(left)
    if (completion) return completion
    return String(left.terminal || left.id).localeCompare(String(right.terminal || right.id), 'zh-CN', {
      numeric: true,
    })
  })
}

export function materialExportStatusLabel(status: string): string {
  return {
    not_prechecked: '未预检',
    blocked: '资料异常',
    ready: '可导出',
    reserved: '已预留',
    downloading: '下载中',
    paused: '已暂停',
    needs_recheck: '需重新预检',
    failed: '可重试',
    completed: '已完成',
    cancelled_released: '已取消并释放',
  }[status] || status || '未开始'
}
