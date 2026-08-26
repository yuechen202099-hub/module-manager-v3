import { mockTasks } from './mock'
import { priorityRequestBody } from './claimTasksState.mjs'
import { parseContentDispositionFilename } from './constructionPriorityImportState.mjs'
import type {
  AuthConfig,
  ConstructionExceptionOrder,
  ConstructionPriorityImportResult,
  ConstructionUploadPayload,
  CollectorAllocationResult,
  CollectorInventoryDecision,
  CollectorInventoryPage,
  CollectorPhotoRegistration,
  GlobalCollectorTerminalCandidate,
  GlobalCollectorTerminalDetail,
  GlobalCollectorTerminalOpenResult,
  GlobalCollectorTerminalPage,
  GlobalCollectorTerminalReplacementResult,
  ReviewWorkbenchOpenResult,
  CollectorTerminalWorkbench,
  CollectorTransferRun,
  CollectorWorkbenchItemStatus,
  CollectorWorkbenchSummary,
  CurrentUser,
  DataCenterBarcodeFilterStatus,
  DataCenterBarcodeEligibility,
  DataCenterDataType,
  DataCenterInstallerSource,
  DataCenterDetail,
  DataCenterPage,
  DataCenterPageSize,
  DataCenterRow,
  DataCenterTerminalFilterStatus,
  GroupBarcodeManualConfirmation,
  GroupSearchResult,
  ImportJob,
  InstallerWorkload,
  MaterialGroup,
  PhotoBarcodeReviewGroup,
  Project,
  ProjectSummary,
  RegionScanRequest,
  RegionScanResult,
  ReplacementRecord,
  ReviewGroupPage,
  ReviewGroupQuery,
  ReviewPhoto,
  ReviewTask,
  TaskSnapshot,
  TaskStatusSummary,
  TaskStatus,
  UnmatchedMatchCandidate,
  UnmatchedListStats,
  UnmatchedRecord,
  UnmatchedReviewDetail,
  UnmatchedReviewPhoto,
  UserAccount,
  UserRole,
  BarcodeVerification,
  BarcodeVerificationStatus,
} from './types'

type BackendRegionScanResult = {
  barcode_type: RegionScanResult['barcodeType']
  values: string[]
  normalized_values: string[]
  method: RegionScanResult['method']
  region: RegionScanResult['region']
}

function regionScanRequestBody(request: RegionScanRequest) {
  return {
    barcode_type: request.barcodeType,
    region: request.region,
  }
}

function mapRegionScanResult(raw: BackendRegionScanResult): RegionScanResult {
  return {
    barcodeType: raw.barcode_type,
    values: raw.values.map(String),
    normalizedValues: raw.normalized_values.map(String),
    method: raw.method,
    region: { ...raw.region },
  }
}

type ApiEnvelope<T> = {
  data?: T
  error?: { message?: string }
  detail?: string
}

type BackendDataCenterRow = {
  kind?: 'group' | 'unmatched'
  id?: string
  terminal?: string
  meter_no?: string
  meter_match_key?: string
  address?: string
  collector?: string
  module_asset_no?: string
  construction_collector?: string
  construction_module_asset_no?: string
  installer?: string
  photo_count?: number
  classification_status?: string
  classification_progress?: Record<string, unknown>
  barcode_status?: string
  barcode_progress?: Record<string, unknown>
  group_barcode_missing_fields?: string[]
  construction_status?: string
  archive_status?: string
  exception_status?: string
  status?: string
  updated_at?: string
  photos?: BackendPhoto[]
  audit?: Array<Record<string, unknown>>
}

type BackendDataCenterPage = {
  total?: number
  page?: number
  page_size?: number
  items?: BackendDataCenterRow[]
}

type LegacySession = {
  access_token?: string
  token_type?: string
  team_id?: string
  user?: {
    username?: string
    name?: string
    team_id?: string
    roles?: UserRole[]
  }
}

type AuthLoginData = {
  access_token: string
  token_type?: string
  team_id?: string
  user?: {
    username?: string
    name?: string
    team_id?: string
    roles?: UserRole[]
  }
}

type BackendAuthConfig = {
  demo_auth_enabled?: boolean
  demo_accounts?: AuthConfig['demo_accounts']
  account_config_enabled?: boolean
}

type BackendTask = {
  id: number | string
  terminal?: string
  address?: string
  address_search_text?: string
  meter_search_text?: string
  name?: string
  status?: string
  claimed_by?: string
  claimed_by_name?: string
  can_claim?: boolean
  has_scan_info?: boolean
  total_groups?: number
  renovation_count?: number
  uploaded_count?: number
  upload_rate?: number
  reviewed_count?: number
  unreviewed_count?: number
  exception_groups?: number
  review_rate?: number
  construction_enabled?: boolean
  construction_priority?: boolean
  construction_available?: boolean
  review_available?: boolean
  construction_claimed_by?: string
  construction_claimed_by_name?: string
  assigned_constructor?: string
  assigned_constructor_name?: string
  construction_uploaded_count?: number
  construction_unbuilt_count?: number
  construction_exception_count?: number
  installer_distribution?: Array<{ installer?: string; group_count?: number; share?: number }>
}

type BackendTaskSnapshot = {
  team_id?: string
  items?: BackendTask[]
  version?: string
  generated_at?: string
  cache?: {
    source?: string
    stale?: boolean
    refresh_interval_seconds?: number
  }
}

const VALID_LEGACY_SESSION_ROLES = new Set<UserRole>(['admin', 'constructor'])

type BackendTaskStatusSummary = {
  version?: string
  generated_at?: string
  total?: number
  scanned?: number
  uploaded?: number
  reviewing?: number
  archived?: number
  claimed?: number
  construction_assigned?: number
  avg_upload_rate?: number
  avg_review_rate?: number
  renovation_count?: number
  uploaded_count?: number
  reviewed_count?: number
  unreviewed_count?: number
  total_catalog_rows?: number
  groups?: number
}

type BackendPhoto = {
  id: string | number
  url?: string
  image_url?: string
  source_url?: string
  preview_url?: string
  thumbnail_url?: string
  delivery_cache_url?: string
  storage_type?: string
  storage_key?: string
  category?: string
  category_label?: string
  archive_status?: string
  archive_filename?: string
  barcode?: string
  collector?: string
  module_asset_no?: string
  asset_no?: string
  creator?: string
  barcode_check_status?: string
  barcode_check_expected_type?: string
  barcode_check_values?: unknown[]
  barcode_check_normalized_values?: unknown[]
  barcode_check_ocr_values?: unknown[]
  barcode_check_ocr_normalized_values?: unknown[]
  barcode_check_expected_values?: unknown[]
  barcode_check_matched_value?: string
  barcode_checked_at?: string
  barcode_check_error?: string
  barcode_check_method?: string
}

type BackendGroup = {
  id: string | number
  task_id?: string | number
  address?: string
  meter_no?: string
  meter_match_key?: string
  terminal?: string
  status?: string
  photo_count?: number
  reviewer?: string
  review_note?: string
  exception_note?: string
  exception_reasons?: string[]
  has_archive_blocker?: boolean
  installer?: string
  collector?: string
  module_asset_no?: string
  asset_no?: string
  creator?: string
  construction_collector?: string
  construction_module_asset_no?: string
  construction_status?: string
  exception_order_id?: string
  group_barcode_check_status?: string
  group_barcode_matched_fields?: unknown[]
  group_barcode_missing_fields?: unknown[]
  group_barcode_passed_count?: number
  group_barcode_total_count?: number
  group_barcode_manual_confirmed?: boolean
  barcode_verification?: BackendBarcodeVerification
  barcode_verification_status?: string
  barcode_verification_source?: string
  barcode_verification_passed_count?: number
  barcode_verification_total_count?: number
  barcode_verification_reason?: string
  photo_category_classified_count?: number
  photo_category_total_count?: number
  photo_category_complete?: boolean
  photo_category_status?: string
  photos?: BackendPhoto[]
}

type BackendBarcodeVerification = {
  status?: string
  recognition_source?: string
  invalidation_reason?: string
  evidence_version?: number
  result?: {
    passed_count?: number
    matched_fields?: unknown[]
    missing_fields?: unknown[]
    machine_barcode_values?: unknown[]
    machine_qr_values?: unknown[]
    ocr_candidates?: unknown[]
    unmatched_machine_values?: unknown[]
    matched_ocr_candidates?: unknown[]
    unmatched_ocr_candidates?: unknown[]
  }
}

type BackendReviewGroupPage = {
  total?: number
  items?: BackendGroup[]
  status_counts?: Partial<Record<ReviewGroupQuery['status'], number>>
  limit?: number
  offset?: number
}

type BackendConstructionExceptionOrder = {
  id?: string | number
  task_id?: string | number
  group_id?: string | number
  terminal?: string
  meter_no?: string
  address?: string
  status?: string
  category?: string
  note?: string
  assigned_to?: string
  assigned_by?: string
  assigned_at?: string
  assignment_note?: string
  due_date?: string
  payload?: Record<string, unknown>
  group?: BackendGroup
}

type BackendSummary = {
  total_catalog_rows?: number
  groups?: number
  scanned_groups?: number
  approved_groups?: number
  reviewed_groups?: number
  unreviewed_groups?: number
  exception_groups?: number
  incomplete_groups?: number
  unconstructed_groups?: number
  photo_rows_linked?: number
  scan_unmatched?: number
  review_progress?: number
  photo_accuracy_checked?: number
  photo_accuracy_passed?: number
  photo_accuracy_failed?: number
  photo_accuracy_unreadable?: number
  photo_accuracy_not_required?: number
  photo_accuracy_rate?: number
  group_barcode_accuracy_checked?: number
  group_barcode_accuracy_passed?: number
  group_barcode_accuracy_failed?: number
  group_barcode_accuracy_unreadable?: number
  group_barcode_accuracy_not_required?: number
  group_barcode_accuracy_rate?: number
  installer_distribution?: Array<{ installer?: string; group_count?: number; share?: number }>
}

type BackendPhotoBarcodeReviewPhoto = {
  id?: string | number
  category?: string
  category_label?: string
  image_url?: string
  thumbnail_url?: string
  barcode_check_status?: string
  barcode_check_values?: unknown[]
  barcode_check_normalized_values?: unknown[]
  barcode_check_ocr_values?: unknown[]
  barcode_check_ocr_normalized_values?: unknown[]
  barcode_check_method?: string
}

type BackendPhotoBarcodeReviewGroup = {
  group_id?: string
  meter_no?: string
  module_asset_no?: string
  collector?: string
  terminal?: string
  address?: string
  installer?: string
  group_status?: string
  archived?: boolean
  photo_count?: number
  status?: string
  missing_fields?: string[]
  missing_expected_fields?: string[]
  expected?: Record<string, string[]>
  detected_values?: Record<string, string[]>
  unmatched_values?: string[]
  barcode_verification?: BackendBarcodeVerification
  barcode_verification_status?: string
  barcode_verification_source?: string
  barcode_verification_passed_count?: number
  barcode_verification_total_count?: number
  barcode_verification_reason?: string
  photo_category_classified_count?: number
  photo_category_total_count?: number
  photo_category_complete?: boolean
  photo_category_status?: string
  photos?: BackendPhotoBarcodeReviewPhoto[]
}

type BackendImportJob = {
  job_id?: string
  id?: string
  status?: string
  progress?: Record<string, unknown>
  result?: Record<string, unknown>
  error?: string
}

type BackendUnmatchedRecord = {
  unmatched_id?: string
  review_version?: number
  barcode?: string
  meter_no?: string
  meter_match_key?: string
  terminal?: string
  address?: string
  collector?: string
  module_asset_no?: string
  asset_no?: string
  creator?: string
  photo_count?: number
  photo_urls?: unknown
  record_type?: string
  status?: string
  assigned_to?: string
  assigned_by?: string
  assigned_at?: string
  assignment_note?: string
  due_date?: string
  project_outside?: boolean
  project_outside_by?: string
  project_outside_at?: string
  project_outside_note?: string
  replacement_old_meter_no?: string
  replacement_target_group_id?: string
  field_task_type?: string
  source_file?: string
  raw?: Record<string, unknown>
}

type BackendUnmatchedListStats = {
  pending?: number
  assigned?: number
  outside?: number
}

type BackendUnmatchedReviewPhoto = {
  id?: string
  category?: string
  barcode_check_status?: string
  barcode_check_values?: string[]
  barcode_check_ocr_values?: string[]
  barcode_check_method?: string
  barcode_check_error?: string
}

type BackendUnmatchedReview = {
  version?: number
  state?: string
  meter_no?: string
  collector?: string
  module_asset_no?: string
  manual_confirmed?: boolean
  reviewer?: string
  photos?: BackendUnmatchedReviewPhoto[]
}

type BackendUnmatchedReviewResponse = {
  record?: BackendUnmatchedRecord
  review?: BackendUnmatchedReview
}

type BackendUnmatchedMatchCandidate = {
  candidate_key?: string
  has_existing_group?: boolean
  terminal?: string
  meter_no?: string
  address?: string
  match_reasons?: string[]
}

type BackendUnmatchedMatchCandidates = {
  total?: number
  items?: BackendUnmatchedMatchCandidate[]
}

type BackendReplacementRecord = {
  group_id?: string
  task_id?: string | number
  terminal?: string
  address?: string
  status?: string
  photo_count?: number
  meter_no?: string
  meter_match_key?: string
  old_meter_no?: string
  new_meter_no?: string
  replacement_by?: string
  replacement_at?: string
}

type BackendUserAccount = {
  username?: string
  name?: string
  roles?: UserRole[]
  team_id?: string
  status?: string
  home?: string
  last_login_at?: string
  last_login_ip?: string
  last_login_device?: string
  login_history?: Array<{
    at?: string
    ip?: string
    device?: string
    ip_common_user?: string
    ip_common_user_name?: string
    ip_common_user_count?: number
    ip_login_count?: number
  }>
}

