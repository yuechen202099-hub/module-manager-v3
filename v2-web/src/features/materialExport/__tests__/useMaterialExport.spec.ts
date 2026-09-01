import { computed, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { MaterialExportJobDetail, MaterialExportPreflight, ReviewTask } from '../../../api/types'

const apiMock = vi.hoisted(() => ({
  cancelReleaseMaterialExport: vi.fn(),
  fetchMaterialExportJob: vi.fn(),
  fetchMaterialExportSummaries: vi.fn(),
  preflightMaterialExport: vi.fn(),
  reserveMaterialExport: vi.fn(),
  updateMaterialExportSetting: vi.fn(),
}))

const runnerMock = vi.hoisted(() => ({
  runMaterialExport: vi.fn(),
}))

vi.mock('../../../api/services', () => apiMock)
vi.mock('../runner', () => runnerMock)

import { useMaterialExport } from '../useMaterialExport'

const SHA = 'a'.repeat(64)

function reviewTask(id = 'task-1'): ReviewTask {
  return {
    id,
    projectId: 'project-a',
    name: id,
    stage: '施工',
    status: 'pending',
    terminal: id === 'task-1' ? 'T-1' : 'T-2',
    totalGroups: 2,
    claimedGroups: 0,
    completedGroups: 0,
    renovationCount: 2,
    constructionUploadedCount: 1,
  }
}

function preflight(overrides: Partial<MaterialExportPreflight> = {}): MaterialExportPreflight {
  return {
    projectId: 'project-a',
    fingerprint: SHA,
    sourceGroupIds: ['g-1'],
    totalPoolShortage: 0,
    terminals: {
      'task-1': {
        taskId: 'task-1',
        terminalCode: 'T-1',
        constructedMeterCount: 1,
        sourceCollectorCount: 1,
        requestedCollectorCount: 1,
        finalCollectorCount: 1,
        sourceRevision: SHA,
        canExport: true,
        issues: [],
        poolShortage: 0,
      },
    },
    ...overrides,
  }
}

function job(): MaterialExportJobDetail {
  return {
    id: 'job-1',
    status: 'reserved',
    manifestSha256: SHA,
    terminals: [{
      id: 'terminal-1',
      taskId: 'task-1',
      terminalCode: 'T-1',
      status: 'reserved',
      meterRows: [],
      supplementRows: [],
      files: [],
    }],
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

describe('useMaterialExport', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    apiMock.preflightMaterialExport.mockResolvedValue(preflight())
    apiMock.reserveMaterialExport.mockResolvedValue(job())
    apiMock.cancelReleaseMaterialExport.mockResolvedValue(undefined)
    apiMock.fetchMaterialExportSummaries.mockResolvedValue([])
    vi.stubGlobal('showDirectoryPicker', vi.fn(async () => ({} as FileSystemDirectoryHandle)))
  })

  it('reports the total and every terminal pool gap before creating a job', async () => {
    apiMock.preflightMaterialExport.mockResolvedValue(preflight({
      totalPoolShortage: 2,
      terminals: {
        'task-1': { ...preflight().terminals['task-1'], poolShortage: 1 },
        'task-2': { ...preflight().terminals['task-1'], taskId: 'task-2', terminalCode: 'T-2', poolShortage: 1 },
      },
    }))
    const subject = useMaterialExport(ref([reviewTask(), reviewTask('task-2')]), computed(() => true))

    await expect(subject.start(['task-1', 'task-2'])).rejects.toThrow('合计缺少 2 个；T-1 缺少 1 个；T-2 缺少 1 个')
    expect(apiMock.reserveMaterialExport).not.toHaveBeenCalled()
  })

  it('pauses between files and resumes the same immutable job and folder', async () => {
    const firstRun = deferred<'paused' | 'completed'>()
    let shouldPause: (() => boolean) | undefined
    runnerMock.runMaterialExport.mockImplementationOnce(async (_job, _root, _signal, _progress, pauseCheck) => {
      shouldPause = pauseCheck
      return firstRun.promise
    })
    const subject = useMaterialExport(ref([reviewTask()]), computed(() => true))

    const startPromise = subject.start(['task-1'])
    await vi.waitFor(() => expect(runnerMock.runMaterialExport).toHaveBeenCalledTimes(1))
    subject.pause()
    expect(shouldPause?.()).toBe(true)
    firstRun.resolve('paused')
    await startPromise
    expect(subject.paused.value).toBe(true)

    runnerMock.runMaterialExport.mockResolvedValueOnce('completed')
    await subject.resume()
    expect(runnerMock.runMaterialExport).toHaveBeenLastCalledWith(
      expect.objectContaining({ id: 'job-1' }),
      expect.anything(),
      expect.any(AbortSignal),
      expect.any(Function),
      expect.any(Function),
    )
    expect(subject.paused.value).toBe(false)
  })

  it('releases only incomplete terminal reservations and clears the resume state', async () => {
    runnerMock.runMaterialExport.mockResolvedValue('paused')
    const subject = useMaterialExport(ref([reviewTask()]), computed(() => true))
    await subject.start(['task-1'])

    await subject.release('管理员取消本次导出')

    expect(apiMock.cancelReleaseMaterialExport).toHaveBeenCalledWith('job-1', ['terminal-1'], '管理员取消本次导出')
    expect(subject.currentJob.value).toBeNull()
    expect(localStorage.getItem('module-manager-material-export-last-job')).toBeNull()
  })
})
