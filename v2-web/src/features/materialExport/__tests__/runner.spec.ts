import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { MaterialExportJobDetail, MaterialExportTerminalManifest } from '../../../api/types'

const apiMock = vi.hoisted(() => ({
  acknowledgeMaterialExportFile: vi.fn(),
  completeMaterialExportTerminal: vi.fn(),
  fetchMaterialExportFile: vi.fn(),
  heartbeatMaterialExport: vi.fn(),
  pauseMaterialExport: vi.fn(),
  resumeMaterialExport: vi.fn(),
}))

const checkpointMock = vi.hoisted(() => ({
  loadCheckpoint: vi.fn(),
  saveCheckpoint: vi.fn(),
}))

const fileSystemMock = vi.hoisted(() => ({
  saveResponseToDirectory: vi.fn(),
  verifyLocalFile: vi.fn(),
  writeBytesToDirectory: vi.fn(),
}))

const workbookMock = vi.hoisted(() => ({
  buildSupplementWorkbook: vi.fn(),
  buildTerminalWorkbook: vi.fn(),
}))

vi.mock('../../../api/services', () => apiMock)
vi.mock('../checkpoint', () => checkpointMock)
vi.mock('../fileSystem', () => fileSystemMock)
vi.mock('../workbooks', () => workbookMock)

import { runMaterialExport } from '../runner'

const SHA = 'a'.repeat(64)

function terminal(id: string, code: string): MaterialExportTerminalManifest {
  return {
    id,
    taskId: `task-${id}`,
    terminalCode: code,
    status: 'reserved',
    meterRows: [{ meterNo: `M-${id}`, address: '安装地址', moduleNo: `MOD-${id}`, finalCollectorNo: `C-${id}` }],
    supplementRows: [],
    files: [
      {
        id: `${id}-photo`,
        relativePath: `${code}/MOD-${id}/改造后.jpg`,
        sourceKind: 'photo',
        contentType: 'image/jpeg',
        byteSize: 8,
        sha256: SHA,
        status: 'pending',
      },
      {
        id: `${id}-xlsx`,
        relativePath: `${code}/终端资料.xlsx`,
        sourceKind: 'client_workbook',
        contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        byteSize: null,
        sha256: null,
        status: 'pending',
      },
    ],
  }
}

function job(terminals = [terminal('t1', 'T-1'), terminal('t2', 'T-2')]): MaterialExportJobDetail {
  return { id: 'job-1', status: 'reserved', manifestSha256: SHA, terminals }
}

