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

export type MaterialExportTerminalSummary = {
  taskId: string
  projectId: string
  terminalCode: string
  requestedCollectorCount: number
  sourceCollectorCount: number
  finalCollectorCount: number
  activeAllocationCount: number
  lastJobStatus: string
}

export type MaterialExportIssue = {
  code: string
  terminalCode: string
  groupIds: string[]
  meterNos: string[]
  moduleNos: string[]
  message: string
}

export type MaterialExportTerminalPreflight = {
  taskId: string
  terminalCode: string
  constructedMeterCount: number
  sourceCollectorCount: number
  requestedCollectorCount: number
  finalCollectorCount: number
  sourceRevision: string
  canExport: boolean
  issues: MaterialExportIssue[]
  poolShortage: number
}

export type MaterialExportPreflight = {
  projectId: string
  fingerprint: string
  terminals: Record<string, MaterialExportTerminalPreflight>
  sourceGroupIds: string[]
  totalPoolShortage: number
}

export type MaterialExportFile = {
  id: string
  relativePath: string
  sourceKind: 'photo' | 'collector_photo' | 'client_workbook'
  contentType: string
  byteSize: number | null
  sha256: string | null
  status: string
}

export type MaterialExportMeterRow = {
  meterNo: string
  address: string
  moduleNo: string
  finalCollectorNo: string
}

export type MaterialExportSupplementRow = {
  collectorNo: string
  photoFilename: string
}

export type MaterialExportTerminalManifest = {
  id: string
  taskId: string
  terminalCode: string
  status: string
  meterRows: MaterialExportMeterRow[]
  supplementRows: MaterialExportSupplementRow[]
  files: MaterialExportFile[]
}

export type MaterialExportJobDetail = {
  id: string
  status: string
  manifestSha256: string
  terminals: MaterialExportTerminalManifest[]
}

export type MaterialExportLease = {
  scope: string
  jobId: string
  ownerToken: string
  expiresAt: string
}

