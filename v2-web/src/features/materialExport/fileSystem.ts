import type { MaterialExportWrittenFile } from '../../api/types'

function safePathParts(relativePath: string): string[] {
  if (!relativePath || relativePath.startsWith('/') || relativePath.includes('\\')) throw new Error('非法导出路径')
  const parts = relativePath.split('/')
  if (parts.some((part) => !part || part === '.' || part === '..' || part.includes('\0'))) throw new Error('非法导出路径')
  return parts
}

async function targetFile(root: FileSystemDirectoryHandle, relativePath: string): Promise<FileSystemFileHandle> {
  const parts = safePathParts(relativePath)
  const filename = parts.pop()!
  let directory = root
  for (const part of parts) directory = await directory.getDirectoryHandle(part, { create: true })
  return directory.getFileHandle(filename, { create: true })
}

async function createHasher() {
  const { createSHA256 } = await import('hash-wasm')
  const hasher = await createSHA256()
  hasher.init()
  return hasher
}

export async function saveResponseToDirectory(
  root: FileSystemDirectoryHandle,
  relativePath: string,
  response: Response,
): Promise<MaterialExportWrittenFile> {
  if (!response.body) throw new Error('浏览器未提供可读取的下载流')
  const handle = await targetFile(root, relativePath)
  const writable = await handle.createWritable()
  const reader = response.body.getReader()
  const hasher = await createHasher()
  let byteSize = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      if (!value) continue
      hasher.update(value)
      byteSize += value.byteLength
      await writable.write(value)
    }
    await writable.close()
    return { byteSize, sha256: hasher.digest('hex') }
  } catch (error) {
    await writable.abort(error).catch(() => undefined)
    throw error
  }
}

export async function writeBytesToDirectory(
  root: FileSystemDirectoryHandle,
  relativePath: string,
  bytes: Uint8Array,
): Promise<MaterialExportWrittenFile> {
  const handle = await targetFile(root, relativePath)
  const writable = await handle.createWritable()
  const hasher = await createHasher()
  try {
    hasher.update(bytes)
    const writableBytes = new Uint8Array(bytes.byteLength)
    writableBytes.set(bytes)
    await writable.write(writableBytes)
    await writable.close()
    return { byteSize: bytes.byteLength, sha256: hasher.digest('hex') }
  } catch (error) {
    await writable.abort(error).catch(() => undefined)
    throw error
  }
}

export async function verifyLocalFile(
  root: FileSystemDirectoryHandle,
  relativePath: string,
  expectedSize: number,
  expectedSha256: string,
): Promise<boolean> {
  try {
    const parts = safePathParts(relativePath)
    const filename = parts.pop()!
    let directory = root
    for (const part of parts) directory = await directory.getDirectoryHandle(part)
    const file = await (await directory.getFileHandle(filename)).getFile()
    if (file.size !== expectedSize) return false
    const reader = file.stream().getReader()
    const hasher = await createHasher()
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      if (value) hasher.update(value)
    }
    return hasher.digest('hex') === expectedSha256.toLowerCase()
  } catch {
    return false
  }
}
