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

export type ProjectModule = {
  id: string
  name: string
  priority: number
  endpoint: string
  routePath: string
}

export type ProjectFieldSource = 'import' | 'field_collection' | 'review' | 'system'

export type ProjectCaptureMethod = 'manual' | 'scan' | 'photo' | 'select' | 'datetime' | 'location' | 'system' | 'none'

export type ProjectFieldDataType = 'text' | 'number' | 'datetime' | 'image' | 'enum' | 'duration' | 'location' | 'boolean'

export type ProjectFieldRequiredWhen = {
  fieldKey: string
  equals: string | string[]
}

export type ProjectFieldRelationRole =
  | 'aggregate'
  | 'task_object'
  | 'task_detail'
  | 'replacement_device'
  | 'old_device'
  | 'accessory_replace_confirm'
  | 'accessory_new_device'
  | 'evidence_photo'
  | 'supporting_field'

export type ProjectFieldDefinition = {
  key: string
  label: string
  dataType: ProjectFieldDataType
  source: ProjectFieldSource
  captureMethod: ProjectCaptureMethod
  required: boolean
  parentKey?: string
  kpiEnabled: boolean
  showInConstructionPanel?: boolean
  options: string[]
  requiredWhen?: ProjectFieldRequiredWhen
  relationRole?: ProjectFieldRelationRole
}

export type ProjectDashboardMetric = {
  key: string
  label: string
  source?: string
  scope?: string
}

export type ProjectWorkItemSchema = {
  schemaVersion?: number
  primaryField?: ProjectFieldDefinition
  aggregateField?: ProjectFieldDefinition
  platformRequiredFields: ProjectFieldDefinition[]
  customFields: ProjectFieldDefinition[]
  dashboardMetrics?: ProjectDashboardMetric[]
}

export type ProjectWorkflowNode = {
  id: string
  type: string
  label: string
  enabled: boolean
  required: boolean
  order: number
  moduleId: string
  config: Record<string, unknown>
}

export type ProjectWorkflowEdge = {
  id: string
  source: string
  target: string
  label: string
}

export type ProjectWorkflow = {
  version: number
  nodes: ProjectWorkflowNode[]
  edges: ProjectWorkflowEdge[]
  updatedAt: string
  updatedBy: string
}

export type ProjectWorkflowStatus = {
  totalNodes: number
  enabledNodeIds: string[]
  enabledNodeLabels: string[]
  enabledModuleIds: string[]
  currentNodeId: string
  currentNodeLabel: string
  pendingNodeIds: string[]
  pendingNodeLabels: string[]
  moduleSyncEnabled: boolean
}

export type ProjectReadinessCheckStatus = 'passed' | 'failed'

export type ProjectReadinessCheck = {
  id: string
  group: string
  label: string
  status: ProjectReadinessCheckStatus
  severity: string
  evidence: Record<string, unknown>
  action: string
}

export type ProjectReadinessSummary = {
  total: number
  passed: number
  failed: number
  blockers: number
}

export type ProjectReadiness = {
  readinessVersion: number
  projectId: string
  ready: boolean
  summary: ProjectReadinessSummary
  checks: ProjectReadinessCheck[]
  nextActions: string[]
  safety: string[]
}

export type ProjectReadinessSummaryItem = {
  projectId: string
  projectName: string
  projectStatus: string
  ready: boolean
  summary: ProjectReadinessSummary
  nextActions: string[]
}

export type ProjectReadinessActionCount = {
  action: string
  count: number
}

export type ProjectReadinessSummaryList = {
  readinessVersion: number
  total: number
  ready: number
  notReady: number
  actionCounts: ProjectReadinessActionCount[]
  items: ProjectReadinessSummaryItem[]
  safety: string[]
}

export type PlatformPersistenceStore = {
  id: string
  label: string
  backend: string
  path: string
  exists: boolean
  parent: string
  parentExists: boolean
  contains: string[]
}

export type PlatformPersistenceStatus = {
  statusVersion: number
  stateBackend: string
  database: {
    configured: boolean
    urlRedacted: string
    usedForPlatformProjectConfig: boolean
    migrationRequiredForPostgresPlatformConfig: boolean
  }
  stores: PlatformPersistenceStore[]
  guarantees: string[]
  safety: string[]
}