type BackendInstallerWorkload = {
  installer?: string
  items?: Array<{
    date?: string
    group_count?: number
    photo_count?: number
    archived_count?: number
    exception_count?: number
    unreviewed_count?: number
    start_at?: string
    end_at?: string
    start_time?: string
    end_time?: string
    work_duration_minutes?: number
    work_duration_hours?: number
    work_duration_label?: string
    efficiency_duration_minutes?: number
    efficiency_duration_hours?: number
    efficiency_duration_label?: string
    work_duration_minutes_v2?: number
    work_duration_hours_v2?: number
    work_duration_label_v2?: string
    work_duration_base_minutes_v2?: number
    work_duration_delta_minutes_v2?: number
    dense_bonus_minutes_v2?: number
    dense_bonus_windows_v2?: Array<{
      start_at?: string
      end_at?: string
      start_time?: string
      end_time?: string
      gap_count?: number
      under_three_count?: number
      under_five_count?: number
      bonus_minutes?: number
      rule?: string
    }>
    completion_per_effective_hour_v2?: number
    weighted_completion_per_effective_hour_v2?: number
    work_span_minutes?: number
    work_span_label?: string
    break_threshold_minutes?: number
    timepoint_count?: number
    completion_count?: number
    completion_per_effective_hour?: number
    weighted_completion?: number
    weighted_completion_per_effective_hour?: number
    attendance_window_minutes?: number
    online_minutes?: number
    countable_online_minutes?: number
    online_ratio?: number
    base_online_coefficient?: number
    idle_penalty_coefficient?: number
    final_online_coefficient?: number
    fused_work_duration_minutes?: number
    fused_work_duration_hours?: number
    fused_work_duration_label?: string
    fused_efficiency_duration_minutes?: number
    fused_efficiency_duration_hours?: number
    fused_efficiency_duration_label?: string
    fused_weighted_completion_per_effective_hour?: number
    idle_segments?: Array<{
      start_at?: string
      end_at?: string
      start_time?: string
      end_time?: string
      minutes?: number
      hours?: number
      free?: boolean
      penalty_coefficient?: number
    }>
    free_idle_segment_used?: boolean
    pending_non_idle_count?: number
    confirmed_non_idle_count?: number
    online_confidence?: string
    hourly_segments?: Array<{
      hour?: number
      label?: string
      minutes?: number
      duration_label?: string
    }>
    two_hour_segments?: Array<{
      hour?: number
      start_hour?: number
      end_hour?: number
      label?: string
      minutes?: number
      duration_label?: string
      efficiency_minutes?: number
      efficiency_duration_label?: string
      completion_count?: number
      weighted_completion?: number
      completion_per_effective_hour?: number
      weighted_completion_per_effective_hour?: number
      address_count?: number
      addresses?: Array<{
        group_id?: string
        meter_no?: string
        terminal?: string
        address?: string
        status?: string
        photo_count?: number
        completed_at?: string
        completed_time?: string
        address_cluster_key?: string
        difficulty_weight?: number
        difficulty_label?: string
        difficulty_reasons?: string[]
        cluster_size?: number
      }>
    }>
    exception_groups?: Array<{
      group_id?: string
      meter_no?: string
      terminal?: string
      address?: string
      status?: string
      exception_note?: string
      exception_reasons?: string[]
      photo_count?: number
    }>
  }>
}

const delay = (ms = 120) => new Promise((resolve) => window.setTimeout(resolve, ms))

export class ApiRequestError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
  }
}

export function getApiErrorStatus(error: unknown) {
  if (error instanceof ApiRequestError) return error.status
  if (typeof error !== 'object' || error === null) return undefined
  const status = (error as { status?: unknown }).status
  return typeof status === 'number' ? status : undefined
}

function createApiRequestError(response: Response, payload?: ApiEnvelope<unknown>) {
  return new ApiRequestError(payload?.detail || payload?.error?.message || response.statusText, response.status)
}

function readLegacySession(): LegacySession | null {
  if (typeof localStorage === 'undefined') return null
  try {
    const session = JSON.parse(localStorage.getItem('module_manager_session') || 'null') as LegacySession | null
    if (!session) return null
    if (!session.user?.username || !session.access_token) return invalidateLegacySession()
    const rawRoles = Array.isArray(session.user.roles) ? [...session.user.roles] : []
    const roles = normalizeLegacySessionRoles(session)
    if (roles.length === 0 || roles.length !== rawRoles.length) {
      return invalidateLegacySession()
    }
    return {
      ...session,
      user: {
        ...session.user,
        roles,
      },
    }
  } catch {
    return invalidateLegacySession()
  }
}

export function currentActor() {
  const session = readLegacySession()
  return session?.user?.username || 'admin'
}

export function currentTeamId() {
  const session = readLegacySession()
  return session?.team_id || session?.user?.team_id || localStorage.getItem('module_manager_team_id') || 'default-team'
}

function authHeaders(): HeadersInit {
  const session = readLegacySession()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Team-Id': currentTeamId(),
  }
  if (session?.access_token) {
    headers.Authorization = `${session.token_type || 'bearer'} ${session.access_token}`
  }
  return headers
}

function formHeaders(): HeadersInit {
  const session = readLegacySession()
  const headers: Record<string, string> = {
    'X-Team-Id': currentTeamId(),
  }
  if (session?.access_token) {
    headers.Authorization = `${session.token_type || 'bearer'} ${session.access_token}`
  }
  return headers
}

function normalizeLegacySessionRoles(session: LegacySession | null): UserRole[] {
  const roles = Array.isArray(session?.user?.roles) ? session.user.roles : []
  return Array.from(new Set(roles.filter((role): role is UserRole => VALID_LEGACY_SESSION_ROLES.has(role))))
}

function clearLocalAuthSession() {
  if (typeof localStorage === 'undefined') return
  localStorage.removeItem('v2-web-token')
  localStorage.removeItem('v2-web-user')
  localStorage.removeItem('module_manager_session')
  localStorage.removeItem('module_manager_reviewer')
}

function redirectToLogin() {
  if (typeof window === 'undefined') return
  if (window.location.pathname === '/login') return
  const target = `${window.location.pathname}${window.location.search}${window.location.hash}`
  const query = target && target !== '/' ? `?redirect=${encodeURIComponent(target)}` : ''
  window.location.assign(`/login${query}`)
}

function invalidateLegacySession(): null {
  clearLocalAuthSession()
  redirectToLogin()
  return null
}

function handleUnauthorizedResponse(response: Response) {
  if (response.status === 401) {
    clearLocalAuthSession()
    redirectToLogin()
  }
  if (response.status === 429) {
    const retryAfter = response.headers.get('Retry-After')
    console.warn('请求过于频繁，请稍后再试', retryAfter ? { retryAfter } : undefined)
  }
}

export function readLegacySessionAccessToken() {
  return readLegacySession()?.access_token || ''
}

async function fetchWithAuth(path: string, init: RequestInit = {}) {
  const response = await fetch(path, init)
  handleUnauthorizedResponse(response)
  return response
}

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = String(init.method || 'GET').toUpperCase()
  const response = await fetchWithAuth(path, {
    ...init,
    headers: {
      ...authHeaders(),
      ...(init.headers || {}),
    },
  })
  const payload = (await response.json()) as ApiEnvelope<T>
  if (!response.ok || payload.error) {
    throw createApiRequestError(response, payload)
  }
  if (method !== 'GET' && method !== 'HEAD') emitDataMutated(`api:${method}:${path}`)
  return payload.data as T
}

async function formApi<T>(path: string, formData: FormData): Promise<T> {
  const response = await fetchWithAuth(path, {
    method: 'POST',
    headers: formHeaders(),
    body: formData,
  })
  const payload = (await response.json()) as ApiEnvelope<T>
  if (!response.ok || payload.error) {
    throw createApiRequestError(response, payload)
  }
  emitDataMutated(`form:${path}`)
  return payload.data as T
}

function emitDataMutated(reason: string, payload: Record<string, unknown> = {}) {
  if (typeof window === 'undefined') return
  window.postMessage(
    {
      type: 'module-manager:data-mutated',
      reason,
      payload: {
        path: reason,
        ...payload,
      },
    },
    window.location.origin,
  )
}

function roleFromSession(session: LegacySession | null, username: string): UserRole {
  const role = session?.user?.roles?.[0]
  if (role) return role
  if (username === 'admin' || username.includes('admin') || username.includes('管理')) return 'admin'
  if (username.includes('constructor') || username.includes('施工')) return 'constructor'
  return 'constructor'
}

function mapTask(raw: BackendTask): ReviewTask {
  const renovationCount = Number(raw.renovation_count || raw.total_groups || 0)
  const reviewedCount = Number(raw.reviewed_count || 0)
  const uploadedCount = Number(raw.uploaded_count || 0)
  const unreviewedCount = Number(raw.unreviewed_count || Math.max(renovationCount - reviewedCount, 0))
  return {
    id: String(raw.id),
    projectId: 'local-test',
    name: raw.name || `终端 ${raw.terminal || raw.id}`,
    stage: raw.terminal || '',
    status: (raw.status || 'pending') as TaskStatus,
    terminal: raw.terminal || '',
    address: raw.address || '',
    addressSearchText: raw.address_search_text || raw.address || '',
    meterSearchText: raw.meter_search_text || '',
    totalGroups: renovationCount,
    claimedGroups: uploadedCount,
    completedGroups: reviewedCount,
    ownerName: raw.claimed_by_name || raw.claimed_by || '',
    claimedBy: raw.claimed_by || '',
    claimedByName: raw.claimed_by_name || '',
    canClaim: Boolean(raw.can_claim),
    hasScanInfo: Boolean(raw.has_scan_info ?? raw.can_claim),
    renovationCount,
    uploadedCount,
    reviewedCount,
    unreviewedCount,
    uploadRate: Number(raw.upload_rate || (renovationCount ? uploadedCount / renovationCount : 0)),
    reviewRate: Number(raw.review_rate || (renovationCount ? reviewedCount / renovationCount : 0)),
    constructionEnabled: Boolean(raw.construction_enabled),
    constructionPriority: Boolean(raw.construction_priority),
    constructionAvailable: Boolean(raw.construction_available),
    reviewAvailable: Boolean(raw.review_available),
    constructionClaimedBy: raw.construction_claimed_by || '',
    constructionClaimedByName: raw.construction_claimed_by_name || '',
    assignedConstructor: raw.assigned_constructor || raw.construction_claimed_by || '',
    assignedConstructorName: raw.assigned_constructor_name || raw.construction_claimed_by_name || '',
    constructionUploadedCount: Number(raw.construction_uploaded_count || raw.uploaded_count || 0),
    constructionUnbuiltCount: Number(raw.construction_unbuilt_count || Math.max(renovationCount - uploadedCount, 0)),
    constructionExceptionCount: Number(raw.construction_exception_count || raw.exception_groups || 0),
    installerDistribution: (raw.installer_distribution || []).map((item) => ({
      installer: item.installer || '',
      groupCount: Number(item.group_count || 0),
      share: Number(item.share || 0),
    })).filter((item) => item.installer && item.groupCount > 0),
  }
}

function mapTaskStatusSummary(raw: BackendTaskStatusSummary): TaskStatusSummary {
  return {
    version: raw.version || '',
    generatedAt: raw.generated_at || '',
    total: Number(raw.total || 0),
    scanned: Number(raw.scanned || 0),
    uploaded: Number(raw.uploaded || 0),
    reviewing: Number(raw.reviewing || 0),
    archived: Number(raw.archived || 0),
    claimed: Number(raw.claimed || 0),
    constructionAssigned: Number(raw.construction_assigned || 0),
    avgUploadRate: Number(raw.avg_upload_rate || 0),
    avgReviewRate: Number(raw.avg_review_rate || 0),
    renovationCount: Number(raw.renovation_count || 0),
    uploadedCount: Number(raw.uploaded_count || 0),
    reviewedCount: Number(raw.reviewed_count || 0),
    unreviewedCount: Number(raw.unreviewed_count || 0),
    totalCatalogRows: Number(raw.total_catalog_rows || 0),
    groups: Number(raw.groups || 0),
  }
}

function mapStringArray(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item || '')).filter(Boolean)
  const text = String(value || '').trim()
  return text ? [text] : []
}

function mapPhoto(raw: BackendPhoto): ReviewPhoto {
  const originalUrl = raw.image_url || raw.source_url || raw.url || ''
  const imageUrl = raw.delivery_cache_url || raw.preview_url || raw.thumbnail_url || originalUrl
  const category = raw.category || 'unclassified'
  return {
    id: String(raw.id),
    url: imageUrl,
    imageUrl,
    sourceUrl: raw.source_url || '',
    previewUrl: raw.preview_url || '',
    thumbnailUrl: raw.thumbnail_url || '',
    deliveryCacheUrl: raw.delivery_cache_url || '',
    storageType: raw.storage_type || '',
    storageKey: raw.storage_key || '',
    name: raw.archive_filename || raw.category_label || `#${raw.id}`,
    status: category === 'unclassified' ? 'unclassified' : 'valid',
    category,
    categoryLabel: raw.category_label || '',
    archiveStatus: raw.archive_status || '',
    archiveFilename: raw.archive_filename || '',
    barcode: raw.barcode || '',
    collector: raw.collector || '',
    moduleAssetNo: raw.module_asset_no || raw.asset_no || '',
    creator: raw.creator || '',
    barcodeCheckStatus: raw.barcode_check_status || '',
    barcodeCheckExpectedType: raw.barcode_check_expected_type || '',
    barcodeCheckValues: mapStringArray(raw.barcode_check_values),
    barcodeCheckNormalizedValues: mapStringArray(raw.barcode_check_normalized_values),
    barcodeCheckOcrValues: mapStringArray(raw.barcode_check_ocr_values),
    barcodeCheckOcrNormalizedValues: mapStringArray(raw.barcode_check_ocr_normalized_values),
    barcodeCheckExpectedValues: mapStringArray(raw.barcode_check_expected_values),
    barcodeCheckMatchedValue: raw.barcode_check_matched_value || '',
    barcodeCheckedAt: raw.barcode_checked_at || '',
    barcodeCheckError: raw.barcode_check_error || '',
    barcodeCheckMethod: raw.barcode_check_method || '',
  }
}

