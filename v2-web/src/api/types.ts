export type ApiEnvelope<T> = {
  data: T
  error: null
  request_id: string
}

export type ApiErrorEnvelope = {
  data: null
  error: {
    code: string
    message: string
    details?: Record<string, unknown>
  }
  request_id: string
}

export type UserRole = 'admin' | 'reviewer' | 'constructor'

export type UserAccount = {
  username: string
  name: string
  roles: UserRole[]
  teamId: string
  status: string
  home?: string
  lastLoginAt?: string
}

export type CurrentUser = {
  id: string
  username?: string
  name: string
  role: UserRole
  roles?: UserRole[]
  teamId?: string
}

export type AuthDemoAccount = {
  label: string
  username: string
  password?: string
  role: UserRole
  home?: string
  team_id?: string
}

export type AuthConfig = {
  demo_auth_enabled: boolean
  demo_accounts: AuthDemoAccount[]
  account_config_enabled?: boolean
}

export type Project = {
  id: string
  name: string
  status: 'active' | 'archived'
  totalGroups: number
  completedGroups: number
  exceptionGroups: number
  updatedAt: string
}

export type TaskStatus =
  | 'pending'
  | 'unreviewed'
  | 'in_review'
  | 'complete'
  | 'approved'
  | 'exception'
  | 'incomplete'
  | 'locked'
  | 'released'
  | 'published'

export type ReviewTask = {
  id: string
  projectId: string
  name: string
  stage: string
  status: TaskStatus
  terminal?: string
  totalGroups: number
  claimedGroups: number
  completedGroups: number
  ownerName?: string
  claimedBy?: string
  canClaim?: boolean
  hasScanInfo?: boolean
  renovationCount?: number
  uploadedCount?: number
  reviewedCount?: number
  unreviewedCount?: number
  reviewRate?: number
  constructionEnabled?: boolean
  constructionClaimedBy?: string
  assignedConstructor?: string
  constructionUploadedCount?: number
  constructionUnbuiltCount?: number
  constructionExceptionCount?: number
}

export type MaterialGroup = {
  id: string
  taskId: string | number
  address: string
  meterNo: string
  meterMatchKey?: string
  terminal: string
  status: TaskStatus
  photoCount: number
  reviewer?: string
  reviewNote?: string
  exceptionNote?: string
  exceptionReasons?: string[]
  hasArchiveBlocker?: boolean
  constructionCollector?: string
  constructionModuleAssetNo?: string
  constructionStatus?: string
  exceptionOrderId?: string
  photos?: ReviewPhoto[]
}

export type ReviewPhoto = {
  id: string
  url: string
  imageUrl?: string
  sourceUrl?: string
  previewUrl?: string
  thumbnailUrl?: string
  deliveryCacheUrl?: string
  storageType?: string
  storageKey?: string
  name: string
  status: 'unclassified' | 'valid' | 'invalid' | 'exception'
  category?: string
  categoryLabel?: string
  archiveStatus?: string
  archiveFilename?: string
  barcode?: string
  collector?: string
  moduleAssetNo?: string
  creator?: string
}

export type ConstructionPhotoSlot = {
  key: string
  label: string
  required: boolean
}

export type ConstructionUploadPhoto = {
  slot: string
  file: File
  clientPhotoId: string
}

export type ConstructionUploadPayload = {
  actor: string
  clientBatchId: string
  collector: string
  moduleAssetNo: string
  photos: ConstructionUploadPhoto[]
}

export type ConstructionExceptionOrder = {
  id: string
  taskId?: string | number
  groupId: string
  terminal: string
  meterNo: string
  address: string
  status: string
  category: string
  note: string
  assignedTo?: string
  group?: MaterialGroup
}

export type ProjectSummary = {
  totalCatalogRows: number
  groups: number
  scannedGroups: number
  approvedGroups: number
  reviewedGroups: number
  unreviewedGroups: number
  exceptionGroups: number
  incompleteGroups: number
  unconstructedGroups: number
  photoRowsLinked: number
  scanUnmatched: number
  reviewProgress: number
  installerDistribution: Array<{ installer: string; groupCount: number; share: number }>
}

export type ImportJob = {
  jobId: string
  status: string
  progress?: Record<string, unknown>
  result?: Record<string, unknown>
  error?: string
}

export type UnmatchedRecord = {
  unmatchedId: string
  barcode: string
  meterNo: string
  meterMatchKey: string
  terminal: string
  address: string
  collector: string
  moduleAssetNo: string
  creator: string
  photoCount: number
  recordType?: string
}
