import {
  acknowledgeMaterialExportFile,
  completeMaterialExportTerminal,
  fetchMaterialExportFile,
  heartbeatMaterialExport,
  pauseMaterialExport,
  resumeMaterialExport,
} from '../../api/services'
import type {
  MaterialExportFile,
  MaterialExportJobDetail,
  MaterialExportTerminalManifest,
  MaterialExportWrittenFile,
} from '../../api/types'
import { loadCheckpoint, saveCheckpoint, type MaterialExportCheckpoint } from './checkpoint'
import { saveResponseToDirectory, verifyLocalFile, writeBytesToDirectory } from './fileSystem'
import { buildSupplementWorkbook, buildTerminalWorkbook } from './workbooks'

export type MaterialExportRunProgress = {
  completedFiles: number
  totalFiles: number
  completedBytes: number
  totalBytes: number
}

export function startLeaseHeartbeat(jobId: string, token: string): { stop: () => void } {
  const timer = window.setInterval(() => void heartbeatMaterialExport(jobId, token), 30_000)
  return { stop: () => window.clearInterval(timer) }
}

export async function checkpointMatches(
  root: FileSystemDirectoryHandle,
  job: MaterialExportJobDetail,
  file: MaterialExportFile,
): Promise<boolean> {
  return Boolean(await verifiedCheckpointFile(root, job, file))
}

async function verifiedCheckpointFile(
  root: FileSystemDirectoryHandle,
  job: MaterialExportJobDetail,
  file: MaterialExportFile,
): Promise<MaterialExportWrittenFile | null> {
  const checkpoint = await loadCheckpoint(job.id, job.manifestSha256)
  const saved = checkpoint?.completed[file.id]
  if (!saved) return null
  if (!await verifyLocalFile(root, saved.relativePath, saved.byteSize, saved.sha256)) return null
  return { byteSize: saved.byteSize, sha256: saved.sha256 }
}

async function recordCheckpoint(
  root: FileSystemDirectoryHandle,
  job: MaterialExportJobDetail,
  file: MaterialExportFile,
  written: MaterialExportWrittenFile,
): Promise<void> {
  const current = await loadCheckpoint(job.id, job.manifestSha256)
  const checkpoint: MaterialExportCheckpoint = current || {
    jobId: job.id,
    manifestSha256: job.manifestSha256,
    directoryHandle: root,
    completed: {},
    updatedAt: '',
  }
  checkpoint.completed[file.id] = {
    fileId: file.id,
    relativePath: file.relativePath,
    byteSize: written.byteSize,
    sha256: written.sha256,
  }
  await saveCheckpoint(checkpoint)
}

async function writeClientWorkbook(
  root: FileSystemDirectoryHandle,
  job: MaterialExportJobDetail,
  file: MaterialExportFile,
  bytes: Uint8Array,
): Promise<MaterialExportWrittenFile> {
  const existing = await verifiedCheckpointFile(root, job, file)
  if (existing) return existing
  const written = await writeBytesToDirectory(root, file.relativePath, bytes)
  await acknowledgeMaterialExportFile(job.id, file.id, written)
  await recordCheckpoint(root, job, file, written)
  return written
}

export async function writeAndAcknowledgeWorkbooks(
  root: FileSystemDirectoryHandle,
  job: MaterialExportJobDetail,
  terminal: MaterialExportTerminalManifest,
): Promise<MaterialExportWrittenFile[]> {
  const written: MaterialExportWrittenFile[] = []
  const terminalFile = terminal.files.find((file) => file.sourceKind === 'client_workbook' && file.relativePath.endsWith('/终端资料.xlsx'))
  if (!terminalFile) throw new Error(`终端 ${terminal.terminalCode} 缺少终端资料表清单`)
  written.push(await writeClientWorkbook(root, job, terminalFile, await buildTerminalWorkbook(terminal.meterRows)))
  const supplement = await buildSupplementWorkbook(terminal.supplementRows)
  const supplementFile = terminal.files.find((file) => file.sourceKind === 'client_workbook' && file.relativePath.endsWith('/补充采集器.xlsx'))
  if (supplement && supplementFile) written.push(await writeClientWorkbook(root, job, supplementFile, supplement))
  return written
}

export async function runMaterialExport(
  job: MaterialExportJobDetail,
  root: FileSystemDirectoryHandle,
  signal: AbortSignal,
  onProgress?: (progress: MaterialExportRunProgress) => void,
  shouldPause: () => boolean = () => false,
): Promise<'completed' | 'paused'> {
  const lease = await resumeMaterialExport(job.id)
  const heartbeat = startLeaseHeartbeat(job.id, lease.ownerToken)
  const totalFiles = job.terminals.reduce((sum, terminal) => sum + terminal.files.length, 0)
  let totalBytes = job.terminals.reduce(
    (sum, terminal) => sum + terminal.files.reduce((fileSum, file) => fileSum + Number(file.byteSize || 0), 0),
    0,
  )
  let completedFiles = 0
  let completedBytes = 0
  const reportProgress = () => onProgress?.({ completedFiles, totalFiles, completedBytes, totalBytes })
  try {
    for (const terminal of job.terminals) {
      if (['blocked', 'needs_recheck', 'completed', 'cancelled_released'].includes(terminal.status)) continue
      for (const file of terminal.files.filter((item) => item.sourceKind !== 'client_workbook')) {
        if (signal.aborted) throw new DOMException('导出已暂停', 'AbortError')
        if (shouldPause()) {
          await pauseMaterialExport(job.id, lease.ownerToken)
          return 'paused'
        }
        const existing = await verifiedCheckpointFile(root, job, file)
        if (existing) {
          completedFiles += 1
          completedBytes += existing.byteSize
          reportProgress()
          continue
        }
        const response = await fetchMaterialExportFile(job.id, file.id, lease.ownerToken, signal)
        const written = await saveResponseToDirectory(root, file.relativePath, response)
        await acknowledgeMaterialExportFile(job.id, file.id, written)
        await recordCheckpoint(root, job, file, written)
        completedFiles += 1
        completedBytes += written.byteSize
        reportProgress()
      }
      if (signal.aborted) throw new DOMException('导出已暂停', 'AbortError')
      if (shouldPause()) {
        await pauseMaterialExport(job.id, lease.ownerToken)
        return 'paused'
      }
      const workbookFiles = terminal.files.filter((file) => file.sourceKind === 'client_workbook')
      const workbooks = await writeAndAcknowledgeWorkbooks(root, job, terminal)
      completedFiles += workbookFiles.length
      for (let index = 0; index < workbooks.length; index += 1) {
        const size = workbooks[index].byteSize
        completedBytes += size
        if (!workbookFiles[index]?.byteSize) totalBytes += size
      }
      reportProgress()
      await completeMaterialExportTerminal(job.id, terminal.id)
    }
    return 'completed'
  } catch (error) {
    try {
      await pauseMaterialExport(job.id, lease.ownerToken)
    } catch {
      // The original download error is the actionable failure. An expired or
      // already-released lease must not hide it.
    }
    throw error
  } finally {
    heartbeat.stop()
  }
}