function mapGroup(raw: BackendGroup): MaterialGroup {
  const barcodeVerification = mapBarcodeVerification(raw.barcode_verification)
  const barcodeVerificationStatus = normalizeBarcodeVerificationStatus(
    barcodeVerification?.status || raw.barcode_verification_status,
  )
  const durablePassedCount = Number(
    barcodeVerification?.result.passedCount ?? raw.barcode_verification_passed_count ?? raw.group_barcode_passed_count ?? 0,
  )
  return {
    id: String(raw.id),
    taskId: raw.task_id || '',
    address: raw.address || '',
    meterNo: raw.meter_no || '',
    meterMatchKey: raw.meter_match_key || '',
    terminal: raw.terminal || '',
    status: (raw.status || 'pending') as TaskStatus,
    photoCount: Number(raw.photo_count || raw.photos?.length || 0),
    reviewer: raw.reviewer || '',
    reviewNote: raw.review_note || '',
    exceptionNote: raw.exception_note || '',
    exceptionReasons: Array.isArray(raw.exception_reasons) ? raw.exception_reasons.filter(Boolean) : [],
    hasArchiveBlocker: Boolean(raw.has_archive_blocker),
    installer: raw.installer || '',
    collector: raw.collector || '',
    moduleAssetNo: raw.module_asset_no || raw.asset_no || '',
    creator: raw.creator || '',
    constructionCollector: raw.construction_collector || '',
    constructionModuleAssetNo: raw.construction_module_asset_no || '',
    constructionStatus: raw.construction_status || '',
    exceptionOrderId: raw.exception_order_id || '',
    groupBarcodeCheckStatus: raw.group_barcode_check_status || '',
    groupBarcodeMatchedFields: mapStringArray(raw.group_barcode_matched_fields),
    groupBarcodeMissingFields: mapStringArray(raw.group_barcode_missing_fields),
    groupBarcodePassedCount: Number(raw.group_barcode_passed_count || 0),
    groupBarcodeTotalCount: Number(raw.group_barcode_total_count || 3),
    groupBarcodeManualConfirmed: Boolean(raw.group_barcode_manual_confirmed),
    barcodeVerification,
    barcodeVerificationStatus,
    barcodeVerificationSource: barcodeVerification?.recognitionSource || raw.barcode_verification_source || '',
    barcodeVerificationPassedCount: durablePassedCount,
    barcodeVerificationTotalCount: Number(raw.barcode_verification_total_count || raw.group_barcode_total_count || 3),
    barcodeVerificationReason: barcodeVerification?.invalidationReason || raw.barcode_verification_reason || '',
    photoCategoryClassifiedCount: Number(raw.photo_category_classified_count || 0),
    photoCategoryTotalCount: Number(raw.photo_category_total_count || 0),
    photoCategoryComplete: Boolean(raw.photo_category_complete),
    photoCategoryStatus: normalizePhotoCategoryStatus(raw.photo_category_status),
    photos: (raw.photos || []).map(mapPhoto),
  }
}

function mapDataCenterRow(raw: BackendDataCenterRow): DataCenterRow {
  return {
    kind: raw.kind === 'unmatched' ? 'unmatched' : 'group',
    id: String(raw.id || ''),
    terminal: raw.terminal || '',
    meterNo: raw.meter_no || '',
    meterMatchKey: raw.meter_match_key || '',
    address: raw.address || '',
    collector: raw.collector || '',
    moduleAssetNo: raw.module_asset_no || '',
    constructionCollector: raw.construction_collector || '',
    constructionModuleAssetNo: raw.construction_module_asset_no || '',
    installer: raw.installer || '',
    photoCount: Number(raw.photo_count || raw.photos?.length || 0),
    classificationStatus: raw.classification_status || 'incomplete',
    classificationProgress: raw.classification_progress || {},
    barcodeStatus: raw.barcode_status || 'ineligible',
    barcodeProgress: raw.barcode_progress || {},
    groupBarcodeMissingFields: mapStringArray(raw.group_barcode_missing_fields),
    constructionStatus: raw.construction_status || 'unconstructed',
    archiveStatus: raw.archive_status || 'unarchived',
    exceptionStatus: raw.exception_status || '',
    reviewStatus: raw.status || 'pending',
    updatedAt: raw.updated_at || '',
  }
}

function mapDataCenterDetail(raw: BackendDataCenterRow): DataCenterDetail {
  return {
    ...mapDataCenterRow(raw),
    photos: (raw.photos || []).map(mapPhoto),
    audit: raw.audit || [],
  }
}

function normalizeBarcodeVerificationStatus(value: unknown): BarcodeVerificationStatus | undefined {
  const status = String(value || '')
  if (
    [
      'not_eligible',
      'pending',
      'processing',
      'passed',
      'partial',
      'unreadable',
      'mismatch',
      'manual_confirmed',
      'failed',
    ].includes(status)
  ) {
    return status as BarcodeVerificationStatus
  }
  return undefined
}

function mapBarcodeVerification(raw?: BackendBarcodeVerification): BarcodeVerification | undefined {
  const status = normalizeBarcodeVerificationStatus(raw?.status)
  if (!raw || !status) return undefined
  return {
    status,
    recognitionSource: raw.recognition_source || '',
    invalidationReason: raw.invalidation_reason || '',
    evidenceVersion: Number(raw.evidence_version || 0),
    result: {
      passedCount: Number(raw.result?.passed_count || 0),
      matchedFields: mapStringArray(raw.result?.matched_fields),
      missingFields: mapStringArray(raw.result?.missing_fields),
      machineBarcodeValues: mapStringArray(raw.result?.machine_barcode_values),
      machineQrValues: mapStringArray(raw.result?.machine_qr_values),
      ocrCandidates: mapStringArray(raw.result?.ocr_candidates),
      unmatchedMachineValues: mapStringArray(raw.result?.unmatched_machine_values),
      matchedOcrCandidates: mapStringArray(raw.result?.matched_ocr_candidates),
      unmatchedOcrCandidates: mapStringArray(raw.result?.unmatched_ocr_candidates),
    },
  }
}

function normalizePhotoCategoryStatus(value: unknown): MaterialGroup['photoCategoryStatus'] {
  const status = String(value || '')
  if (['complete', 'duplicate', 'missing', 'invalid_count'].includes(status)) {
    return status as MaterialGroup['photoCategoryStatus']
  }
  return undefined
}

function mapConstructionExceptionOrder(raw: BackendConstructionExceptionOrder): ConstructionExceptionOrder {
  const group = raw.group ? mapGroup(raw.group) : undefined
  return {
    id: String(raw.id || ''),
    taskId: raw.task_id || group?.taskId || '',
    groupId: String(raw.group_id || group?.id || ''),
    terminal: raw.terminal || group?.terminal || '',
    meterNo: raw.meter_no || group?.meterNo || '',
    address: raw.address || group?.address || '',
    status: raw.status || '',
    category: raw.category || '',
    note: raw.note || '',
    assignedTo: raw.assigned_to || '',
    assignedBy: raw.assigned_by || '',
    assignedAt: raw.assigned_at || '',
    assignmentNote: raw.assignment_note || '',
    dueDate: raw.due_date || '',
    payload: raw.payload || {},
    group,
  }
}

function mapSummary(raw: BackendSummary): ProjectSummary {
  return {
    totalCatalogRows: Number(raw.total_catalog_rows || 0),
    groups: Number(raw.groups || 0),
    scannedGroups: Number(raw.scanned_groups || 0),
    approvedGroups: Number(raw.approved_groups || 0),
    reviewedGroups: Number(raw.reviewed_groups || 0),
    unreviewedGroups: Number(raw.unreviewed_groups || 0),
    exceptionGroups: Number(raw.exception_groups || 0),
    incompleteGroups: Number(raw.incomplete_groups || 0),
    unconstructedGroups: Number(raw.unconstructed_groups || 0),
    photoRowsLinked: Number(raw.photo_rows_linked || 0),
    scanUnmatched: Number(raw.scan_unmatched || 0),
    reviewProgress: Number(raw.review_progress || 0),
    photoAccuracyChecked: Number(raw.photo_accuracy_checked || 0),
    photoAccuracyPassed: Number(raw.photo_accuracy_passed || 0),
    photoAccuracyFailed: Number(raw.photo_accuracy_failed || 0),
    photoAccuracyUnreadable: Number(raw.photo_accuracy_unreadable || 0),
    photoAccuracyNotRequired: Number(raw.photo_accuracy_not_required || 0),
    photoAccuracyRate: Number(raw.photo_accuracy_rate || 0),
    groupBarcodeAccuracyChecked: Number(raw.group_barcode_accuracy_checked || 0),
    groupBarcodeAccuracyPassed: Number(raw.group_barcode_accuracy_passed || 0),
    groupBarcodeAccuracyFailed: Number(raw.group_barcode_accuracy_failed || 0),
    groupBarcodeAccuracyUnreadable: Number(raw.group_barcode_accuracy_unreadable || 0),
    groupBarcodeAccuracyNotRequired: Number(raw.group_barcode_accuracy_not_required || 0),
    groupBarcodeAccuracyRate: Number(raw.group_barcode_accuracy_rate || 0),
    installerDistribution: (raw.installer_distribution || []).map((item) => ({
      installer: item.installer || '未填写',
      groupCount: Number(item.group_count || 0),
      share: Number(item.share || 0),
    })),
  }
}

function mapImportJob(raw: BackendImportJob): ImportJob {
  return {
    jobId: String(raw.job_id || raw.id || ''),
    status: raw.status || 'unknown',
    progress: raw.progress || {},
    result: raw.result || {},
    error: raw.error || '',
  }
}

function mapUnmatchedRecord(raw: BackendUnmatchedRecord): UnmatchedRecord {
  const photoUrls = Array.isArray(raw.photo_urls) ? raw.photo_urls : []
  return {
    unmatchedId: raw.unmatched_id || '',
    reviewVersion: Number(raw.review_version || 1),
    status: raw.status || '',
    barcode: raw.barcode || '',
    meterNo: raw.meter_no || '',
    meterMatchKey: raw.meter_match_key || '',
    terminal: raw.terminal || '',
    address: raw.address || '',
    collector: raw.collector || '',
    moduleAssetNo: raw.module_asset_no || raw.asset_no || '',
    creator: raw.creator || '',
    photoCount: Number(raw.photo_count || photoUrls.length || 0),
    recordType: raw.record_type || '',
    assignedTo: raw.assigned_to || '',
    assignedBy: raw.assigned_by || '',
    assignedAt: raw.assigned_at || '',
    assignmentNote: raw.assignment_note || '',
    dueDate: raw.due_date || '',
    projectOutside: Boolean(raw.project_outside),
    projectOutsideBy: raw.project_outside_by || '',
    projectOutsideAt: raw.project_outside_at || '',
    projectOutsideNote: raw.project_outside_note || '',
    replacementOldMeterNo: raw.replacement_old_meter_no || '',
    replacementTargetGroupId: raw.replacement_target_group_id || '',
    fieldTaskType: raw.field_task_type || '',
    sourceFile: raw.source_file || '',
    raw: raw.raw || {},
  }
}

function mapReplacementRecord(raw: BackendReplacementRecord): ReplacementRecord {
  return {
    groupId: raw.group_id || '',
    taskId: raw.task_id || '',
    terminal: raw.terminal || '',
    address: raw.address || '',
    status: raw.status || '',
    photoCount: Number(raw.photo_count || 0),
    meterNo: raw.meter_no || '',
    meterMatchKey: raw.meter_match_key || '',
    oldMeterNo: raw.old_meter_no || '',
    newMeterNo: raw.new_meter_no || '',
    replacementBy: raw.replacement_by || '',
    replacementAt: raw.replacement_at || '',
  }
}

function mapUserAccount(raw: BackendUserAccount): UserAccount {
  return {
    username: raw.username || '',
    name: raw.name || raw.username || '',
    roles: Array.isArray(raw.roles) ? raw.roles : [],
    teamId: raw.team_id || 'default-team',
    status: raw.status || 'active',
    home: raw.home || '',
    lastLoginAt: raw.last_login_at || '',
    lastLoginIp: raw.last_login_ip || '',
    lastLoginDevice: raw.last_login_device || '',
    loginHistory: (raw.login_history || []).map((item) => ({
      at: item.at || '',
      ip: item.ip || '',
      device: item.device || '',
      ipCommonUser: item.ip_common_user || '',
      ipCommonUserName: item.ip_common_user_name || '',
      ipCommonUserCount: Number(item.ip_common_user_count || 0),
      ipLoginCount: Number(item.ip_login_count || 0),
    })),
  }
}

export async function fetchAuthConfig(): Promise<AuthConfig> {
  const response = await fetch('/auth/config')
  const payload = (await response.json()) as ApiEnvelope<BackendAuthConfig>
  if (!response.ok || payload.error || !payload.data) {
    throw new Error(payload.detail || payload.error?.message || response.statusText)
  }
  return {
    demo_auth_enabled: Boolean(payload.data.demo_auth_enabled),
    demo_accounts: Array.isArray(payload.data.demo_accounts) ? payload.data.demo_accounts : [],
    account_config_enabled: Boolean(payload.data.account_config_enabled),
  }
}