export type PlatformConfigPreflightIssue = {
  scope: string
  code: string
  severity: string
  message: string
  action: string
}

export type PlatformConfigPreflightProject = {
  projectId: string
  name: string
  sourceStatus: string
  status: string
  issueCount: number
  issues: PlatformConfigPreflightIssue[]
}

export type PlatformConfigPreflight = {
  preflightVersion: number
  readyForConfigLoad: boolean
  store: {
    id: string
    backend: string
    path: string
    exists: boolean
    readable: boolean
  }
  summary: {
    totalProjects: number
    readyProjects: number
    blockedProjects: number
    storeIssues: number
  }
  issues: PlatformConfigPreflightIssue[]
  projects: PlatformConfigPreflightProject[]
  safety: string[]
}

export type PlatformMigrationGateItem = {
  id: string
  label: string
  description: string
  required: boolean
  status: string
  evidence: string
}

export type PlatformMigrationReadiness = {
  readinessVersion: number
  scope: string
  readyForMigration: boolean
  requiresUserApproval: boolean
  createsMigration: boolean
  targetBackend: string
  targetTables: string[]
  databaseConfigured: boolean
  currentStateBackend: string
  gateItems: PlatformMigrationGateItem[]
  migrationPlan: string[]
  rollbackPlan: string[]
  safety: string[]
}

export type PlatformProductionBaseline = {
  branch: string
  version: string
}

export type PlatformHandoffReadiness = {
  handoffVersion: number
  featureBranch: string
  productionBaseline: PlatformProductionBaseline
  readyForReviewPackage: boolean
  readyForProductionMigration: boolean
  readyForProductionRelease: boolean
  configPreflight: PlatformConfigPreflight
  projectReadinessSummary: ProjectReadinessSummaryList
  persistence: PlatformPersistenceStatus
  migration: PlatformMigrationReadiness
  productionSafety: string[]
  nextActions: string[]
}

export type ProjectConfigRoundtrip = {
  canRestore: boolean
  preservedKeys: string[]
  missingPreservedKeys: string[]
}

export type ProjectConfigPersistenceRecord = {
  teamId: string
  projectKey: string
  name: string
  status: string
  adapter: string
  moduleIds: string[]
  description: string
  fieldSchema: ProjectWorkItemSchema
  workflowDefinition: ProjectWorkflow
  createdAt: string
  updatedAt: string
  createdBy: string
  updatedBy: string
}

export type ProjectConfigPersistenceContract = {
  contractVersion: number
  projectId: string
  sourceBackend: string
  targetBackend: string
  targetTables: string[]
  configRecord: ProjectConfigPersistenceRecord
  roundtrip: ProjectConfigRoundtrip
  migrationGate: string[]
  safety: string[]
}

export type ProjectTemplateType = 'initial_work_orders' | 'external_completed'

export type ProjectTemplateValidationItem = {
  severity: 'error' | 'warning'
  code: string
  row: number | null
  field_key: string
  field_label: string
  message: string
  value: string
}

export type ProjectTemplateValidationReport = {
  project_id: string
  template_type: ProjectTemplateType
  status: 'passed' | 'warning' | 'failed'
  summary: {
    total_rows: number
    error_count: number
    warning_count: number
  }
  expected_headers: string[]
  items: ProjectTemplateValidationItem[]
}

export type ProjectTemplatePreviewField = {
  key: string
  label: string
  source: ProjectFieldSource | string
  captureMethod: ProjectCaptureMethod | string
  dataType: ProjectFieldDataType | string
  required: boolean
  parentKey: string
  relationRole: string
  requiredWhen: { fieldKey: string; equals: string | string[] } | null
  showInConstructionPanel: boolean
  templateHierarchyRole: string
  templateParentLabel: string
  templateConditionHint: string
  platformFillRule: string
}

export type ProjectTemplatePreviewItem = {
  templateType: ProjectTemplateType
  headers: string[]
  fieldRows: ProjectTemplatePreviewField[]
}

export type ProjectTemplateFieldPreview = {
  projectId: string
  templates: ProjectTemplatePreviewItem[]
  siteRequiredFields: string[]
}

export type ProjectCreatePayload = {
  name: string
  description?: string
  moduleIds: string[]
  workItemSchema?: ProjectWorkItemSchema
}

