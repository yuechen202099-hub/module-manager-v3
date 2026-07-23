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

export type UserRole = 'admin' | 'constructor'

export type BarcodeType = 'meter' | 'module' | 'collector'
export type NormalizedRegion = { x: number; y: number; width: number; height: number }
export type RegionScanRequest = { barcodeType: BarcodeType; region: NormalizedRegion }
export type RegionScanResult = {
  barcodeType: BarcodeType
  values: string[]
  normalizedValues: string[]
  method: 'barcode' | 'ocr' | 'none'
  region: NormalizedRegion
}

export type UserAccount = {
  username: string
  name: string
  roles: UserRole[]
  teamId: string
  status: string
  home?: string
  lastLoginAt?: string
  lastLoginIp?: string
  lastLoginDevice?: string
  loginHistory?: UserLoginHistoryItem[]
}

export type UserLoginHistoryItem = {
  at: string
  ip: string
  device: string
  ipCommonUser?: string
  ipCommonUserName?: string
  ipCommonUserCount?: number
  ipLoginCount?: number
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
  address?: string
  addressSearchText?: string
  meterSearchText?: string
  totalGroups: number
  claimedGroups: number
  completedGroups: number
  ownerName?: string
  claimedBy?: string
  claimedByName?: string
  canClaim?: boolean
  hasScanInfo?: boolean
  renovationCount?: number
  uploadedCount?: number
  reviewedCount?: number
  unreviewedCount?: number
  uploadRate?: number
  reviewRate?: number
  constructionEnabled?: boolean
  constructionPriority?: boolean
  constructionAvailable?: boolean
  reviewAvailable?: boolean
  constructionClaimedBy?: string
  constructionClaimedByName?: string
  assignedConstructor?: string
  assignedConstructorName?: string
  constructionUploadedCount?: number
  constructionUnbuiltCount?: number
  constructionExceptionCount?: number
  installerDistribution?: Array<{ installer: string; groupCount: number; share: number }>
}

export type TaskSnapshot = {
  teamId: string
  items: ReviewTask[]
  version: string
  generatedAt: string
  cache: {
    source: string
    stale: boolean
    refreshIntervalSeconds: number
  }
}

export type TaskStatusSummary = {
  version: string
  generatedAt: string
  total: number
  scanned: number
  uploaded: number
  reviewing: number
  archived: number
  claimed: number
  constructionAssigned: number
  avgUploadRate: number
  avgReviewRate: number
  renovationCount: number
  uploadedCount: number
  reviewedCount: number
  unreviewedCount: number
  totalCatalogRows: number
  groups: number
}

export type ConstructionPriorityImportStatus =
  | 'valid'
  | 'duplicate'
  | 'conflict'
  | 'unknown'
  | 'completed'
  | 'unchanged'
  | 'malformed'

export type ConstructionPriorityImportCounts = Record<ConstructionPriorityImportStatus, number>

export type ConstructionPriorityImportItem = {
  row_number: number
  terminal: string
  priority: boolean | null
  status: ConstructionPriorityImportStatus
  reason?: string
  task_id?: string | number
}

export type ConstructionPriorityImportResult = {
  counts: ConstructionPriorityImportCounts
  items: ConstructionPriorityImportItem[]
  confirmed: boolean
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
  installer?: string
  installerName?: string
  collector?: string
  moduleAssetNo?: string
  creator?: string
  creatorName?: string
  reviewerName?: string
  constructionCollector?: string
  constructionModuleAssetNo?: string
  constructionStatus?: string
  exceptionOrderId?: string
  groupBarcodeCheckStatus?: string
  groupBarcodeMatchedFields?: string[]
  groupBarcodeMissingFields?: string[]
  groupBarcodePassedCount?: number
  groupBarcodeTotalCount?: number
  groupBarcodeManualConfirmed?: boolean
  barcodeVerification?: BarcodeVerification
  barcodeVerificationStatus?: BarcodeVerificationStatus
  barcodeVerificationSource?: string
  barcodeVerificationPassedCount?: number
  barcodeVerificationTotalCount?: number
  barcodeVerificationReason?: string
  photoCategoryClassifiedCount?: number
  photoCategoryTotalCount?: number
  photoCategoryComplete?: boolean
  photoCategoryStatus?: PhotoCategoryStatus
  photos?: ReviewPhoto[]
}