export async function login(username: string, password: string, teamId = currentTeamId()): Promise<{ token: string; user: CurrentUser }> {
  if (!username || !password) {
    throw new Error('请输入账号和密码')
  }
  const normalizedTeamId = teamId.trim() || 'default-team'

  const response = await fetch('/auth/login', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Team-Id': normalizedTeamId,
    },
    body: JSON.stringify({
      username,
      password,
      team_id: normalizedTeamId,
    }),
  })
  const payload = (await response.json()) as ApiEnvelope<AuthLoginData>
  if (!response.ok || payload.error || !payload.data?.access_token) {
    throw new Error(payload.detail || payload.error?.message || response.statusText)
  }

  const data = payload.data
  const session: LegacySession = {
    access_token: data.access_token,
    token_type: data.token_type || 'bearer',
    team_id: data.team_id || data.user?.team_id || normalizedTeamId,
    user: {
      username: data.user?.username || username,
      name: data.user?.name || username,
      team_id: data.user?.team_id || data.team_id || normalizedTeamId,
      roles: data.user?.roles || [],
    },
  }
  localStorage.setItem('module_manager_session', JSON.stringify(session))
  localStorage.setItem('module_manager_team_id', session.team_id || 'default-team')
  localStorage.setItem('module_manager_reviewer', session.user?.username || username)

  const role = roleFromSession(session, username)
  return {
    token: data.access_token,
    user: {
      id: session.user?.username || username,
      username: session.user?.username || username,
      name: session?.user?.name || username,
      role,
      roles: session?.user?.roles || [role],
      teamId: session.team_id || normalizedTeamId,
    },
  }
}

export async function fetchCurrentUser(): Promise<CurrentUser> {
  const session = readLegacySession()
  if (!session?.user) {
    throw new Error('Legacy session is invalid')
  }
  const username = session.user.username || session.user.name || 'admin'
  const role = roleFromSession(session, username)
  return {
    id: username,
    username,
    name: session.user.name || username,
    role,
    roles: session.user.roles || [role],
    teamId: currentTeamId(),
  }
}

export async function fetchUserAccounts(): Promise<UserAccount[]> {
  const data = await api<{ items: BackendUserAccount[] }>('/auth/users')
  return (data.items || []).map(mapUserAccount)
}

export async function saveUserAccount(payload: {
  username: string
  password?: string
  name: string
  roles: UserRole[]
  teamId: string
  status: string
}): Promise<UserAccount> {
  const data = await api<{ user: BackendUserAccount }>('/auth/users', {
    method: 'POST',
    body: JSON.stringify({
      username: payload.username,
      password: payload.password || undefined,
      name: payload.name,
      roles: payload.roles,
      team_id: payload.teamId,
      status: payload.status,
    }),
  })
  return mapUserAccount(data.user)
}

export async function deleteUserAccount(username: string): Promise<UserAccount> {
  const data = await api<{ user: BackendUserAccount }>(`/auth/users/${encodeURIComponent(username)}`, {
    method: 'DELETE',
  })
  return mapUserAccount(data.user)
}

export async function fetchProjects(): Promise<Project[]> {
  return fetchCollectorTransferProjects()
}

export async function fetchCollectorTransferProjects(): Promise<Project[]> {
  const data = await api<{
    items?: Array<{
      id?: string
      name?: string
      status?: 'active' | 'archived'
      updated_at?: string | null
    }>
  }>('/collector-transfer/projects')
  return (data.items || []).map((project): Project => ({
    id: String(project.id || ''),
    name: project.name || '未命名项目',
    status: project.status === 'archived' ? 'archived' : 'active',
    totalGroups: 0,
    completedGroups: 0,
    exceptionGroups: 0,
    updatedAt: project.updated_at || '',
  })).filter((project) => Boolean(project.id))
}

export async function fetchTasks(options: { summary?: boolean } = {}): Promise<ReviewTask[]> {
  const query = options.summary ? '?summary=true' : ''
  const data = await api<{ items: BackendTask[] }>(`/local-test/tasks${query}`)
  return (data.items || []).map(mapTask)
}

export async function fetchTaskSnapshot(
  options: boolean | { force?: boolean; signal?: AbortSignal } = false,
): Promise<TaskSnapshot> {
  const force = typeof options === 'boolean' ? options : Boolean(options.force)
  const signal = typeof options === 'boolean' ? undefined : options.signal
  const suffix = force ? '?refresh=true' : ''
  const data = await api<BackendTaskSnapshot>(`/local-test/tasks/snapshot${suffix}`, { signal })
  return {
    teamId: data.team_id || '',
    items: (data.items || []).map(mapTask),
    version: data.version || '',
    generatedAt: data.generated_at || '',
    cache: {
      source: data.cache?.source || '',
      stale: Boolean(data.cache?.stale),
      refreshIntervalSeconds: Number(data.cache?.refresh_interval_seconds || 0),
    },
  }
}

export async function fetchTaskStatus(): Promise<TaskStatusSummary> {
  const data = await api<BackendTaskStatusSummary>('/local-test/tasks/status')
  return mapTaskStatusSummary(data || {})
}

export function boardEventsUrl(scope = 'project-board'): string {
  const query = new URLSearchParams({ scope, team_id: currentTeamId() })
  return `/local-test/events?${query.toString()}`
}

export function boardEventHeaders(): HeadersInit {
  return formHeaders()
}

export async function claimTask(taskId: string): Promise<ReviewTask> {
  const task = await api<BackendTask>(`/local-test/tasks/${encodeURIComponent(taskId)}/claim`, {
    method: 'POST',
    body: JSON.stringify({ reviewer: currentActor() }),
  })
  return mapTask(task)
}

export async function releaseTask(taskId: string): Promise<ReviewTask> {
  const task = await api<BackendTask>(`/local-test/tasks/${encodeURIComponent(taskId)}/release`, {
    method: 'POST',
    body: JSON.stringify({ reviewer: currentActor() }),
  })
  return mapTask(task)
}

export async function releaseAllClaimedTasks(): Promise<{ released: number }> {
  return api<{ released: number }>('/local-test/tasks/release-all', {
    method: 'POST',
    body: JSON.stringify({ reviewer: currentActor() }),
  })
}

export async function fetchTaskGroups(taskId = '1'): Promise<MaterialGroup[]> {
  const data = await api<{ total: number; items: BackendGroup[] }>(
    `/local-test/tasks/${encodeURIComponent(taskId)}/groups?limit=1000&scan_only=false&summary=true`,
  )
  return (data.items || []).map(mapGroup)
}

export async function fetchReviewTaskGroups(
  taskId: string,
  options: ReviewGroupQuery,
): Promise<ReviewGroupPage> {
  const params = new URLSearchParams({
    limit: '20',
    offset: String(options.offset),
    review_status: options.status,
    query: options.query,
  })
  const data = await api<BackendReviewGroupPage>(
    `/local-test/tasks/${encodeURIComponent(taskId)}/review-groups?${params}`,
  )
  return {
    total: Number(data.total || 0),
    items: (data.items || []).map(mapGroup),
    statusCounts: {
      all: Number(data.status_counts?.all || 0),
      reviewable: Number(data.status_counts?.reviewable || 0),
      exception: Number(data.status_counts?.exception || 0),
      archived: Number(data.status_counts?.archived || 0),
      unconstructed: Number(data.status_counts?.unconstructed || 0),
    },
    limit: Number(data.limit || 20),
    offset: Number(data.offset || 0),
  }
}

export async function searchGroups(options: {
  query?: string
  terminal?: string
  limit?: number
  offset?: number
  signal?: AbortSignal
}): Promise<GroupSearchResult> {
  const params = new URLSearchParams()
  params.set('query', options.query || '')
  if (options.terminal) params.set('terminal', options.terminal)
  params.set('limit', String(options.limit || 30))
  params.set('offset', String(options.offset || 0))
  const data = await api<{ total: number; terminals?: string[]; items?: BackendGroup[] }>(
    `/groups/search?${params.toString()}`,
    { signal: options.signal },
  )
  return {
    total: Number(data.total || 0),
    terminals: data.terminals || [],
    items: (data.items || []).map(mapGroup),
  }
}

function mapUnmatchedReviewPhoto(raw: BackendUnmatchedReviewPhoto): UnmatchedReviewPhoto {
  return {
    id: raw.id || '',
    category: raw.category || 'unclassified',
    barcodeCheckStatus: raw.barcode_check_status || 'not_checked',
    barcodeCheckValues: Array.isArray(raw.barcode_check_values) ? raw.barcode_check_values.map(String) : [],
    barcodeCheckOcrValues: Array.isArray(raw.barcode_check_ocr_values) ? raw.barcode_check_ocr_values.map(String) : [],
    barcodeCheckMethod: raw.barcode_check_method || '',
    barcodeCheckError: raw.barcode_check_error || '',
  }
}

function mapUnmatchedReview(raw: BackendUnmatchedReviewResponse): UnmatchedReviewDetail {
  const review = raw.review || {}
  return {
    record: mapUnmatchedRecord(raw.record || {}),
    version: Number(review.version || 0),
    state: review.state === 'reviewed' ? 'reviewed' : 'pending',
    meterNo: review.meter_no || '',
    collector: review.collector || '',
    moduleAssetNo: review.module_asset_no || '',
    manualConfirmed: Boolean(review.manual_confirmed),
    reviewer: review.reviewer || '',
    photos: (review.photos || []).map(mapUnmatchedReviewPhoto),
  }
}

function mapUnmatchedMatchCandidate(raw: BackendUnmatchedMatchCandidate): UnmatchedMatchCandidate {
  return {
    candidateKey: raw.candidate_key || '',
    hasExistingGroup: Boolean(raw.has_existing_group),
    terminal: raw.terminal || '',
    meterNo: raw.meter_no || '',
    address: raw.address || '',
    matchReasons: Array.isArray(raw.match_reasons) ? raw.match_reasons.map(String) : [],
  }
}

function mapPhotoBarcodeReviewGroup(raw: BackendPhotoBarcodeReviewGroup): PhotoBarcodeReviewGroup {
  const barcodeVerification = mapBarcodeVerification(raw.barcode_verification)
  const barcodeVerificationStatus = normalizeBarcodeVerificationStatus(
    barcodeVerification?.status || raw.barcode_verification_status,
  )
  return {
    groupId: raw.group_id || '',
    meterNo: raw.meter_no || '',
    moduleAssetNo: raw.module_asset_no || '',
    collector: raw.collector || '',
    terminal: raw.terminal || '',
    address: raw.address || '',
    installer: raw.installer || '',
    groupStatus: raw.group_status || '',
    archived: Boolean(raw.archived),
    photoCount: Number(raw.photo_count || raw.photos?.length || 0),
    status: raw.status || '',
    missingFields: raw.missing_fields || [],
    missingExpectedFields: raw.missing_expected_fields || [],
    expected: raw.expected || {},
    detectedValues: raw.detected_values || {},
    unmatchedValues: raw.unmatched_values || [],
    barcodeVerification,
    barcodeVerificationStatus,
    barcodeVerificationSource: barcodeVerification?.recognitionSource || raw.barcode_verification_source || '',
    barcodeVerificationPassedCount: Number(
      barcodeVerification?.result.passedCount ?? raw.barcode_verification_passed_count ?? 0,
    ),
    barcodeVerificationTotalCount: Number(raw.barcode_verification_total_count || 3),
    barcodeVerificationReason: barcodeVerification?.invalidationReason || raw.barcode_verification_reason || '',
    photoCategoryClassifiedCount: Number(raw.photo_category_classified_count || 0),
    photoCategoryTotalCount: Number(raw.photo_category_total_count || 0),
    photoCategoryComplete: Boolean(raw.photo_category_complete),
    photoCategoryStatus: normalizePhotoCategoryStatus(raw.photo_category_status),
    photos: (raw.photos || []).map((photo) => ({
      id: String(photo.id || ''),
      category: photo.category || '',
      categoryLabel: photo.category_label || '',
      imageUrl: photo.image_url || '',
        thumbnailUrl: photo.thumbnail_url || photo.image_url || '',
        barcodeCheckStatus: photo.barcode_check_status || '',
        barcodeCheckValues: mapStringArray(photo.barcode_check_values),
        barcodeCheckNormalizedValues: mapStringArray(photo.barcode_check_normalized_values),
        barcodeCheckOcrValues: mapStringArray(photo.barcode_check_ocr_values),
        barcodeCheckOcrNormalizedValues: mapStringArray(photo.barcode_check_ocr_normalized_values),
        barcodeCheckMethod: photo.barcode_check_method || '',
      })),
    }
  }

export async function updateAdminGroupMetadata(
  groupId: string,
  updates: Record<string, unknown>,
): Promise<{ group: MaterialGroup; changedFields: string[] }> {
  const data = await api<{ group?: BackendGroup; changed_fields?: string[] }>(
    `/groups/${encodeURIComponent(groupId)}/metadata`,
    {
      method: 'PATCH',
      body: JSON.stringify({ updates }),
    },
  )
  return {
    group: mapGroup(data.group || ({} as BackendGroup)),
    changedFields: (data.changed_fields || []).map(String),
  }
}

export type DataCenterListQuery = {
  dataType?: DataCenterDataType
  constructionStatus?: string
  terminalStatus?: DataCenterTerminalFilterStatus
  archiveStatus?: string
  barcodeStatus?: DataCenterBarcodeFilterStatus
  barcodeEligibility?: DataCenterBarcodeEligibility
  classificationStatus?: string
  exceptionStatus?: string
  installer?: string
  installerSource?: DataCenterInstallerSource
  hasPhotos?: boolean
  dateFrom?: string
  dateTo?: string
  activityDateFrom?: string
  activityDateTo?: string
  terminal?: string
  keyword?: string
  page?: number
  pageSize?: DataCenterPageSize
  sort?: string
  signal?: AbortSignal
}