export type Project = {
  id: string
  name: string
  status: 'active' | 'archived' | 'draft'
  stage?: string
  systemProgress?: number
  managementProgress?: number
  managementLocked?: boolean
  totalGroups: number
  completedGroups: number
  exceptionGroups: number
  updatedAt: string
  modules: ProjectModule[]
  workItemSchema?: ProjectWorkItemSchema
  workflow?: ProjectWorkflow
  workflowStatus?: ProjectWorkflowStatus
  tasks?: {
    total: number
    uploaded: number
    reviewing: number
    archived: number
    initialWorkOrders: number
    externalCompleted: number
    pendingReview: number
    returnedRework: number
    approvedArchive: number
    notReady: number
    kpiReady: number
    photoTotal: number
    oldDeviceRecovered: number
    averageOnlineDurationMinutes: number
    installerCount: number
    uploadRate: number
    reviewRate: number
  }
  delivery?: {
    status: string
    totalItems: number
    completedItems: number
    latestRecord: string
  }
  field?: {
    photoRowsLinked: number
    unconstructedGroups: number
    exceptionCount: number
  }
  review?: {
    reviewedGroups: number
    reviewRate: number
    pendingGroups: number
  }
  risks?: {
    total: number
    fieldExceptions: number
    unconstructedGroups: number
    deliveryBlockers: number
  }
}

export type PlatformDeliveryArchiveBlocker = {
  workOrderId: string
  primaryValue: string
  aggregateValue: string
  reason: string
  detail: string
}

export type PlatformDeliveryArchiveReadyItem = {
  workOrderId: string
  primaryValue: string
  aggregateValue: string
  reason: string
}

export type PlatformDeliveryArchiveReadiness = {
  projectId: string
  total: number
  readyForArchive: number
  approvedArchive: number
  pendingReview: number
  returnedRework: number
  evidenceGap: number
  notReady: number
  exception: number
  blocked: number
  ready: boolean
  status: string
  nextActions: string[]
  blockers: PlatformDeliveryArchiveBlocker[]
  readyItems: PlatformDeliveryArchiveReadyItem[]
}

export type PlatformDeliveryArchiveManifestItem = {
  workOrderId: string
  primaryValue: string
  aggregateValue: string
  reason: string
  detail: string
}

export type PlatformDeliveryArchiveManifestSection = {
  id: string
  title: string
  count: number
  items: PlatformDeliveryArchiveManifestItem[]
}

export type PlatformDeliveryArchiveManifestEvidenceItem = {
  key: string
  label: string
  captureMethod: ProjectFieldDefinition['captureMethod']
  relationRole: ProjectFieldDefinition['relationRole']
  required: boolean
  requiredWhen?: ProjectFieldRequiredWhen
}

export type PlatformDeliveryArchiveManifest = {
  projectId: string
  manifestId: string
  generatedAt: string
  status: string
  ready: boolean
  canExport: boolean
  total: number
  readyCount: number
  blockedCount: number
  nextActions: string[]
  requiredEvidence: {
    fields: PlatformDeliveryArchiveManifestEvidenceItem[]
    photos: PlatformDeliveryArchiveManifestEvidenceItem[]
  }
  sections: PlatformDeliveryArchiveManifestSection[]
}

export type PlatformConstructionFieldSchema = {
  primaryField?: ProjectFieldDefinition
  aggregateField?: ProjectFieldDefinition
  displayFields: ProjectFieldDefinition[]
  constructionFields: ProjectFieldDefinition[]
  photoSlots: ProjectFieldDefinition[]
}

export type PlatformReworkEvidenceGapGroup = {
  label: string
  items: string[]
}

export type PlatformConstructionWorkOrder = {
  id: string
  projectId: string
  sourceTaskId: string
  sourceBatchId: string
  primaryValue: string
  aggregateValue: string
  status: string
  createdAt: string
  createdBy: string
  fieldValues: Record<string, string>
  requiredFields: ProjectFieldDefinition[]
  photoSlots: ProjectFieldDefinition[]
  collectionPhotos: PlatformConstructionPhoto[]
  collectionStatus: string
  collectionFieldValues: Record<string, string>
  kpiValues: Record<string, string>
  coveredPhotoSlots: string[]
  clientBatchId: string
  collectedBy: string
  collectedAt: string
  reviewStatus: string
  reviewedBy: string
  reviewedAt: string
  reviewNote: string
  reviewReason: string
  reviewHistory: PlatformReviewHistoryEvent[]
  reworkEvidenceGapGroups: PlatformReworkEvidenceGapGroup[]
}