export type BarcodeVerificationStatus =
  | 'not_eligible'
  | 'pending'
  | 'processing'
  | 'passed'
  | 'partial'
  | 'unreadable'
  | 'mismatch'
  | 'manual_confirmed'
  | 'failed'

export type BarcodeVerification = {
  status: BarcodeVerificationStatus
  recognitionSource: string
  invalidationReason: string
  evidenceVersion: number
  result: {
    passedCount: number
    matchedFields: string[]
    missingFields: string[]
    machineBarcodeValues: string[]
    machineQrValues: string[]
    ocrCandidates: string[]
    unmatchedMachineValues: string[]
    matchedOcrCandidates: string[]
    unmatchedOcrCandidates: string[]
  }
}

export type PhotoCategoryStatus = 'complete' | 'duplicate' | 'missing' | 'invalid_count'

export type GroupBarcodeManualConfirmation = {
  meterNo: string
  moduleAssetNo: string
  collector: string
  reason: string
  photoIds: string[]
}

export type ReviewGroupStatus = 'all' | 'reviewable' | 'exception' | 'archived' | 'unconstructed'

export type ReviewGroupQuery = {
  offset: number
  status: ReviewGroupStatus
  query: string
}

export type ReviewGroupPage = {
  total: number
  items: MaterialGroup[]
  statusCounts: Record<ReviewGroupStatus, number>
  limit: number
  offset: number
}

export type GroupSearchResult = {
  total: number
  terminals: string[]
  items: MaterialGroup[]
}

export type DataCenterDataType = 'all' | 'group' | 'unmatched'
export type DataCenterPageSize = 20 | 50 | 100
export type DataCenterBarcodeFilterStatus =
  | 'all'
  | 'passed'
  | 'manual'
  | 'manual_confirmed'
  | 'mismatched'
  | 'failed'
  | 'unreadable'
  | 'ineligible'
  | 'verified'
  | 'needs_review'
export type DataCenterBarcodeEligibility = 'all' | 'eligible' | 'ineligible'
export type DataCenterInstallerSource = 'all' | 'photo'
export type DataCenterTerminalFilterStatus = 'all' | 'completed' | 'incomplete' | 'pending_archive' | 'archived'

export type DataCenterRow = {
  kind: 'group' | 'unmatched'
  id: string
  terminal: string
  meterNo: string
  meterMatchKey: string
  address: string
  collector: string
  moduleAssetNo: string
  constructionCollector: string
  constructionModuleAssetNo: string
  installer: string
  photoCount: number
  classificationStatus: string
  classificationProgress: Record<string, unknown>
  barcodeStatus: string
  barcodeProgress: Record<string, unknown>
  groupBarcodeMissingFields: string[]
  constructionStatus: string
  archiveStatus: string
  exceptionStatus: string
  updatedAt: string
}

export type DataCenterPage = {
  total: number
  page: number
  pageSize: DataCenterPageSize
  items: DataCenterRow[]
}

export type DataCenterDetail = DataCenterRow & {
  photos: ReviewPhoto[]
  audit: Array<Record<string, unknown>>
}

export type ExportCenterPageSize = 20 | 50 | 100
export type ExportCenterTab = 'terminal' | 'device' | 'business' | 'statistics'
export type ExportCatalogMode = 'inline' | 'background'
export type ExportCatalogRequiredFilterKind = 'task'

export type ExportCatalogRequiredFilter = {
  key: string
  label: string
  kind: ExportCatalogRequiredFilterKind
}

export type ExportCatalogItem = {
  key: string
  label: string
  delivery: string
  mode: ExportCatalogMode
  requiredFilters?: ExportCatalogRequiredFilter[]
}

export type TerminalReadinessItem = {
  terminal: string
  groupCount: number
  constructedCount: number
  archivedCount: number
  cacheReadyCount: number
  status: 'ready' | 'blocked'
  blockers: string[]
}