export async function fetchDataCenterRows(query: DataCenterListQuery): Promise<DataCenterPage> {
  const params = new URLSearchParams({
    data_type: query.dataType || 'all',
    construction_status: query.constructionStatus || 'all',
    terminal_status: query.terminalStatus || 'all',
    archive_status: query.archiveStatus || 'all',
    barcode_status: query.barcodeStatus || 'all',
    barcode_eligibility: query.barcodeEligibility || 'all',
    classification_status: query.classificationStatus || 'all',
    exception_status: query.exceptionStatus || '',
    installer: query.installer || '',
    installer_source: query.installerSource || 'all',
    terminal: query.terminal || '',
    query: query.keyword || '',
    page: String(query.page || 1),
    page_size: String(query.pageSize || 20),
    sort: query.sort || 'updated_desc',
  })
  if (query.hasPhotos) params.set('has_photos', '1')
  if (query.dateFrom) params.set('date_from', query.dateFrom)
  if (query.dateTo) params.set('date_to', query.dateTo)
  if (query.activityDateFrom) params.set('activity_date_from', query.activityDateFrom)
  if (query.activityDateTo) params.set('activity_date_to', query.activityDateTo)
  const data = await api<BackendDataCenterPage>(`/groups/data-center?${params.toString()}`, {
    signal: query.signal,
  })
  const pageSize = [20, 50, 100].includes(Number(data.page_size)) ? Number(data.page_size) as DataCenterPageSize : 20
  return {
    total: Number(data.total || 0),
    page: Number(data.page || query.page || 1),
    pageSize,
    items: (data.items || []).map(mapDataCenterRow),
  }
}

export async function fetchDataCenterDetail(
  kind: DataCenterRow['kind'],
  itemId: string,
  signal?: AbortSignal,
): Promise<DataCenterDetail> {
  const data = await api<BackendDataCenterRow>(
    `/groups/data-center/${encodeURIComponent(kind)}/${encodeURIComponent(itemId)}`,
    { signal },
  )
  return mapDataCenterDetail(data)
}

export async function reviewDataCenterGroup(
  groupId: string,
  status: 'approved' | 'incomplete' | 'exception',
  note = '',
  exceptionNote = '',
): Promise<MaterialGroup> {
  const data = await api<BackendGroup>(
    `/groups/data-center/groups/${encodeURIComponent(groupId)}/review`,
    {
      method: 'PATCH',
      body: JSON.stringify({ status, note, exception_note: exceptionNote }),
    },
  )
  return mapGroup(data)
}