export type MaterialExportWrittenFile = {
  byteSize: number
  sha256: string
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
export type DataCenterInstallerSource = 'all' | 'photo'
export type DataCenterTerminalFilterStatus = 'all' | 'completed' | 'incomplete' | 'pending_archive' | 'archived'

export type ModuleSourceValues = {
  initialImport: string[]
  construction: string[]
}

export type DataCenterRow = {
  kind: 'group' | 'unmatched'
  id: string
  terminal: string
  meterNo: string
  meterMatchKey: string
  address: string
  collector: string
  moduleAssetNo: string
  moduleSourceValues: ModuleSourceValues
  constructionCollector: string
  constructionModuleAssetNo: string
  installer: string
  photoCount: number
  classificationStatus: string
  classificationProgress: Record<string, unknown>
  constructionStatus: string
  archiveStatus: string
  archiveReady: boolean
  archiveBlockers: string[]
  exceptionStatus: string
  reviewStatus: string
  updatedAt: string
}

export type DataCenterPage = {
  total: number
  page: number
  pageSize: DataCenterPageSize
  items: DataCenterRow[]
}

export type DataCenterAnomaly = {
  code: string
  message: string
  status: 'open' | 'resolved'
  evidenceFingerprint: string
  resolvedBy: string
  resolvedAt: string
}

export type DataCenterDetail = DataCenterRow & {
  classificationManualConfirmation: Record<string, unknown> | null
  classificationConfirmationFingerprint: string
  anomalies: DataCenterAnomaly[]
  photos: ReviewPhoto[]
  audit: Array<Record<string, unknown>>
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

export type CollectorTransferPhoto = {
  id: string
  image_url: string
  object_key: string
  storage_type: string
  storage_key: string
  storage_bucket: string
  sha256: string
  content_type: string
  canonical_image_url: string
  module_asset_no: string
  collector: string
  creator: string
  preview_url: string
  thumbnail_url: string
}

export type CollectorTransferDiagnostic = {
  group_id: string
  code: string
  message: string
}

export type CollectorTransferRun = {
  id: string
  project_id: string
  name: string
  status: 'draft' | 'inventory' | 'allocated' | 'completed' | 'cancelled'
  terminal_count: number
  meter_count: number
  collector_requirement_count: number
  blocked_terminal_count: number
  direct_match_count: number
  pool_available_count: number
  assignment_count: number
  diagnostics: CollectorTransferDiagnostic[]
  created_at: string | null
}

export type CollectorPoolStatus = 'awaiting_photo' | 'direct' | 'available' | 'reserved' | 'used'

export type CollectorInventoryDecision = {
  collector_id: string | null
  collector_no: string
  decision:
    | 'direct_reuse'
    | 'direct_needs_photo'
    | 'pool_needs_photo'
    | 'existing_available'
    | 'existing_reserved'
    | 'existing_used'
  requires_photo: boolean
  add_to_pool: boolean
  pool_status: CollectorPoolStatus | null
  photo: CollectorTransferPhoto | null
}

export type CollectorPhotoRegistration = {
  collector_id: string
  collector_no: string
  pool_status: CollectorPoolStatus
  photo: CollectorTransferPhoto
}

export type CollectorInventoryItem = {
  collector_id: string
  collector_no: string
  pool_status: CollectorPoolStatus
  number_correction_locked: boolean
  photo: CollectorTransferPhoto | null
  last_scanned_at: string | null
  created_at: string | null
}

export type CollectorNumberRecognitionMethod = 'manual' | 'barcode' | 'ocr'

export type CollectorNumberCorrectionRequest = {
  expectedCollectorNo: string
  expectedPhotoSha256: string
  collectorNo: string
  recognitionMethod: CollectorNumberRecognitionMethod
  region: NormalizedRegion | null
}

export type CollectorInventoryStats = Record<CollectorPoolStatus, number>

export type CollectorInventoryPage = {
  items: CollectorInventoryItem[]
  total: number
  stats: CollectorInventoryStats
}

export type CollectorAllocation = {
  assignment_id: string
  requirement_id: string
  original_collector_no: string
  physical_collector_id: string
  final_collector_no: string
  mode: 'random'
}

export type CollectorAllocationResult = {
  run_id: string
  assignment_count: number
  assignments: CollectorAllocation[]
}

export type CollectorWorkbenchTerminal = {
  id: string
  terminal_code: string
  installation_address: string
  status: 'blocked' | 'ready' | 'in_progress' | 'completed'
  meter_count: number
  collector_requirement_count: number
  completed_count: number
  total_count: number
  progress: number
  diagnostics: CollectorTransferDiagnostic[]
}

export type CollectorWorkbenchPhotoSlot = {
  slot: 'module_meter' | 'after_box' | 'collector'
  label: string
  photo: CollectorTransferPhoto | null
}

export type CollectorWorkbenchItemBase = {
  id: string
  status: 'pending' | 'completed'
  photos: CollectorWorkbenchPhotoSlot[]
}

export type CollectorMeterInstallWorkbenchItem = CollectorWorkbenchItemBase & {
  kind: 'meter_install'
  meter_no: string
  meter_barcode: string
  module_no: string
  module_barcode: string
}

export type CollectorRemovalWorkbenchItem = CollectorWorkbenchItemBase & {
  kind: 'collector_removal'
  collector_no: string
  collector_barcode: string
  assignment_mode: 'direct' | 'random'
}

export type CollectorWorkbenchItem = CollectorMeterInstallWorkbenchItem | CollectorRemovalWorkbenchItem

export type CollectorWorkbenchSummary = {
  run: CollectorTransferRun
  terminals: CollectorWorkbenchTerminal[]
}

export type CollectorTerminalWorkbench = {
  run_id: string
  terminal: Pick<CollectorWorkbenchTerminal, 'id' | 'terminal_code' | 'installation_address' | 'status'>
  items: CollectorWorkbenchItem[]
}

export type CollectorWorkbenchItemStatus = {
  id: string
  status: 'pending' | 'completed'
  completed_at: string | null
}

export type GlobalCollectorTerminalState =
  | 'no_construction' | 'needs_review' | 'blocked' | 'needs_replacement'
  | 'pool_shortage' | 'ready' | 'in_progress' | 'completed'
export type CollectorPhysicalState = 'present' | 'missing' | 'replaced'
export type CollectorCaptureStrategy = 'live_physical' | 'unavailable' | 'screen_photo'

export type GlobalCollectorPhoto = {
  id: string
  image_url?: string
  preview_url?: string
  thumbnail_url?: string
  canonical_image_url?: string
}

export type GlobalCollectorTerminalCandidate = {
  terminal_key: string
  project_id: string
  project_name: string
  terminal_code: string
  installation_address: string
  needs_disambiguation: boolean
  meter_count: number
  collector_count: number
  physical_count: number
  missing_count: number
  pool_available_count: number
  workflow_state: GlobalCollectorTerminalState
  selectable: boolean
  source_revision: string
  constructed_meter_count?: number
  unconstructed_meter_count?: number
  review_ready_count?: number
  review_required_count?: number
  diagnostics: CollectorTransferDiagnostic[]
}

export type GlobalCollectorTerminalPage = {
  items: GlobalCollectorTerminalCandidate[]
  page: number
  page_size: number
  total: number
}

export type GlobalCollectorTerminalOpenResult = {
  run_id?: string
  terminal_id?: string
  workbench_terminal_id: string
  project_id?: string
  terminal_code?: string
  source_revision?: string
  current_source_revision?: string
  snapshot_reused: boolean
  source_changed: boolean
}

export type ReviewWorkbenchBlocker = { group_id: string; codes: string[] }
export type ReviewWorkbenchCandidateCounts = {
  constructed_meter_count: number
  unconstructed_meter_count: number
  review_ready_count: number
  review_required_count: number
}
export type ReviewWorkbenchMeter = {
  group_id: string
  meter_no: string
  module_no: string
  collector_no: string
  construction_state: 'constructed' | 'unconstructed'
  review_status: string
  review_ready: boolean
  blockers: string[]
  classification_manually_confirmed: boolean
  classification_confirmation_anomalies: string[]
  classification_manual_confirmation: Record<string, unknown> | null
}
export type ReviewWorkbenchOpenResult = {
  terminal: { terminal_key: string; project_id: string; terminal_code: string; installation_address: string }
  workflow_state: GlobalCollectorTerminalState
  source_revision: string
  constructed_meter_count: number
  unconstructed_meter_count: number
  review_ready_count: number
  review_required_count: number
  review_blockers: ReviewWorkbenchBlocker[]
  meters: ReviewWorkbenchMeter[]
  rephoto: GlobalCollectorTerminalDetail | null
}

export type CollectorRequirementWorkbenchRow = {
  requirement_id: string
  workbench_item_id: string | null
  status: 'pending' | 'completed' | null
  original_collector_no: string
  final_collector_no: string | null
  physical_state: CollectorPhysicalState
  collector_barcode: string | null
  capture_strategy: CollectorCaptureStrategy
  assignment_id: string | null
  photo: GlobalCollectorPhoto | null
  diagnostics: CollectorTransferDiagnostic[]
}

export type GlobalMeterInstallWorkbenchRow = {
  meter_item_id: string
  source_group_id: string
  workbench_item_id: string | null
  status: 'pending' | 'completed' | null
  meter_no: string
  meter_barcode: string
  module_no: string
  module_barcode: string
  photos: Array<{ slot: 'module_meter' | 'after_box'; label: string; photo: GlobalCollectorPhoto | null }>
  diagnostics: CollectorTransferDiagnostic[]
}

export type GlobalCollectorTerminalDetail = {
  run_id: string
  project_id: string
  terminal: { id: string; terminal_code: string; installation_address: string; status: string; diagnostics: CollectorTransferDiagnostic[] }
  meter_install_items: GlobalMeterInstallWorkbenchRow[]
  collector_items: CollectorRequirementWorkbenchRow[]
  pool_summary: { required: number; available: number; shortage: number }
  completed_count: number
  total_count: number
  progress: number
  source_revision: string
  current_source_revision: string
  source_changed: boolean
}

export type GlobalCollectorTerminalReplacementResult = {
  required: number
  assigned: number
  assignments: CollectorAllocation[]
}