export type PlatformConstructionPhoto = {
  id: string
  slot: string
  clientPhotoId: string
  filename: string
  contentType: string
  size: number
  storage: string
  storageKey: string
  uploadedBy: string
  uploadedAt: string
}

export type PlatformConstructionWorkOrders = {
  projectId: string
  total: number
  fieldSchema: PlatformConstructionFieldSchema
  items: PlatformConstructionWorkOrder[]
}

export type PlatformReviewHistoryEvent = {
  id: string
  action: 'approved' | 'returned' | 'exception' | string
  actor: string
  reviewedAt: string
  note: string
  reason: string
}

export type PlatformReviewFieldReview = {
  key: string
  label: string
  captureMethod: ProjectFieldDefinition['captureMethod']
  required: boolean
  requiredWhen?: ProjectFieldRequiredWhen
  relationRole?: ProjectFieldDefinition['relationRole']
  initialValue: string
  collectedValue: string
}

export type PlatformReviewPhotoSlotReview = {
  key: string
  label: string
  required: boolean
  requiredWhen?: ProjectFieldRequiredWhen
  relationRole?: ProjectFieldDefinition['relationRole']
  covered: boolean
  photoCount: number
}

export type PlatformReviewHierarchyGapItem = {
  row: number | null
  fieldKey: string
  fieldLabel: string
  message: string
  value: string
}

export type PlatformReviewWorkOrder = PlatformConstructionWorkOrder & {
  reviewStatus: string
  reviewedBy: string
  reviewedAt: string
  reviewNote: string
  reviewReason: string
  reviewHistory: PlatformReviewHistoryEvent[]
  suggestedReviewReturnReason: string
  reviewHierarchyGapItems: PlatformReviewHierarchyGapItem[]
  fieldReviews: PlatformReviewFieldReview[]
  photoSlotReviews: PlatformReviewPhotoSlotReview[]
}

export type PlatformReviewWorkOrders = {
  projectId: string
  total: number
  statusCounts: {
    pending_review: number
    approved: number
    returned: number
    exception: number
    not_ready: number
  }
  fieldSchema: PlatformConstructionFieldSchema
  items: PlatformReviewWorkOrder[]
}

export type PlatformReviewActionPayload = {
  actor: string
  action: 'approved' | 'returned' | 'exception'
  note: string
  reason: string
}

export type PlatformConstructionCollectionPayload = {
  actor: string
  clientBatchId: string
  status: 'cached' | 'submitted'
  fieldValues: Record<string, string>
  coveredPhotoSlots: string[]
}

export type PlatformConstructionPhotoUploadPayload = {
  actor: string
  slot: string
  clientPhotoId: string
  file: File
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
  constructionClaimedBy?: string
  constructionClaimedByName?: string
  assignedConstructor?: string
  assignedConstructorName?: string
  constructionUploadedCount?: number
  constructionUnbuiltCount?: number
  constructionExceptionCount?: number
  installerDistribution?: Array<{ installer: string; groupCount: number; share: number }>
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
  collector?: string
  moduleAssetNo?: string
  creator?: string
  constructionCollector?: string
  constructionModuleAssetNo?: string
  constructionStatus?: string
  fieldValues?: Record<string, string>
  exceptionOrderId?: string
  groupBarcodeCheckStatus?: string
  groupBarcodeMatchedFields?: string[]
  groupBarcodeMissingFields?: string[]
  groupBarcodePassedCount?: number
  groupBarcodeTotalCount?: number
  groupBarcodeManualConfirmed?: boolean
  photoCategoryClassifiedCount?: number
  photoCategoryTotalCount?: number
  photoCategoryComplete?: boolean
  photos?: ReviewPhoto[]
}

export type GroupSearchResult = {
  total: number
  terminals: string[]
  items: MaterialGroup[]
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
  constructionSlot?: string
  constructionSlotLabel?: string
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
  requiredWhen?: ProjectFieldRequiredWhen
  relationRole?: ProjectFieldRelationRole
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
  fieldValues?: Record<string, string>
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

export type UnmatchedDedupeResult = {
  total: number
  kept: number
  removed: number
  duplicateIds: string[]
}
