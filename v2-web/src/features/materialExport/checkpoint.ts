export type MaterialExportCheckpointFile = {
  fileId: string
  relativePath: string
  byteSize: number
  sha256: string
}

export type MaterialExportCheckpoint = {
  jobId: string
  manifestSha256: string
  directoryHandle: FileSystemDirectoryHandle
  completed: Record<string, MaterialExportCheckpointFile>
  updatedAt: string
}

const memoryStore = new Map<string, MaterialExportCheckpoint>()
const DB_NAME = 'module-manager-material-export'
const STORE_NAME = 'checkpoints'

function openDatabase(): Promise<IDBDatabase | null> {
  if (typeof indexedDB === 'undefined') return Promise.resolve(null)
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1)
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE_NAME)) request.result.createObjectStore(STORE_NAME, { keyPath: 'jobId' })
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

export async function loadCheckpoint(jobId: string, manifestSha256?: string): Promise<MaterialExportCheckpoint | null> {
  const db = await openDatabase()
  let result: MaterialExportCheckpoint | undefined
  if (!db) result = memoryStore.get(jobId)
  else {
    result = await new Promise((resolve, reject) => {
      const request = db.transaction(STORE_NAME, 'readonly').objectStore(STORE_NAME).get(jobId)
      request.onsuccess = () => resolve(request.result as MaterialExportCheckpoint | undefined)
      request.onerror = () => reject(request.error)
    })
    db.close()
  }
  if (!result || (manifestSha256 && result.manifestSha256 !== manifestSha256)) return null
  return result
}

export async function saveCheckpoint(checkpoint: MaterialExportCheckpoint): Promise<void> {
  const value = { ...checkpoint, updatedAt: new Date().toISOString() }
  const db = await openDatabase()
  if (!db) {
    memoryStore.set(value.jobId, value)
    return
  }
  await new Promise<void>((resolve, reject) => {
    const request = db.transaction(STORE_NAME, 'readwrite').objectStore(STORE_NAME).put(value)
    request.onsuccess = () => resolve()
    request.onerror = () => reject(request.error)
  })
  db.close()
}

export async function removeCheckpoint(jobId: string): Promise<void> {
  memoryStore.delete(jobId)
  const db = await openDatabase()
  if (!db) return
  await new Promise<void>((resolve, reject) => {
    const request = db.transaction(STORE_NAME, 'readwrite').objectStore(STORE_NAME).delete(jobId)
    request.onsuccess = () => resolve()
    request.onerror = () => reject(request.error)
  })
  db.close()
}