export async function updateDataCenterGroup(
  groupId: string,
  patch: Record<string, unknown>,
  reason = '',
): Promise<{ group?: MaterialGroup; changedFields: string[]; archiveStatus: string; barcodeStatus: string }> {
  const data = await api<{
    group?: BackendGroup
    changed_fields?: string[]
    archive_status?: string
    barcode_status?: string
  }>(`/groups/data-center/groups/${encodeURIComponent(groupId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ patch, reason, source_page: 'data_center' }),
  })
  return {
    group: data.group ? mapGroup(data.group) : undefined,
    changedFields: (data.changed_fields || []).map(String),
    archiveStatus: data.archive_status || '',
    barcodeStatus: data.barcode_status || '',
  }
}

export async function confirmDataCenterGroupBarcode(
  groupId: string,
  payload: GroupBarcodeManualConfirmation,
): Promise<{ group?: MaterialGroup; archiveStatus: string; barcodeStatus: string; deliveryPackageJobStatus: string }> {
  const data = await api<{
    group?: BackendGroup
    archive_status?: string
    barcode_status?: string
    delivery_package_job_status?: string
  }>(`/groups/data-center/groups/${encodeURIComponent(groupId)}/barcode-manual-confirm`, {
    method: 'POST',
    body: JSON.stringify({
      meter_no: payload.meterNo,
      module_asset_no: payload.moduleAssetNo,
      collector: payload.collector,
      reason: payload.reason,
      photo_ids: payload.photoIds,
      source_page: 'data_center',
    }),
  })
  return {
    group: data.group ? mapGroup(data.group) : undefined,
    archiveStatus: data.archive_status || '',
    barcodeStatus: data.barcode_status || '',
    deliveryPackageJobStatus: data.delivery_package_job_status || '',
  }
}

export async function classifyDataCenterGroupPhoto(
  groupId: string,
  photoId: string,
  category: string,
  reason = '数据中台照片分类',
): Promise<{ group?: MaterialGroup; archiveStatus: string; barcodeStatus: string; deliveryPackageJobStatus: string }> {
  const data = await api<{
    group?: BackendGroup
    archive_status?: string
    barcode_status?: string
    delivery_package_job_status?: string
  }>(
    `/groups/data-center/groups/${encodeURIComponent(groupId)}/photos/${encodeURIComponent(photoId)}/classify`,
    {
      method: 'POST',
      body: JSON.stringify({ category, reason, source_page: 'data_center' }),
    },
  )
  return {
    group: data.group ? mapGroup(data.group) : undefined,
    archiveStatus: data.archive_status || '',
    barcodeStatus: data.barcode_status || '',
    deliveryPackageJobStatus: data.delivery_package_job_status || '',
  }
}

export async function rescanDataCenterGroupPhotoBarcode(
  groupId: string,
  photoId: string,
  category = '',
  reason = '数据中台重新扫码',
): Promise<{ photo: ReviewPhoto }> {
  const data = await api<BackendPhoto>(
    `/groups/data-center/groups/${encodeURIComponent(groupId)}/photos/${encodeURIComponent(photoId)}/barcode-rescan`,
    {
      method: 'POST',
      body: JSON.stringify({ category, reason, source_page: 'data_center' }),
    },
  )
  return { photo: mapPhoto(data) }
}

export async function scanDataCenterGroupPhotoRegion(
  groupId: string,
  photoId: string,
  request: RegionScanRequest,
  reason = '数据中台框选扫码',
): Promise<RegionScanResult> {
  const data = await api<BackendRegionScanResult>(
    `/groups/data-center/groups/${encodeURIComponent(groupId)}/photos/${encodeURIComponent(photoId)}/region-scan`,
    {
      method: 'POST',
      body: JSON.stringify({ ...regionScanRequestBody(request), reason, source_page: 'data_center' }),
    },
  )
  return mapRegionScanResult(data)
}

export async function finalizeDataCenterUnmatchedToGroup(
  unmatchedId: string,
  payload: { terminal: string; meterNo: string; candidateKey: string; expectedVersion: number },
): Promise<{ groupId: string }> {
  const data = await api<{ group?: { id?: string } }>(
    `/groups/data-center/unmatched/${encodeURIComponent(unmatchedId)}/finalize-to-group`,
    {
      method: 'POST',
      body: JSON.stringify({
        terminal: payload.terminal,
        meter_no: payload.meterNo,
        candidate_key: payload.candidateKey,
        expected_version: payload.expectedVersion,
        source_page: 'data_center',
      }),
    },
  )
  return { groupId: data.group?.id ? String(data.group.id) : '' }
}

export async function returnDataCenterGroupToException(
  groupId: string,
  payload: { category: string; note: string; reason?: string },
): Promise<{ group: MaterialGroup }> {
  const data = await api<{ group?: BackendGroup }>(
    `/groups/data-center/groups/${encodeURIComponent(groupId)}/return-exception`,
    {
      method: 'PATCH',
      body: JSON.stringify({
        category: payload.category,
        note: payload.note,
        reason: payload.reason || payload.note,
        source_page: 'data_center',
      }),
    },
  )
  return { group: mapGroup(data.group || ({} as BackendGroup)) }
}

export async function resetAdminGroupToUnreviewed(
  groupId: string,
  reason = '',
): Promise<{ group: MaterialGroup }> {
  const data = await api<{ group?: BackendGroup }>(
    `/groups/${encodeURIComponent(groupId)}/reset-unreviewed`,
    {
      method: 'PATCH',
      body: JSON.stringify({ reason, source_page: 'data_center' }),
    },
  )
  return { group: mapGroup(data.group || ({} as BackendGroup)) }
}

export async function resetAdminGroupToUnconstructed(
  groupId: string,
  reason = '',
): Promise<{ group: MaterialGroup; softDeletedPhotos: number }> {
  const data = await api<{ group?: BackendGroup; soft_deleted_photos?: number }>(
    `/groups/${encodeURIComponent(groupId)}/reset-unconstructed`,
    {
      method: 'PATCH',
      body: JSON.stringify({ reason, source_page: 'data_center' }),
    },
  )
  return {
    group: mapGroup(data.group || ({} as BackendGroup)),
    softDeletedPhotos: Number(data.soft_deleted_photos || 0),
  }
}

export async function bulkArchiveAdminGroups(groupIds: string[], reason = ''): Promise<{
  archivedCount: number
  skipped: Array<{ groupId: string; reason: string }>
  groups: MaterialGroup[]
}> {
  const data = await api<{
    archived_count?: number
    skipped?: Array<{ group_id?: string; reason?: string }>
    groups?: BackendGroup[]
  }>('/groups/bulk-archive', {
    method: 'POST',
    body: JSON.stringify({ group_ids: groupIds, reason }),
  })
  return {
    archivedCount: Number(data.archived_count || 0),
    skipped: (data.skipped || []).map((item) => ({
      groupId: String(item.group_id || ''),
      reason: String(item.reason || ''),
    })),
    groups: (data.groups || []).map(mapGroup),
  }
}

export async function fetchGroup(groupId: string): Promise<{ group: MaterialGroup; photos: ReviewPhoto[] }> {
  const group = mapGroup(await api<BackendGroup>(`/local-test/groups/${encodeURIComponent(groupId)}`))
  return { group, photos: group.photos || [] }
}

export async function saveReview(
  groupId: string,
  status: TaskStatus,
  options: { note?: string; exceptionNote?: string } = {},
): Promise<MaterialGroup> {
  const group = await api<BackendGroup>(`/local-test/groups/${encodeURIComponent(groupId)}/review`, {
    method: 'PATCH',
    body: JSON.stringify({
      status,
      reviewer: currentActor(),
      note: options.note || '',
      exception_note: options.exceptionNote || '',
    }),
  })
  return mapGroup(group)
}

export async function classifyPhoto(groupId: string, photoId: string, category: string): Promise<ReviewPhoto> {
  const photo = await api<BackendPhoto>(
    `/local-test/groups/${encodeURIComponent(groupId)}/photos/${encodeURIComponent(photoId)}/category`,
    {
      method: 'PATCH',
      body: JSON.stringify({ category, reviewer: currentActor() }),
    },
  )
  return mapPhoto(photo)
}

export async function classifyPhotoWithGroup(
  groupId: string,
  photoId: string,
  category: string,
): Promise<{ photo: ReviewPhoto; group?: MaterialGroup }> {
  const data = await api<{ photo?: BackendPhoto; group?: BackendGroup } | BackendPhoto>(
    `/local-test/groups/${encodeURIComponent(groupId)}/photos/${encodeURIComponent(photoId)}/category?include_group=true`,
    {
      method: 'PATCH',
      body: JSON.stringify({ category, reviewer: currentActor() }),
    },
  )
  if ('photo' in data || 'group' in data) {
    return {
      photo: mapPhoto(data.photo || ({} as BackendPhoto)),
      group: data.group ? mapGroup(data.group) : undefined,
    }
  }
  return { photo: mapPhoto(data as BackendPhoto) }
}

export async function rescanPhotoBarcode(
  groupId: string,
  photoId: string,
  category = '',
): Promise<{ photo: ReviewPhoto; group?: MaterialGroup }> {
  const data = await api<{ photo?: BackendPhoto; group?: BackendGroup } | BackendPhoto>(
    `/local-test/groups/${encodeURIComponent(groupId)}/photos/${encodeURIComponent(photoId)}/barcode-rescan?include_group=true`,
    {
      method: 'POST',
      body: JSON.stringify({ reviewer: currentActor(), category }),
    },
  )
  if ('photo' in data || 'group' in data) {
    return {
      photo: mapPhoto(data.photo || ({} as BackendPhoto)),
      group: data.group ? mapGroup(data.group) : undefined,
    }
  }
  return { photo: mapPhoto(data as BackendPhoto) }
}

export async function confirmGroupBarcodeManually(
  groupId: string,
  payload: GroupBarcodeManualConfirmation,
): Promise<{ group?: MaterialGroup }> {
  const data = await api<{ group?: BackendGroup }>(
    `/local-test/groups/${encodeURIComponent(groupId)}/barcode-manual-confirm`,
    {
      method: 'POST',
      body: JSON.stringify({
        actor: currentActor(),
        meter_no: payload.meterNo,
        module_asset_no: payload.moduleAssetNo,
        collector: payload.collector,
        reason: payload.reason,
        photo_ids: payload.photoIds,
      }),
    },
  )
  return { group: data.group ? mapGroup(data.group) : undefined }
}

export async function deleteGroupPhoto(groupId: string, photoId: string): Promise<{ group?: MaterialGroup }> {
  const data = await api<{ group?: BackendGroup }>(
    `/local-test/groups/${encodeURIComponent(groupId)}/photos/${encodeURIComponent(photoId)}`,
    {
      method: 'DELETE',
      body: JSON.stringify({ reviewer: currentActor() }),
    },
  )
  return { group: data.group ? mapGroup(data.group) : undefined }
}

export async function resetGroupToUnconstructed(groupId: string, reason = ''): Promise<{ group?: MaterialGroup }> {
  const data = await api<{ group?: BackendGroup }>(
    `/local-test/groups/${encodeURIComponent(groupId)}/reset-unconstructed`,
    {
      method: 'PATCH',
      body: JSON.stringify({ actor: currentActor(), reason }),
    },
  )
  return { group: data.group ? mapGroup(data.group) : undefined }
}

export async function returnGroupToException(
  groupId: string,
  payload: { category: string; note: string },
): Promise<{ group?: MaterialGroup; orderId?: string }> {
  const data = await api<{ group?: BackendGroup; order?: { id?: string | number } }>(
    `/local-test/groups/${encodeURIComponent(groupId)}/return-exception`,
    {
      method: 'PATCH',
      body: JSON.stringify({ actor: currentActor(), category: payload.category, note: payload.note }),
    },
  )
  return {
    group: data.group ? mapGroup(data.group) : undefined,
    orderId: data.order?.id ? String(data.order.id) : '',
  }
}

export async function fetchConstructionTasks(includeClosed = false, actor = currentActor()): Promise<ReviewTask[]> {
  const query = new URLSearchParams({
    include_closed: includeClosed ? 'true' : 'false',
  })
  if (actor) query.set('actor', actor)
  const data = await api<{ items: BackendTask[] }>(`/local-test/construction/tasks?${query.toString()}`)
  return (data.items || []).map(mapTask)
}

export async function openConstructionTask(taskId: string): Promise<ReviewTask> {
  const task = await api<BackendTask>(`/local-test/construction/tasks/${encodeURIComponent(taskId)}/open`, {
    method: 'PATCH',
    body: JSON.stringify({ actor: currentActor() }),
  })
  return mapTask(task)
}

export async function closeConstructionTask(taskId: string): Promise<ReviewTask> {
  const task = await api<BackendTask>(`/local-test/construction/tasks/${encodeURIComponent(taskId)}/close`, {
    method: 'PATCH',
    body: JSON.stringify({ actor: currentActor() }),
  })
  return mapTask(task)
}

export async function setConstructionTaskPriority(taskId: string, priority: boolean): Promise<ReviewTask> {
  const task = await api<BackendTask>(`/local-test/construction/tasks/${encodeURIComponent(taskId)}/priority`, {
    method: 'PATCH',
    body: JSON.stringify(priorityRequestBody(priority)),
  })
  return mapTask(task)
}

export async function downloadConstructionPriorityTemplate(): Promise<void> {
  const response = await fetchWithAuth('/local-test/construction/priority-template', { headers: authHeaders() })
  if (!response.ok) throw new Error(response.statusText || '下载模板失败')
  const blob = await response.blob()
  triggerBrowserDownload(
    blob,
    filenameFromDisposition(response.headers.get('Content-Disposition') || '', '终端优先施工导入模板.xlsx'),
  )
}

async function submitConstructionPriorityImport(file: File, confirm: boolean): Promise<ConstructionPriorityImportResult> {
  const form = new FormData()
  form.append('file', file)
  const response = await fetchWithAuth(`/local-test/construction/priority-import?confirm=${confirm ? 'true' : 'false'}`, {
    method: 'POST',
    headers: formHeaders(),
    body: form,
  })
  const payload = (await response.json()) as ApiEnvelope<ConstructionPriorityImportResult>
  if (!response.ok || payload.error) throw createApiRequestError(response, payload)
  if (!payload.data) throw new Error('导入响应为空')
  if (confirm) emitDataMutated('form:/local-test/construction/priority-import')
  return payload.data
}

export function previewConstructionPriorityImport(file: File): Promise<ConstructionPriorityImportResult> {
  return submitConstructionPriorityImport(file, false)
}

export function confirmConstructionPriorityImport(file: File): Promise<ConstructionPriorityImportResult> {
  return submitConstructionPriorityImport(file, true)
}

export async function assignConstructionTask(
  taskId: string,
  constructor: string,
  note = '',
  dueDate = '',
): Promise<ReviewTask> {
  const task = await api<BackendTask>(`/local-test/construction/tasks/${encodeURIComponent(taskId)}/assign`, {
    method: 'PATCH',
    body: JSON.stringify({
      actor: currentActor(),
      constructor,
      note,
      due_date: dueDate,
    }),
  })
  return mapTask(task)
}

export async function unassignConstructionTask(taskId: string): Promise<ReviewTask> {
  const task = await api<BackendTask>(`/local-test/construction/tasks/${encodeURIComponent(taskId)}/unassign`, {
    method: 'PATCH',
    body: JSON.stringify({ actor: currentActor() }),
  })
  return mapTask(task)
}

export async function releaseConstructionTask(taskId: string): Promise<ReviewTask> {
  const task = await api<BackendTask>(`/local-test/construction/tasks/${encodeURIComponent(taskId)}/release`, {
    method: 'POST',
    body: JSON.stringify({ actor: currentActor() }),
  })
  return mapTask(task)
}

export async function fetchConstructionTaskGroups(taskId: string, status = ''): Promise<MaterialGroup[]> {
  const query = new URLSearchParams({
    limit: '1000',
    summary: 'true',
  })
  if (status) query.set('status', status)
  const data = await api<{ total: number; items: BackendGroup[] }>(
    `/local-test/construction/tasks/${encodeURIComponent(taskId)}/groups?${query.toString()}`,
  )
  return (data.items || []).map(mapGroup)
}

export async function fetchConstructionExceptionOrders(taskId = '', actor = currentActor()): Promise<ConstructionExceptionOrder[]> {
  const query = new URLSearchParams()
  if (actor) query.set('actor', actor)
  if (taskId) query.set('task_id', taskId)
  const data = await api<{ items: BackendConstructionExceptionOrder[] }>(
    `/local-test/construction/exception-orders?${query.toString()}`,
  )
  return (data.items || []).map(mapConstructionExceptionOrder)
}

export async function submitConstructionExceptionOrder(
  orderId: string,
  updates: { meterNo?: string; collector?: string; moduleAssetNo?: string },
  note = '现场已处理异常工单',
): Promise<{ order?: ConstructionExceptionOrder; group?: MaterialGroup }> {
  const data = await api<{ order?: BackendConstructionExceptionOrder; group?: BackendGroup }>(
    `/local-test/construction/exception-orders/${encodeURIComponent(orderId)}/submit`,
    {
      method: 'PATCH',
      body: JSON.stringify({
        actor: currentActor(),
        updates: {
          meter_no: updates.meterNo || '',
          collector: updates.collector || '',
          module_asset_no: updates.moduleAssetNo || '',
        },
        note,
      }),
    },
  )
  return {
    order: data.order ? mapConstructionExceptionOrder(data.order) : undefined,
    group: data.group ? mapGroup(data.group) : undefined,
  }
}

export async function assignConstructionExceptionOrder(
  orderId: string,
  constructor: string,
  note = '',
  dueDate = '',
): Promise<ConstructionExceptionOrder> {
  const data = await api<{ order?: BackendConstructionExceptionOrder }>(
    `/local-test/construction/exception-orders/${encodeURIComponent(orderId)}/assign`,
    {
      method: 'PATCH',
      body: JSON.stringify({
        actor: currentActor(),
        constructor,
        note,
        due_date: dueDate,
      }),
    },
  )
  return mapConstructionExceptionOrder(data.order || {})
}

export async function unassignConstructionExceptionOrder(orderId: string, reason = ''): Promise<ConstructionExceptionOrder> {
  const data = await api<{ order?: BackendConstructionExceptionOrder }>(
    `/local-test/construction/exception-orders/${encodeURIComponent(orderId)}/unassign`,
    {
      method: 'PATCH',
      body: JSON.stringify({ actor: currentActor(), reason }),
    },
  )
  return mapConstructionExceptionOrder(data.order || {})
}

export async function uploadConstructionBatch(
  groupId: string,
  payload: ConstructionUploadPayload,
): Promise<{ group?: MaterialGroup; uploadedUrls: string[] }> {
  const form = new FormData()
  form.append('actor', payload.actor)
  form.append('client_batch_id', payload.clientBatchId)
  if (payload.clientCompletedAt) form.append('client_completed_at', payload.clientCompletedAt)
  form.append('collector', payload.collector)
  form.append('module_asset_no', payload.moduleAssetNo)
  for (const photo of payload.photos) {
    form.append('photo_slots', photo.slot)
    form.append('client_photo_ids', photo.clientPhotoId)
    form.append('files', photo.file)
  }
  const data = await formApi<{ group?: BackendGroup; uploaded_urls?: string[] }>(
    `/local-test/construction/groups/${encodeURIComponent(groupId)}/upload-batch`,
    form,
  )
  return {
    group: data.group ? mapGroup(data.group) : undefined,
    uploadedUrls: data.uploaded_urls || [],
  }
}

export async function recordConstructionHeartbeat(payload: {
  actor: string
  taskId?: string | number
  occurredAt?: string
}): Promise<void> {
  await api('/local-test/construction/heartbeat', {
    method: 'POST',
    body: JSON.stringify({
      actor: payload.actor,
      task_id: payload.taskId || '',
      occurred_at: payload.occurredAt || new Date().toISOString(),
    }),
  })
}

export async function recordConstructionNonIdleEvent(payload: {
  eventType: 'group_draft_completed' | 'group_draft_deleted' | 'group_uploaded'
  actor: string
  taskId?: string | number
  groupId?: string
  clientBatchId?: string
  occurredAt?: string
}): Promise<void> {
  await api('/local-test/construction/non-idle-events', {
    method: 'POST',
    body: JSON.stringify({
      event_type: payload.eventType,
      actor: payload.actor,
      task_id: payload.taskId || '',
      group_id: payload.groupId || '',
      client_batch_id: payload.clientBatchId || '',
      occurred_at: payload.occurredAt || new Date().toISOString(),
    }),
  })
}

export async function fetchProjectSummary(
  options: { refresh?: boolean } = {},
): Promise<{ summary: ProjectSummary; paths: Record<string, unknown> }> {
  const query = options.refresh ? '?refresh=true' : ''
  const data = await api<{ summary: BackendSummary; paths?: Record<string, unknown> }>(`/local-test/summary${query}`)
  return { summary: mapSummary(data.summary || {}), paths: data.paths || {} }
}

export async function fetchPhotoBarcodeReviewGroups(
  status = 'unreadable',
  page = 1,
  pageSize = 20,
  query = '',
  signal?: AbortSignal,
): Promise<{ total: number; items: PhotoBarcodeReviewGroup[] }> {
  const safePage = Math.max(1, Math.floor(Number(page) || 1))
  const safePageSize = Math.max(1, Math.min(100, Math.floor(Number(pageSize) || 20)))
  const params = new URLSearchParams({
    status,
    limit: String(safePageSize),
    offset: String((safePage - 1) * safePageSize),
  })
  if (query.trim()) params.set('query', query.trim())
  const data = await api<{ total: number; items: BackendPhotoBarcodeReviewGroup[] }>(
    `/local-test/photo-barcode/review-groups?${params.toString()}`,
    { signal },
  )
  return {
    total: Number(data.total || 0),
    items: (data.items || []).map(mapPhotoBarcodeReviewGroup),
  }
}

export async function fetchInstallerWorkload(installer: string): Promise<InstallerWorkload> {
  const data = await api<BackendInstallerWorkload>(
    `/local-test/installers/${encodeURIComponent(installer)}/daily-workload`,
  )
  return {
    installer: data.installer || installer,
    items: (data.items || []).map((item) => ({
      date: item.date || '',
      groupCount: Number(item.group_count || 0),
      photoCount: Number(item.photo_count || 0),
      archivedCount: Number(item.archived_count || 0),
      exceptionCount: Number(item.exception_count || 0),
      unreviewedCount: Number(item.unreviewed_count || 0),
      startAt: String(item.start_at || ''),
      endAt: String(item.end_at || ''),
      startTime: String(item.start_time || ''),
      endTime: String(item.end_time || ''),
      workDurationMinutes: Number(item.work_duration_minutes || 0),
      workDurationHours: Number(item.work_duration_hours || 0),
      efficiencyDurationMinutes: Number(item.efficiency_duration_minutes ?? item.work_duration_minutes ?? 0),
      efficiencyDurationHours: Number(item.efficiency_duration_hours || 0),
      efficiencyDurationLabel: String(item.efficiency_duration_label || item.work_duration_label || '0分钟'),
      workDurationLabel: String(item.work_duration_label || '0分钟'),
      workDurationMinutesV2: Number(item.work_duration_minutes_v2 || 0),
      workDurationHoursV2: Number(item.work_duration_hours_v2 || 0),
      workDurationLabelV2: String(item.work_duration_label_v2 || '0分钟'),
      workDurationBaseMinutesV2: Number(item.work_duration_base_minutes_v2 || 0),
      workDurationDeltaMinutesV2: Number(item.work_duration_delta_minutes_v2 || 0),
      denseBonusMinutesV2: Number(item.dense_bonus_minutes_v2 || 0),
      denseBonusWindowsV2: (item.dense_bonus_windows_v2 || []).map((window) => ({
        startAt: String(window.start_at || ''),
        endAt: String(window.end_at || ''),
        startTime: String(window.start_time || ''),
        endTime: String(window.end_time || ''),
        gapCount: Number(window.gap_count || 0),
        underThreeCount: Number(window.under_three_count || 0),
        underFiveCount: Number(window.under_five_count || 0),
        bonusMinutes: Number(window.bonus_minutes || 0),
        rule: String(window.rule || ''),
      })),
      completionPerEffectiveHourV2: Number(item.completion_per_effective_hour_v2 || 0),
      weightedCompletionPerEffectiveHourV2: Number(item.weighted_completion_per_effective_hour_v2 || 0),
      workSpanMinutes: Number(item.work_span_minutes || 0),
      workSpanLabel: String(item.work_span_label || '0分钟'),
      breakThresholdMinutes: Number(item.break_threshold_minutes || 60),
      timepointCount: Number(item.timepoint_count || 0),
      completionCount: Number(item.completion_count || 0),
      completionPerEffectiveHour: Number(item.completion_per_effective_hour || 0),
      weightedCompletion: Number(item.weighted_completion || 0),
      weightedCompletionPerEffectiveHour: Number(item.weighted_completion_per_effective_hour || 0),
      attendanceWindowMinutes: Number(item.attendance_window_minutes || 0),
      onlineMinutes: Number(item.online_minutes || 0),
      countableOnlineMinutes: Number(item.countable_online_minutes || 0),
      onlineRatio: Number(item.online_ratio || 0),
      baseOnlineCoefficient: Number(item.base_online_coefficient ?? 1),
      idlePenaltyCoefficient: Number(item.idle_penalty_coefficient || 0),
      finalOnlineCoefficient: Number(item.final_online_coefficient ?? 1),
      fusedWorkDurationMinutes: Number(item.fused_work_duration_minutes ?? item.work_duration_minutes ?? 0),
      fusedWorkDurationHours: Number(item.fused_work_duration_hours || 0),
      fusedEfficiencyDurationMinutes: Number(
        item.fused_efficiency_duration_minutes ?? item.efficiency_duration_minutes ?? item.work_duration_minutes ?? 0,
      ),
      fusedEfficiencyDurationHours: Number(item.fused_efficiency_duration_hours || 0),
      fusedEfficiencyDurationLabel: String(
        item.fused_efficiency_duration_label || item.efficiency_duration_label || item.work_duration_label || '0分钟',
      ),
      fusedWorkDurationLabel: String(item.fused_work_duration_label || item.work_duration_label || '0分钟'),
      fusedWeightedCompletionPerEffectiveHour: Number(item.fused_weighted_completion_per_effective_hour || 0),
      idleSegments: (item.idle_segments || []).map((segment) => ({
        startAt: String(segment.start_at || ''),
        endAt: String(segment.end_at || ''),
        startTime: String(segment.start_time || ''),
        endTime: String(segment.end_time || ''),
        minutes: Number(segment.minutes || 0),
        hours: Number(segment.hours || 0),
        free: Boolean(segment.free),
        penaltyCoefficient: Number(segment.penalty_coefficient || 0),
      })),
      freeIdleSegmentUsed: Boolean(item.free_idle_segment_used),
      pendingNonIdleCount: Number(item.pending_non_idle_count || 0),
      confirmedNonIdleCount: Number(item.confirmed_non_idle_count || 0),
      onlineConfidence: String(item.online_confidence || ''),
      hourlySegments: (
        item.hourly_segments?.length
          ? item.hourly_segments
          : Array.from({ length: 24 }, (_, hour) => ({
              hour,
              label: `${String(hour).padStart(2, '0')}:00`,
              minutes: 0,
              duration_label: '0分钟',
            }))
      ).map((segment) => ({
          hour: Number(segment.hour || 0),
          label: String(segment.label || `${String(Number(segment.hour || 0)).padStart(2, '0')}:00`),
          minutes: Number(segment.minutes || 0),
          durationLabel: String(segment.duration_label || '0分钟'),
      })),
      twoHourSegments: (
        item.two_hour_segments?.length
          ? item.two_hour_segments
          : Array.from({ length: 12 }, (_, index) => ({
              hour: index * 2,
              start_hour: index * 2,
              end_hour: index * 2 + 2,
              efficiency_minutes: 0,
              efficiency_duration_label: '0分钟',
              label: `${String(index * 2).padStart(2, '0')}:00-${String(index * 2 + 2).padStart(2, '0')}:00`,
              minutes: 0,
              duration_label: '0分钟',
              completion_count: 0,
              weighted_completion: 0,
              completion_per_effective_hour: 0,
              weighted_completion_per_effective_hour: 0,
              address_count: 0,
              addresses: [],
            }))
      ).map((segment) => ({
        hour: Number(segment.hour ?? segment.start_hour ?? 0),
        startHour: Number(segment.start_hour ?? segment.hour ?? 0),
        endHour: Number(segment.end_hour ?? Number(segment.start_hour ?? segment.hour ?? 0) + 2),
        label: String(segment.label || ''),
        minutes: Number(segment.minutes || 0),
        efficiencyMinutes: Number(segment.efficiency_minutes ?? segment.minutes ?? 0),
        efficiencyDurationLabel: String(segment.efficiency_duration_label || segment.duration_label || '0分钟'),
        durationLabel: String(segment.duration_label || '0分钟'),
        completionCount: Number(segment.completion_count || 0),
        weightedCompletion: Number(segment.weighted_completion || 0),
        completionPerEffectiveHour: Number(segment.completion_per_effective_hour || 0),
        weightedCompletionPerEffectiveHour: Number(segment.weighted_completion_per_effective_hour || 0),
        addressCount: Number(segment.address_count || segment.addresses?.length || 0),
        addresses: (segment.addresses || []).map((address) => ({
          groupId: String(address.group_id || ''),
          meterNo: String(address.meter_no || ''),
          terminal: String(address.terminal || ''),
          address: String(address.address || ''),
          status: String(address.status || ''),
          photoCount: Number(address.photo_count || 0),
          completedAt: String(address.completed_at || ''),
          completedTime: String(address.completed_time || ''),
          addressClusterKey: String(address.address_cluster_key || ''),
          difficultyWeight: Number(address.difficulty_weight || 1),
          difficultyLabel: String(address.difficulty_label || '标准地址'),
          difficultyReasons: Array.isArray(address.difficulty_reasons) ? address.difficulty_reasons.filter(Boolean) : [],
          clusterSize: Number(address.cluster_size || 1),
        })),
      })),
      exceptionGroups: (item.exception_groups || []).map((group) => ({
        groupId: String(group.group_id || ''),
        meterNo: String(group.meter_no || ''),
        terminal: String(group.terminal || ''),
        address: String(group.address || ''),
        status: String(group.status || ''),
        exceptionNote: String(group.exception_note || ''),
        exceptionReasons: Array.isArray(group.exception_reasons) ? group.exception_reasons.filter(Boolean) : [],
        photoCount: Number(group.photo_count || 0),
      })),
    })),
  }
}

export async function fetchSystemStatus(): Promise<Record<string, unknown>> {
  return api<Record<string, unknown>>('/local-test/system/status')
}

export async function importTotalCatalog(file: File): Promise<Record<string, unknown>> {
  const form = new FormData()
  form.append('file', file)
  return formApi<Record<string, unknown>>('/local-test/catalog/total/import-xlsx', form)
}

export async function startScanImportJob(file: File): Promise<ImportJob> {
  const form = new FormData()
  form.append('file', file)
  const job = await formApi<BackendImportJob>('/local-test/scan/import-template-xlsx/jobs', form)
  return mapImportJob(job)
}

export async function fetchScanImportJob(jobId: string): Promise<ImportJob> {
  const job = await api<BackendImportJob>(`/local-test/scan/import-template-xlsx/jobs/${encodeURIComponent(jobId)}`)
  return mapImportJob(job)
}

export async function fetchUnmatchedRecords(
  query = '',
  page = 1,
  pageSize = 20,
): Promise<{ total: number; items: UnmatchedRecord[]; stats: UnmatchedListStats }> {
  const safePage = Math.max(1, Math.floor(Number(page) || 1))
  const safePageSize = Math.max(1, Math.min(1000, Math.floor(Number(pageSize) || 20)))
  const params = new URLSearchParams({
    limit: String(safePageSize),
    offset: String((safePage - 1) * safePageSize),
  })
  if (query.trim()) params.set('query', query.trim())
  const data = await api<{ total: number; items: BackendUnmatchedRecord[]; stats?: BackendUnmatchedListStats }>(
    `/local-test/unmatched?${params.toString()}`,
  )
  return {
    total: Number(data.total || 0),
    items: (data.items || []).map(mapUnmatchedRecord),
    stats: {
      pending: Number(data.stats?.pending || 0),
      assigned: Number(data.stats?.assigned || 0),
      outside: Number(data.stats?.outside || 0),
    },
  }
}

export async function fetchAllUnmatchedRecords(query = ''): Promise<UnmatchedRecord[]> {
  const pageSize = 500
  const records: UnmatchedRecord[] = []
  for (let page = 1; ; page += 1) {
    const result = await fetchUnmatchedRecords(query, page, pageSize)
    records.push(...result.items)
    if (!result.items.length || records.length >= result.total) break
  }
  return records
}

export async function fetchUnmatchedReview(unmatchedId: string): Promise<UnmatchedReviewDetail> {
  const data = await api<BackendUnmatchedReviewResponse>(
    `/local-test/unmatched/${encodeURIComponent(unmatchedId)}/review`,
  )
  return mapUnmatchedReview(data)
}

export async function scanGroupPhotoRegion(
  groupId: string,
  photoId: string,
  request: RegionScanRequest,
): Promise<RegionScanResult> {
  const data = await api<BackendRegionScanResult>(
    `/local-test/groups/${encodeURIComponent(groupId)}/photos/${encodeURIComponent(photoId)}/region-scan`,
    {
      method: 'POST',
      body: JSON.stringify(regionScanRequestBody(request)),
    },
  )
  return mapRegionScanResult(data)
}

export async function scanUnmatchedPhotoRegion(
  unmatchedId: string,
  photoId: string,
  request: RegionScanRequest,
): Promise<RegionScanResult> {
  const data = await api<BackendRegionScanResult>(
    `/local-test/unmatched/${encodeURIComponent(unmatchedId)}/photos/${encodeURIComponent(photoId)}/region-scan`,
    {
      method: 'POST',
      body: JSON.stringify(regionScanRequestBody(request)),
    },
  )
  return mapRegionScanResult(data)
}

export async function saveUnmatchedReview(
  unmatchedId: string,
  payload: {
    expectedVersion: number
    metadata?: { meterNo?: string; collector?: string; moduleAssetNo?: string }
    photoUpdates?: Array<{ id: string; category: string }>
    state?: 'pending' | 'reviewed'
  },
): Promise<UnmatchedReviewDetail> {
  const metadata: Record<string, string> = {}
  if (payload.metadata?.meterNo !== undefined) metadata.meter_no = payload.metadata.meterNo
  if (payload.metadata?.collector !== undefined) metadata.collector = payload.metadata.collector
  if (payload.metadata?.moduleAssetNo !== undefined) metadata.module_asset_no = payload.metadata.moduleAssetNo
  const data = await api<BackendUnmatchedReviewResponse>(
    `/local-test/unmatched/${encodeURIComponent(unmatchedId)}/review`,
    {
      method: 'PATCH',
      body: JSON.stringify({
        expected_version: payload.expectedVersion,
        metadata,
        photo_updates: (payload.photoUpdates || []).map((photo) => ({ id: photo.id, category: photo.category })),
        state: payload.state || 'pending',
      }),
    },
  )
  return mapUnmatchedReview(data)
}

export async function fetchUnmatchedReviewPhotoObjectUrl(unmatchedId: string, photoId: string): Promise<string> {
  const path = `/local-test/unmatched/${encodeURIComponent(unmatchedId)}/photos/${encodeURIComponent(photoId)}/content`
  const response = await fetchWithAuth(path, { headers: formHeaders() })
  if (!response.ok) throw createApiRequestError(response)
  const blob = await response.blob()
  if (!blob.type.startsWith('image/')) throw new Error('返回内容不是图片')
  return createVerifiedImageObjectUrl(blob)
}

export async function rescanUnmatchedReviewPhoto(
  unmatchedId: string,
  photoId: string,
  expectedVersion: number,
  category = '',
): Promise<UnmatchedReviewDetail> {
  const data = await api<BackendUnmatchedReviewResponse>(
    `/local-test/unmatched/${encodeURIComponent(unmatchedId)}/photos/${encodeURIComponent(photoId)}/rescan`,
    {
      method: 'POST',
      body: JSON.stringify({ expected_version: expectedVersion, category }),
    },
  )
  return mapUnmatchedReview(data)
}

export async function confirmUnmatchedReview(
  unmatchedId: string,
  expectedVersion: number,
  confirmed = true,
): Promise<UnmatchedReviewDetail> {
  const data = await api<BackendUnmatchedReviewResponse>(
    `/local-test/unmatched/${encodeURIComponent(unmatchedId)}/confirm`,
    {
      method: 'POST',
      body: JSON.stringify({ expected_version: expectedVersion, confirmed }),
    },
  )
  return mapUnmatchedReview(data)
}

export async function fetchUnmatchedMatchCandidates(
  unmatchedId: string,
  signal?: AbortSignal,
): Promise<UnmatchedMatchCandidate[]> {
  const data = await api<BackendUnmatchedMatchCandidates>(
    `/local-test/unmatched/${encodeURIComponent(unmatchedId)}/candidates`,
    { signal },
  )
  return (data.items || []).map(mapUnmatchedMatchCandidate)
}

export async function finalizeUnmatchedMatch(unmatchedId: string, candidateKey: string, expectedVersion: number) {
  const data = await api<{ group?: { id?: string } }>(`/local-test/unmatched/${encodeURIComponent(unmatchedId)}/finalize-match`, {
    method: 'POST',
    body: JSON.stringify({ candidate_key: candidateKey, expected_version: expectedVersion }),
  })
  return data.group?.id || ''
}

export async function fetchReplacementRecords(query = ''): Promise<ReplacementRecord[]> {
  const params = new URLSearchParams({ limit: '500' })
  if (query.trim()) params.set('query', query.trim())
  const data = await api<{ total: number; items: BackendReplacementRecord[] }>(
    `/local-test/replacements?${params.toString()}`,
  )
  return (data.items || []).map(mapReplacementRecord)
}

export async function createBlankUnmatchedRecord(): Promise<UnmatchedRecord> {
  const data = await api<{ record: BackendUnmatchedRecord }>('/local-test/unmatched/blank', {
    method: 'POST',
    body: JSON.stringify({ actor: currentActor() }),
  })
  return mapUnmatchedRecord(data.record || {})
}

export async function updateUnmatchedRecord(
  unmatchedId: string,
  expectedVersion: number,
  updates: Record<string, unknown>,
): Promise<UnmatchedRecord> {
  const data = await api<{ record?: BackendUnmatchedRecord }>(
    `/local-test/unmatched/${encodeURIComponent(unmatchedId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify({ expected_version: expectedVersion, updates }),
    },
  )
  return mapUnmatchedRecord(data.record || {})
}

export async function assignUnmatchedRecord(
  unmatchedId: string,
  expectedVersion: number,
  constructor: string,
  note = '',
  dueDate = '',
): Promise<UnmatchedRecord> {
  const data = await api<{ record?: BackendUnmatchedRecord }>(
    `/local-test/unmatched/${encodeURIComponent(unmatchedId)}/assign`,
    {
      method: 'PATCH',
      body: JSON.stringify({ expected_version: expectedVersion, constructor, note, due_date: dueDate }),
    },
  )
  return mapUnmatchedRecord(data.record || {})
}

export async function unassignUnmatchedRecord(
  unmatchedId: string,
  expectedVersion: number,
  reason = '',
): Promise<UnmatchedRecord> {
  const data = await api<{ record?: BackendUnmatchedRecord }>(
    `/local-test/unmatched/${encodeURIComponent(unmatchedId)}/unassign`,
    {
      method: 'PATCH',
      body: JSON.stringify({ expected_version: expectedVersion, reason }),
    },
  )
  return mapUnmatchedRecord(data.record || {})
}

export async function markUnmatchedOutsideProject(
  unmatchedId: string,
  expectedVersion: number,
  note = '',
): Promise<UnmatchedRecord> {
  const data = await api<{ record?: BackendUnmatchedRecord }>(
    `/local-test/unmatched/${encodeURIComponent(unmatchedId)}/outside-project`,
    {
      method: 'POST',
      body: JSON.stringify({ expected_version: expectedVersion, note }),
    },
  )
  return mapUnmatchedRecord(data.record || {})
}

export async function deleteUnmatchedRecord(
  unmatchedId: string,
  expectedVersion: number,
  reason = '',
): Promise<UnmatchedRecord> {
  const data = await api<BackendUnmatchedRecord>(
    `/local-test/unmatched/${encodeURIComponent(unmatchedId)}/delete`,
    {
      method: 'POST',
      body: JSON.stringify({ expected_version: expectedVersion, reason }),
    },
  )
  return mapUnmatchedRecord(data || {})
}

export async function fetchExceptionGroups(reviewer = currentActor()): Promise<MaterialGroup[]> {
  const query = new URLSearchParams({ limit: '1000' })
  if (reviewer) query.set('reviewer', reviewer)
  const data = await api<{ total: number; items: BackendGroup[] }>(
    `/local-test/exception-groups?${query.toString()}`,
  )
  return (data.items || []).map(mapGroup)
}

export async function updateGroupMetadata(
  groupId: string,
  updates: Record<string, unknown>,
): Promise<MaterialGroup> {
  const result = await api<{ group?: BackendGroup } | BackendGroup>(
    `/local-test/groups/${encodeURIComponent(groupId)}/metadata`,
    {
      method: 'PATCH',
      body: JSON.stringify({ actor: currentActor(), updates }),
    },
  )
  return mapGroup('group' in result && result.group ? result.group : (result as BackendGroup))
}

export async function uploadGroupImages(
  groupId: string,
  payload: { collector: string; moduleAssetNo: string; creator: string; files: File[] },
): Promise<{ group?: MaterialGroup; uploadedUrls: string[] }> {
  const form = new FormData()
  form.append('actor', currentActor())
  form.append('collector', payload.collector)
  form.append('module_asset_no', payload.moduleAssetNo)
  form.append('creator', payload.creator)
  for (const file of payload.files) form.append('files', file)
  const data = await formApi<{ group?: BackendGroup; uploaded_urls?: string[] }>(
    `/local-test/groups/${encodeURIComponent(groupId)}/photos/upload-images`,
    form,
  )
  return {
    group: data.group ? mapGroup(data.group) : undefined,
    uploadedUrls: data.uploaded_urls || [],
  }
}

export function groupPhotoContentUrl(
  groupId: string,
  photoId: string,
  kind: 'thumbnail' | 'preview' | 'original' = 'preview',
): string {
  const params = new URLSearchParams({
    kind,
    team_id: currentTeamId(),
  })
  return `/local-test/groups/${encodeURIComponent(groupId)}/photos/${encodeURIComponent(photoId)}/content?${params.toString()}`
}

export async function fetchGroupPhotoObjectUrl(
  groupId: string,
  photoId: string,
  kind: 'thumbnail' | 'preview' | 'original' = 'preview',
  version = '',
  signal?: AbortSignal,
): Promise<string> {
  const url = `${groupPhotoContentUrl(groupId, photoId, kind)}${version ? `&v=${encodeURIComponent(version)}` : ''}`
  const response = await fetchWithAuth(url, { headers: formHeaders(), signal })
  if (!response.ok) {
    throw new Error(response.statusText || `HTTP ${response.status}`)
  }
  const blob = await response.blob()
  if (!blob.type.startsWith('image/')) {
    throw new Error('图片接口返回内容不是图片')
  }
  return createVerifiedImageObjectUrl(blob)
}

async function createVerifiedImageObjectUrl(blob: Blob): Promise<string> {
  if (!blob.size) {
    throw new Error('图片内容为空')
  }
  const objectUrl = URL.createObjectURL(blob)
  if (typeof Image === 'undefined') {
    return objectUrl
  }
  try {
    await new Promise<void>((resolve, reject) => {
      const image = new Image()
      const timer = window.setTimeout(() => {
        image.onload = null
        image.onerror = null
        reject(new Error('图片解码超时'))
      }, 10000)
      image.onload = () => {
        window.clearTimeout(timer)
        if (image.naturalWidth > 0 && image.naturalHeight > 0) {
          if (looksLikeBlankOrPlaceholderImage(image)) {
            reject(new Error('图片内容疑似空白'))
            return
          }
          resolve()
          return
        }
        reject(new Error('图片尺寸异常'))
      }
      image.onerror = () => {
        window.clearTimeout(timer)
        reject(new Error('图片无法解码'))
      }
      image.src = objectUrl
    })
    return objectUrl
  } catch (error) {
    URL.revokeObjectURL(objectUrl)
    throw error
  }
}

function looksLikeBlankOrPlaceholderImage(image: HTMLImageElement): boolean {
  if (typeof document === 'undefined') {
    return false
  }
  try {
    const canvas = document.createElement('canvas')
    canvas.width = 64
    canvas.height = 64
    const context = canvas.getContext('2d', { willReadFrequently: true })
    if (!context) {
      return false
    }
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data
    let visiblePixels = 0
    let transparentPixels = 0
    let lumaSum = 0
    let lumaSquareSum = 0
    let grayPixels = 0
    let brightPixels = 0
    for (let index = 0; index < pixels.length; index += 4) {
      const alpha = pixels[index + 3]
      if (alpha < 8) {
        transparentPixels += 1
        continue
      }
      const red = pixels[index]
      const green = pixels[index + 1]
      const blue = pixels[index + 2]
      const luma = 0.2126 * red + 0.7152 * green + 0.0722 * blue
      visiblePixels += 1
      lumaSum += luma
      lumaSquareSum += luma * luma
      if (Math.abs(red - green) < 3 && Math.abs(green - blue) < 3) {
        grayPixels += 1
      }
      if (luma > 245) {
        brightPixels += 1
      }
    }
    const totalPixels = canvas.width * canvas.height
    if (!visiblePixels) {
      return true
    }
    const mean = lumaSum / visiblePixels
    const variance = Math.max(0, lumaSquareSum / visiblePixels - mean * mean)
    const stddev = Math.sqrt(variance)
    const transparentRatio = transparentPixels / totalPixels
    const grayRatio = grayPixels / visiblePixels
    const brightRatio = brightPixels / visiblePixels
    return (
      transparentRatio > 0.95 ||
      stddev < 3 ||
      (brightRatio > 0.98 && stddev < 8) ||
      (grayRatio > 0.98 && stddev < 5 && mean > 80 && mean < 245)
    )
  } catch {
    return false
  }
}

function filenameFromDisposition(disposition: string, fallbackName: string) {
  return parseContentDispositionFilename(disposition, fallbackName)
}

function triggerBrowserDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export async function fetchCollectorTransferRuns(projectId = ''): Promise<CollectorTransferRun[]> {
  const query = new URLSearchParams()
  if (projectId) query.set('project_id', projectId)
  const suffix = query.size ? `?${query.toString()}` : ''
  return api<CollectorTransferRun[]>(`/collector-transfer/runs${suffix}`)
}

export async function createCollectorTransferRun(projectId: string, name: string): Promise<CollectorTransferRun> {
  return api<CollectorTransferRun>('/collector-transfer/runs', {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId, name }),
  })
}