describe('material export serial runner', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    checkpointMock.loadCheckpoint.mockResolvedValue(null)
    checkpointMock.saveCheckpoint.mockResolvedValue(undefined)
    fileSystemMock.verifyLocalFile.mockResolvedValue(false)
    fileSystemMock.saveResponseToDirectory.mockResolvedValue({ byteSize: 8, sha256: SHA })
    fileSystemMock.writeBytesToDirectory.mockResolvedValue({ byteSize: 12, sha256: SHA })
    workbookMock.buildTerminalWorkbook.mockResolvedValue(new Uint8Array([1, 2, 3]))
    workbookMock.buildSupplementWorkbook.mockResolvedValue(null)
    apiMock.resumeMaterialExport.mockResolvedValue({
      scope: 'global-download',
      jobId: 'job-1',
      ownerToken: 'lease-1',
      expiresAt: '2026-09-02T00:00:00Z',
    })
    apiMock.fetchMaterialExportFile.mockImplementation(async (_jobId: string, fileId: string) => ({ fileId }) as unknown as Response)
    apiMock.acknowledgeMaterialExportFile.mockResolvedValue(undefined)
    apiMock.completeMaterialExportTerminal.mockResolvedValue(undefined)
    apiMock.pauseMaterialExport.mockResolvedValue(undefined)
    vi.spyOn(window, 'setInterval').mockReturnValue(77 as never)
    vi.spyOn(window, 'clearInterval').mockImplementation(() => undefined)
  })

  it('finishes every file in one terminal before starting the next terminal', async () => {
    const order: string[] = []
    apiMock.fetchMaterialExportFile.mockImplementation(async (_jobId: string, fileId: string) => {
      order.push(`file:${fileId}`)
      return { fileId } as unknown as Response
    })
    apiMock.acknowledgeMaterialExportFile.mockImplementation(async (_jobId: string, fileId: string) => {
      order.push(`ack:${fileId}`)
    })
    fileSystemMock.writeBytesToDirectory.mockImplementation(async (_root: unknown, path: string) => {
      order.push(`workbook:${path.split('/')[0]}`)
      return { byteSize: 12, sha256: SHA }
    })
    apiMock.completeMaterialExportTerminal.mockImplementation(async (_jobId: string, terminalId: string) => {
      order.push(`complete:${terminalId}`)
    })

    const result = await runMaterialExport(job(), {} as FileSystemDirectoryHandle, new AbortController().signal)

    expect(result).toBe('completed')
    expect(order).toEqual([
      'file:t1-photo',
      'ack:t1-photo',
      'workbook:T-1',
      'ack:t1-xlsx',
      'complete:t1',
      'file:t2-photo',
      'ack:t2-photo',
      'workbook:T-2',
      'ack:t2-xlsx',
      'complete:t2',
    ])
  })

  it('does not download a checkpoint file after its local hash is verified', async () => {
    checkpointMock.loadCheckpoint.mockResolvedValue({
      jobId: 'job-1',
      manifestSha256: SHA,
      directoryHandle: {},
      completed: {
        't1-photo': { fileId: 't1-photo', relativePath: 'T-1/MOD-t1/改造后.jpg', byteSize: 8, sha256: SHA },
      },
      updatedAt: '2026-09-02T00:00:00Z',
    })
    fileSystemMock.verifyLocalFile.mockResolvedValue(true)

    await runMaterialExport(job([terminal('t1', 'T-1')]), {} as FileSystemDirectoryHandle, new AbortController().signal)

    expect(apiMock.fetchMaterialExportFile).not.toHaveBeenCalled()
    expect(apiMock.completeMaterialExportTerminal).toHaveBeenCalledWith('job-1', 't1')
  })

  it('reports downloaded bytes as well as completed file count', async () => {
    const progress: unknown[] = []

    await runMaterialExport(
      job([terminal('t1', 'T-1')]),
      {} as FileSystemDirectoryHandle,
      new AbortController().signal,
      (value) => progress.push(value),
    )

    expect(progress.at(-1)).toEqual({ completedFiles: 2, totalFiles: 2, completedBytes: 20, totalBytes: 20 })
  })

  it('honors a manual pause only between files and releases the lease', async () => {
    let pauseRequested = false
    fileSystemMock.saveResponseToDirectory.mockImplementation(async () => {
      pauseRequested = true
      return { byteSize: 8, sha256: SHA }
    })

    const result = await runMaterialExport(
      job(),
      {} as FileSystemDirectoryHandle,
      new AbortController().signal,
      undefined,
      () => pauseRequested,
    )

    expect(result).toBe('paused')
    expect(apiMock.fetchMaterialExportFile).toHaveBeenCalledTimes(1)
    expect(apiMock.pauseMaterialExport).toHaveBeenCalledWith('job-1', 'lease-1')
    expect(window.clearInterval).toHaveBeenCalledWith(77)
  })

  it('releases the lease after a download failure and keeps the file retryable', async () => {
    apiMock.fetchMaterialExportFile.mockRejectedValue(new Error('network failed'))

    await expect(
      runMaterialExport(job([terminal('t1', 'T-1')]), {} as FileSystemDirectoryHandle, new AbortController().signal),
    ).rejects.toThrow('network failed')

    expect(apiMock.pauseMaterialExport).toHaveBeenCalledWith('job-1', 'lease-1')
    expect(apiMock.acknowledgeMaterialExportFile).not.toHaveBeenCalled()
    expect(window.clearInterval).toHaveBeenCalledWith(77)
  })
})
