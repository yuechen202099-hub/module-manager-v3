import { computed, ref, shallowRef, type ComputedRef, type Ref } from 'vue'

import {
  cancelReleaseMaterialExport,
  fetchMaterialExportSummaries,
  preflightMaterialExport,
  reserveMaterialExport,
  updateMaterialExportSetting,
} from '../../api/services'
import type { MaterialExportJobDetail, MaterialExportTerminalSummary, ReviewTask } from '../../api/types'
import { removeCheckpoint } from './checkpoint'
import { runMaterialExport, type MaterialExportRunProgress } from './runner'

const LAST_JOB_KEY = 'module-manager-material-export-last-job'

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

export function useMaterialExport(tasks: Ref<ReviewTask[]>, isAdmin: ComputedRef<boolean>) {
  const summaries = ref<Record<string, MaterialExportTerminalSummary>>({})
  const selectedTaskIds = ref(new Set<string>())
  const running = ref(false)
  const paused = ref(false)
  const pauseRequested = ref(false)
  const progress = ref<MaterialExportRunProgress>({ completedFiles: 0, totalFiles: 0, completedBytes: 0, totalBytes: 0 })
  const currentJob = ref<MaterialExportJobDetail | null>(null)
  const currentDirectory = shallowRef<FileSystemDirectoryHandle | null>(null)
  const error = ref('')
  let startedAt = 0

  const selectedCount = computed(() => selectedTaskIds.value.size)
  const progressText = computed(() => {
    const state = progress.value
    if (!running.value && !paused.value && !state.totalFiles) return ''
    const elapsedSeconds = Math.max(0.001, (Date.now() - startedAt) / 1000)
    const rate = state.completedBytes / elapsedSeconds
    const remainingBytes = Math.max(0, state.totalBytes - state.completedBytes)
    const eta = rate > 0 && remainingBytes > 0 ? `，预计剩余 ${Math.ceil(remainingBytes / rate)} 秒` : ''
    const prefix = paused.value ? '已暂停' : running.value ? '导出中' : '已完成'
    return `${prefix} ${state.completedFiles}/${state.totalFiles} 个文件，${formatBytes(state.completedBytes)}/${formatBytes(state.totalBytes)}${eta}`
  })

  async function loadSummaries(source: ReviewTask[] = tasks.value) {
    if (!isAdmin.value || !source.length) return
    const next: Record<string, MaterialExportTerminalSummary> = {}
    for (let offset = 0; offset < source.length; offset += 500) {
      const rows = await fetchMaterialExportSummaries(source.slice(offset, offset + 500).map((task) => task.id))
      for (const row of rows) next[row.taskId] = row
    }
    summaries.value = next
  }

  function isSelected(taskId: string) {
    return selectedTaskIds.value.has(taskId)
  }

  function setSelected(taskId: string, selected: boolean) {
    const next = new Set(selectedTaskIds.value)
    if (selected) next.add(taskId)
    else next.delete(taskId)
    selectedTaskIds.value = next
  }

  function selectCurrent(source: ReviewTask[], selected: boolean) {
    const next = new Set(selectedTaskIds.value)
    for (const task of source) {
      const constructed = Number(task.constructionUploadedCount ?? task.uploadedCount ?? 0) > 0
      if (!constructed) continue
      if (selected) next.add(task.id)
      else next.delete(task.id)
    }
    selectedTaskIds.value = next
  }

  async function updateCount(taskId: string, count: number) {
    const row = await updateMaterialExportSetting(taskId, Math.max(0, Math.trunc(count || 0)))
    summaries.value = { ...summaries.value, [taskId]: row }
  }

  async function runCurrentJob() {
    const job = currentJob.value
    const root = currentDirectory.value
    if (!job || !root) throw new Error('没有可继续的导出任务或本地文件夹')
    pauseRequested.value = false
    paused.value = false
    running.value = true
    startedAt = Date.now()
    const controller = new AbortController()
    try {
      const result = await runMaterialExport(
        job,
        root,
        controller.signal,
        (value) => { progress.value = value },
        () => pauseRequested.value,
      )
      paused.value = result === 'paused'
      if (result === 'completed') {
        localStorage.removeItem(LAST_JOB_KEY)
        await removeCheckpoint(job.id)
        await loadSummaries()
      }
      return result
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '导出失败'
      throw cause
    } finally {
      running.value = false
    }
  }

  async function start(taskIds = [...selectedTaskIds.value]) {
    if (!taskIds.length) throw new Error('请先勾选至少一个终端')
    if (!window.showDirectoryPicker) throw new Error('当前浏览器不支持文件夹直写，请使用最新版 Windows Chrome 或 Edge')
    error.value = ''
    const root = await window.showDirectoryPicker({ mode: 'readwrite' })
    const preflight = await preflightMaterialExport(taskIds)
    const blocked = Object.values(preflight.terminals).filter((row) => !row.canExport)
    if (blocked.length) {
      const details = blocked.flatMap((row) => row.issues.map((issue) => `${row.terminalCode}：${issue.message}`))
      throw new Error(details.join('；'))
    }
    if (preflight.totalPoolShortage) {
      const gaps = Object.values(preflight.terminals)
        .filter((row) => row.poolShortage > 0)
        .map((row) => `${row.terminalCode} 缺少 ${row.poolShortage} 个`)
      throw new Error(`采集器池不足，合计缺少 ${preflight.totalPoolShortage} 个${gaps.length ? `；${gaps.join('；')}` : ''}`)
    }
    const job = await reserveMaterialExport(taskIds, preflight.fingerprint)
    currentJob.value = job
    currentDirectory.value = root
    localStorage.setItem(LAST_JOB_KEY, job.id)
    progress.value = { completedFiles: 0, totalFiles: 0, completedBytes: 0, totalBytes: 0 }
    return runCurrentJob()
  }

  function pause() {
    if (running.value) pauseRequested.value = true
  }

  async function resume() {
    if (running.value) return
    return runCurrentJob()
  }

  async function release(reason: string) {
    const job = currentJob.value
    if (!job) throw new Error('没有可释放的导出任务')
    const terminalIds = job.terminals
      .filter((terminal) => !['completed', 'cancelled_released'].includes(terminal.status))
      .map((terminal) => terminal.id)
    if (!terminalIds.length) throw new Error('已完成的终端不能释放采集器占用')
    await cancelReleaseMaterialExport(job.id, terminalIds, reason)
    await removeCheckpoint(job.id)
    localStorage.removeItem(LAST_JOB_KEY)
    currentJob.value = null
    currentDirectory.value = null
    paused.value = false
    progress.value = { completedFiles: 0, totalFiles: 0, completedBytes: 0, totalBytes: 0 }
  }

  return {
    summaries,
    selectedTaskIds,
    selectedCount,
    running,
    paused,
    progress,
    progressText,
    currentJob,
    error,
    loadSummaries,
    isSelected,
    setSelected,
    selectCurrent,
    updateCount,
    start,
    pause,
    resume,
    release,
  }
}
