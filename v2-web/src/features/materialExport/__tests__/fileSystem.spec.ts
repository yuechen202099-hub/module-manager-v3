import { describe, expect, it, vi } from 'vitest'
import { saveResponseToDirectory } from '../fileSystem'

function rootHandle() {
  const write = vi.fn(async () => undefined)
  const writable = { write, close: vi.fn(async () => undefined), abort: vi.fn(async () => undefined) }
  const fileHandle = { createWritable: vi.fn(async () => writable) }
  const directory: any = {
    getDirectoryHandle: vi.fn(async () => directory),
    getFileHandle: vi.fn(async () => fileHandle),
  }
  return { directory: directory as FileSystemDirectoryHandle, write }
}

describe('material export filesystem', () => {
  it('writes streamed chunks and hashes incrementally', async () => {
    const { directory, write } = rootHandle()
    const chunks = [new Uint8Array(65536), new Uint8Array(65536), new Uint8Array(7)]
    const response = new Response(new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(chunk)
        controller.close()
      },
    }))
    const result = await saveResponseToDirectory(directory, 'T-1/MOD-1/改造后.jpg', response)
    expect(result.byteSize).toBe(131079)
    expect(result.sha256).toMatch(/^[0-9a-f]{64}$/)
    expect(write).toHaveBeenCalledTimes(3)
  })

  it('rejects unsafe manifest paths', async () => {
    const { directory } = rootHandle()
    await expect(saveResponseToDirectory(directory, '../escape.jpg', new Response('x'))).rejects.toThrow('非法导出路径')
  })
})