export type TerminalReadinessPage = {
  total: number
  page: number
  pageSize: ExportCenterPageSize
  items: TerminalReadinessItem[]
}

export type ExportJob = {
  id: string
  jobType: string
  status: string
  fileName: string
  rowCount: number
  progress: number
  errorMessage: string
  filters: Record<string, unknown>
  requestKey: string
  createdBy: string
  createdAt: string
  updatedAt: string
  finishedAt: string
  created: boolean
}

export type ExportJobPage = {
  total: number
  page: number
  pageSize: ExportCenterPageSize
  items: ExportJob[]
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
  barcodeCheckStatus?: string
  barcodeCheckExpectedType?: string
  barcodeCheckValues?: string[]
  barcodeCheckNormalizedValues?: string[]
  barcodeCheckOcrValues?: string[]
  barcodeCheckOcrNormalizedValues?: string[]
  barcodeCheckExpectedValues?: string[]
  barcodeCheckMatchedValue?: string
  barcodeCheckedAt?: string
  barcodeCheckError?: string
  barcodeCheckMethod?: string
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
  clientCompletedAt?: string
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
  assignedBy?: string
  assignedAt?: string
  assignmentNote?: string
  dueDate?: string
  payload?: Record<string, unknown>
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
  photoAccuracyChecked: number
  photoAccuracyPassed: number
  photoAccuracyFailed: number
  photoAccuracyUnreadable: number
  photoAccuracyNotRequired: number
  photoAccuracyRate: number
  groupBarcodeAccuracyChecked: number
  groupBarcodeAccuracyPassed: number
  groupBarcodeAccuracyFailed: number
  groupBarcodeAccuracyUnreadable: number
  groupBarcodeAccuracyNotRequired: number
  groupBarcodeAccuracyRate: number
  installerDistribution: Array<{ installer: string; groupCount: number; share: number }>
}

export type PhotoBarcodeReviewPhoto = {
  id: string
  category: string
  categoryLabel: string
  imageUrl: string
  thumbnailUrl: string
  barcodeCheckStatus: string
  barcodeCheckValues: string[]
  barcodeCheckNormalizedValues: string[]
  barcodeCheckOcrValues?: string[]
  barcodeCheckOcrNormalizedValues?: string[]
  barcodeCheckMethod?: string
}

export type PhotoBarcodeReviewGroup = {
  groupId: string
  meterNo: string
  moduleAssetNo: string
  collector: string
  terminal: string
  address: string
  installer: string
  groupStatus: string
  archived: boolean
  photoCount: number
  status: string
  missingFields: string[]
  missingExpectedFields: string[]
  expected: Record<string, string[]>
  detectedValues: Record<string, string[]>
  unmatchedValues: string[]
  barcodeVerification?: BarcodeVerification
  barcodeVerificationStatus?: BarcodeVerificationStatus
  barcodeVerificationSource: string
  barcodeVerificationPassedCount: number
  barcodeVerificationTotalCount: number
  barcodeVerificationReason: string
  photoCategoryClassifiedCount: number
  photoCategoryTotalCount: number
  photoCategoryComplete: boolean
  photoCategoryStatus?: PhotoCategoryStatus
  photos: PhotoBarcodeReviewPhoto[]
}