export async function fetchCollectorTransferRun(runId: string): Promise<CollectorWorkbenchSummary> {
  return api<CollectorWorkbenchSummary>(`/collector-transfer/runs/${encodeURIComponent(runId)}`)
}

export async function scanProjectCollector(
  projectId: string,
  collectorNo: string,
): Promise<CollectorInventoryDecision> {
  return api<CollectorInventoryDecision>(
    '/collector-transfer/inventory/scan',
    {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, collector_no: collectorNo }),
    },
  )
}

export async function registerProjectCollector(
  projectId: string,
  collectorNo: string,
  file: File,
): Promise<CollectorPhotoRegistration> {
  const form = new FormData()
  form.append('project_id', projectId)
  form.append('collector_no', collectorNo)
  form.append('file', file)
  return formApi<CollectorPhotoRegistration>('/collector-transfer/inventory', form)
}

export async function fetchProjectCollectorInventory(
  projectId: string,
): Promise<CollectorInventoryPage> {
  const query = new URLSearchParams({ project_id: projectId })
  return api<CollectorInventoryPage>(`/collector-transfer/inventory?${query.toString()}`)
}

export async function allocateCollectorPool(runId: string): Promise<CollectorAllocationResult> {
  return api<CollectorAllocationResult>(`/collector-transfer/runs/${encodeURIComponent(runId)}/allocate`, { method: 'POST' })
}

