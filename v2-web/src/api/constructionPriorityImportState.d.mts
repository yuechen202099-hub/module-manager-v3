export type ConstructionPriorityImportRequestToken = number

export interface ConstructionPriorityImportSession {
  begin(): ConstructionPriorityImportRequestToken
  capture(): ConstructionPriorityImportRequestToken
  invalidate(): void
  isCurrent(token: ConstructionPriorityImportRequestToken): boolean
}

export function createConstructionPriorityImportSession(): ConstructionPriorityImportSession
export function parseContentDispositionFilename(disposition: string, fallbackName: string): string