export type InstallerWorkloadRow = {
  date: string
  groupCount: number
  photoCount: number
  archivedCount: number
  exceptionCount: number
  unreviewedCount: number
  startAt: string
  endAt: string
  startTime: string
  endTime: string
  workDurationMinutes: number
  workDurationHours: number
  workDurationLabel: string
  efficiencyDurationMinutes: number
  efficiencyDurationHours: number
  efficiencyDurationLabel: string
  workDurationMinutesV2: number
  workDurationHoursV2: number
  workDurationLabelV2: string
  workDurationBaseMinutesV2: number
  workDurationDeltaMinutesV2: number
  denseBonusMinutesV2: number
  denseBonusWindowsV2: InstallerDenseBonusWindow[]
  completionPerEffectiveHourV2: number
  weightedCompletionPerEffectiveHourV2: number
  workSpanMinutes: number
  workSpanLabel: string
  breakThresholdMinutes: number
  timepointCount: number
  completionCount: number
  completionPerEffectiveHour: number
  weightedCompletion: number
  weightedCompletionPerEffectiveHour: number
  attendanceWindowMinutes: number
  onlineMinutes: number
  countableOnlineMinutes: number
  onlineRatio: number
  baseOnlineCoefficient: number
  idlePenaltyCoefficient: number
  finalOnlineCoefficient: number
  fusedWorkDurationMinutes: number
  fusedWorkDurationHours: number
  fusedWorkDurationLabel: string
  fusedEfficiencyDurationMinutes: number
  fusedEfficiencyDurationHours: number
  fusedEfficiencyDurationLabel: string
  fusedWeightedCompletionPerEffectiveHour: number
  idleSegments: InstallerIdleSegment[]
  freeIdleSegmentUsed: boolean
  pendingNonIdleCount: number
  confirmedNonIdleCount: number
  onlineConfidence: string
  hourlySegments: InstallerWorkSegment[]
  twoHourSegments: InstallerWorkSegment[]
  exceptionGroups: InstallerExceptionGroup[]
}

export type InstallerIdleSegment = {
  startAt: string
  endAt: string
  startTime: string
  endTime: string
  minutes: number
  hours: number
  free: boolean
  penaltyCoefficient: number
}

export type InstallerDenseBonusWindow = {
  startAt: string
  endAt: string
  startTime: string
  endTime: string
  gapCount: number
  underThreeCount: number
  underFiveCount: number
  bonusMinutes: number
  rule: string
}

export type InstallerWorkSegment = {
  hour: number
  startHour?: number
  endHour?: number
  label: string
  minutes: number
  durationLabel: string
  efficiencyMinutes?: number
  efficiencyDurationLabel?: string
  completionCount?: number
  weightedCompletion?: number
  completionPerEffectiveHour?: number
  weightedCompletionPerEffectiveHour?: number
  addressCount?: number
  addresses?: InstallerWorkAddress[]
}

export type InstallerWorkAddress = {
  groupId: string
  meterNo: string
  terminal: string
  address: string
  status: string
  photoCount: number
  completedAt: string
  completedTime: string
  addressClusterKey: string
  difficultyWeight: number
  difficultyLabel: string
  difficultyReasons: string[]
  clusterSize: number
}

export type InstallerExceptionGroup = {
  groupId: string
  meterNo: string
  terminal: string
  address: string
  status: string
  exceptionNote: string
  exceptionReasons: string[]
  photoCount: number
}

export type InstallerWorkload = {
  installer: string
  items: InstallerWorkloadRow[]
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
  reviewVersion: number
  status: string
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
  assignedTo?: string
  assignedBy?: string
  assignedAt?: string
  assignmentNote?: string
  dueDate?: string
  projectOutside?: boolean
  projectOutsideBy?: string
  projectOutsideAt?: string
  projectOutsideNote?: string
  replacementOldMeterNo?: string
  replacementTargetGroupId?: string
  fieldTaskType?: string
  sourceFile?: string
  raw?: Record<string, unknown>
}

export type UnmatchedListStats = {
  pending: number
  assigned: number
  outside: number
}

export type UnmatchedReviewPhoto = {
  id: string
  category: string
  barcodeCheckStatus: string
  barcodeCheckValues: string[]
  barcodeCheckOcrValues: string[]
  barcodeCheckMethod: string
  barcodeCheckError: string
}

export type UnmatchedReviewDetail = {
  record: UnmatchedRecord
  version: number
  state: 'pending' | 'reviewed'
  meterNo: string
  collector: string
  moduleAssetNo: string
  manualConfirmed: boolean
  reviewer: string
  photos: UnmatchedReviewPhoto[]
}

export type UnmatchedMatchCandidate = {
  candidateKey: string
  hasExistingGroup: boolean
  terminal: string
  meterNo: string
  address: string
  matchReasons: string[]
}

export type ReplacementRecord = {
  groupId: string
  taskId: string | number
  terminal: string
  address: string
  status: string
  photoCount: number
  meterNo: string
  meterMatchKey: string
  oldMeterNo: string
  newMeterNo: string
  replacementBy: string
  replacementAt: string
}
