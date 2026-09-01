import { describe, expect, it } from 'vitest'
import { loadCheckpoint, saveCheckpoint } from '../checkpoint'

describe('material export checkpoints', () => {
  it('rejects a checkpoint from a different immutable manifest', async () => {
    const directoryHandle = {} as FileSystemDirectoryHandle
    await saveCheckpoint({
      jobId: 'job-1',
      manifestSha256: 'a'.repeat(64),
      directoryHandle,
      completed: {},
      updatedAt: '',
    })
    expect(await loadCheckpoint('job-1', 'b'.repeat(64))).toBeNull()
    expect((await loadCheckpoint('job-1', 'a'.repeat(64)))?.directoryHandle).toBe(directoryHandle)
  })
})