export async function fetchCollectorWorkbench(runId: string): Promise<CollectorWorkbenchSummary> {
  return api<CollectorWorkbenchSummary>(
    `/collector-transfer/runs/${encodeURIComponent(runId)}/workbench`,
  )
}

export async function fetchCollectorTerminalWorkbench(
  runId: string,
  terminalId: string,
): Promise<CollectorTerminalWorkbench> {
  return api<CollectorTerminalWorkbench>(
    `/collector-transfer/runs/${encodeURIComponent(runId)}/workbench/${encodeURIComponent(terminalId)}`,
  )
}

export async function setCollectorWorkbenchItemCompleted(
  itemId: string,
  completed: boolean,
): Promise<CollectorWorkbenchItemStatus> {
  return api<CollectorWorkbenchItemStatus>(`/collector-transfer/workbench/items/${encodeURIComponent(itemId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ completed }),
  })
}

export async function fetchGlobalCollectorTerminals(params: {
  query?: string
  state?: string
  page?: number
  pageSize?: number
  includeBlocked?: boolean
} = {}): Promise<GlobalCollectorTerminalPage> {
  const query = new URLSearchParams()
  if (params.query) query.set('query', params.query)
  if (params.state) query.set('state', params.state)
  if (params.page) query.set('page', String(params.page))
  if (params.pageSize) query.set('page_size', String(params.pageSize))
  if (params.includeBlocked) query.set('include_blocked', 'true')
  const suffix = query.size ? `?${query.toString()}` : ''
  return api<GlobalCollectorTerminalPage>(`/collector-transfer/workbench/terminals${suffix}`)
}

export async function openGlobalCollectorTerminal(candidate: Pick<GlobalCollectorTerminalCandidate, 'terminal_key' | 'project_id' | 'terminal_code' | 'source_revision'>): Promise<GlobalCollectorTerminalOpenResult> {
  return api<GlobalCollectorTerminalOpenResult>('/collector-transfer/workbench/terminals/open', {
    method: 'POST',
    body: JSON.stringify({
      terminal_key: candidate.terminal_key,
      project_id: candidate.project_id,
      terminal_code: candidate.terminal_code,
      source_revision: candidate.source_revision,
    }),
  })
}

export async function openReviewWorkbenchTerminal(candidate: Pick<GlobalCollectorTerminalCandidate, 'terminal_key' | 'source_revision'>): Promise<ReviewWorkbenchOpenResult> {
  return api<ReviewWorkbenchOpenResult>('/collector-transfer/review-workbench/terminals/open', {
    method: 'POST',
    body: JSON.stringify({ terminal_key: candidate.terminal_key, source_revision: candidate.source_revision }),
  })
}

export async function fetchGlobalCollectorTerminal(terminalId: string): Promise<GlobalCollectorTerminalDetail> {
  return api<GlobalCollectorTerminalDetail>(`/collector-transfer/workbench/terminals/${encodeURIComponent(terminalId)}`)
}

export async function replaceGlobalTerminalMissing(terminalId: string): Promise<GlobalCollectorTerminalReplacementResult> {
  return api<GlobalCollectorTerminalReplacementResult>(`/collector-transfer/workbench/terminals/${encodeURIComponent(terminalId)}/replace-missing`, { method: 'POST' })
}

export async function refreshGlobalCollectorTerminal(terminalId: string): Promise<GlobalCollectorTerminalOpenResult> {
  return api<GlobalCollectorTerminalOpenResult>(`/collector-transfer/workbench/terminals/${encodeURIComponent(terminalId)}/refresh`, { method: 'POST' })
}

export async function rollbackCollectorAssignment(assignmentId: string): Promise<void> {
  await api(`/collector-transfer/assignments/${encodeURIComponent(assignmentId)}/rollback`, { method: 'POST' })
}
