import { mockGroups, mockPhotos, mockProjects, mockTasks, mockUser } from './mock'
import type {
  AuthConfig,
  ConstructionExceptionOrder,
  ConstructionUploadPayload,
  CurrentUser,
  ImportJob,
  InstallerWorkload,
  MaterialGroup,
  Project,
  ProjectSummary,
  ReviewPhoto,
  ReviewTask,
  TaskStatus,
  UnmatchedRecord,
  UserAccount,
  UserRole,
} from './types'

type ApiEnvelope<T> = {
  data?: T
  error?: { message?: string }
  detail?: string
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
  review_rate?: number
  construction_enabled?: boolean
  construction_claimed_by?: string
  construction_claimed_by_name?: string
  assigned_constructor?: string
  assigned_constructor_name?: string
  construction_uploaded_count?: number
  construction_unbuilt_count?: number
  construction_exception_count?: number
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
  construction_collector?: string
  construction_module_asset_no?: string
  construction_status?: string
  exception_order_id?: string
  photos?: BackendPhoto[]
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
  installer_distribution?: Array<{ installer?: string; group_count?: number; share?: number }>
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
    work_span_minutes?: number
    work_span_label?: string
    break_threshold_minutes?: number
    timepoint_count?: number
    completion_count?: number
    completion_per_effective_hour?: number
    weighted_completion?: number
    weighted_completion_per_effective_hour?: number
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

function readLegacySession(): LegacySession | null {
  try {
    return JSON.parse(localStorage.getItem('module_manager_session') || 'null') as LegacySession | null
  } catch {
    return null
  }
}

export function currentActor() {
  const session = readLegacySession()
  return session?.user?.username || localStorage.getItem('module_manager_reviewer') || 'reviewer'
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

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = String(init.method || 'GET').toUpperCase()
  const response = await fetch(path, {
    ...init,
    headers: {
      ...authHeaders(),
      ...(init.headers || {}),
    },
  })
  const payload = (await response.json()) as ApiEnvelope<T>
  if (!response.ok || payload.error) {
    throw new Error(payload.detail || payload.error?.message || response.statusText)
  }
  if (method !== 'GET' && method !== 'HEAD') emitDataMutated(`api:${method}:${path}`)
  return payload.data as T
}

async function formApi<T>(path: string, formData: FormData): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: formHeaders(),
    body: formData,
  })
  const payload = (await response.json()) as ApiEnvelope<T>
  if (!response.ok || payload.error) {
    throw new Error(payload.detail || payload.error?.message || response.statusText)
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
  if (username === 'admin') return 'admin'
  if (username.includes('constructor') || username.includes('施工')) return 'constructor'
  return 'reviewer'
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
    constructionClaimedBy: raw.construction_claimed_by || '',
    constructionClaimedByName: raw.construction_claimed_by_name || '',
    assignedConstructor: raw.assigned_constructor || raw.construction_claimed_by || '',
    assignedConstructorName: raw.assigned_constructor_name || raw.construction_claimed_by_name || '',
    constructionUploadedCount: Number(raw.construction_uploaded_count || raw.uploaded_count || 0),
    constructionUnbuiltCount: Number(raw.construction_unbuilt_count || Math.max(renovationCount - uploadedCount, 0)),
    constructionExceptionCount: Number(raw.construction_exception_count || 0),
  }
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
  }
}

function mapGroup(raw: BackendGroup): MaterialGroup {
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
    constructionCollector: raw.construction_collector || '',
    constructionModuleAssetNo: raw.construction_module_asset_no || '',
    constructionStatus: raw.construction_status || '',
    exceptionOrderId: raw.exception_order_id || '',
    photos: (raw.photos || []).map(mapPhoto),
  }
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
  if (!session?.user) return mockUser
  const username = session.user.username || session.user.name || 'reviewer'
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
  await delay(60)
  return mockProjects
}

export async function fetchTasks(): Promise<ReviewTask[]> {
  const data = await api<{ items: BackendTask[] }>('/local-test/tasks')
  return (data.items || []).map(mapTask)
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
  try {
    const data = await api<{ total: number; items: BackendGroup[] }>(
      `/local-test/tasks/${encodeURIComponent(taskId)}/groups?limit=1000&scan_only=false&summary=true`,
    )
    return (data.items || []).map(mapGroup)
  } catch {
    return mockGroups.filter((group) => group.taskId === taskId)
  }
}

export async function fetchGroup(groupId: string): Promise<{ group: MaterialGroup; photos: ReviewPhoto[] }> {
  try {
    const group = mapGroup(await api<BackendGroup>(`/local-test/groups/${encodeURIComponent(groupId)}`))
    return { group, photos: group.photos || [] }
  } catch {
    const group = mockGroups.find((item) => item.id === groupId) || mockGroups[0]
    return { group, photos: mockPhotos }
  }
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

export async function fetchConstructionTasks(includeClosed = false): Promise<ReviewTask[]> {
  const data = await api<{ items: BackendTask[] }>(
    `/local-test/construction/tasks?actor=${encodeURIComponent(currentActor())}&include_closed=${includeClosed ? 'true' : 'false'}`,
  )
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

export async function fetchProjectSummary(): Promise<{ summary: ProjectSummary; paths: Record<string, unknown> }> {
  const data = await api<{ summary: BackendSummary; paths?: Record<string, unknown> }>('/local-test/summary')
  return { summary: mapSummary(data.summary || {}), paths: data.paths || {} }
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
      workDurationLabel: String(item.work_duration_label || '0分钟'),
      workSpanMinutes: Number(item.work_span_minutes || 0),
      workSpanLabel: String(item.work_span_label || '0分钟'),
      breakThresholdMinutes: Number(item.break_threshold_minutes || 60),
      timepointCount: Number(item.timepoint_count || 0),
      completionCount: Number(item.completion_count || 0),
      completionPerEffectiveHour: Number(item.completion_per_effective_hour || 0),
      weightedCompletion: Number(item.weighted_completion || 0),
      weightedCompletionPerEffectiveHour: Number(item.weighted_completion_per_effective_hour || 0),
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

export async function fetchUnmatchedRecords(query = ''): Promise<UnmatchedRecord[]> {
  const params = new URLSearchParams({ limit: '500' })
  if (query.trim()) params.set('query', query.trim())
  const data = await api<{ total: number; items: BackendUnmatchedRecord[] }>(`/local-test/unmatched?${params.toString()}`)
  return (data.items || []).map(mapUnmatchedRecord)
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
  updates: Record<string, unknown>,
): Promise<UnmatchedRecord> {
  const data = await api<{ record?: BackendUnmatchedRecord }>(
    `/local-test/unmatched/${encodeURIComponent(unmatchedId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify({ actor: currentActor(), updates }),
    },
  )
  return mapUnmatchedRecord(data.record || {})
}

export async function assignUnmatchedRecord(
  unmatchedId: string,
  constructor: string,
  note = '',
  dueDate = '',
): Promise<UnmatchedRecord> {
  const data = await api<{ record?: BackendUnmatchedRecord }>(
    `/local-test/unmatched/${encodeURIComponent(unmatchedId)}/assign`,
    {
      method: 'PATCH',
      body: JSON.stringify({ actor: currentActor(), constructor, note, due_date: dueDate }),
    },
  )
  return mapUnmatchedRecord(data.record || {})
}

export async function unassignUnmatchedRecord(unmatchedId: string, reason = ''): Promise<UnmatchedRecord> {
  const data = await api<{ record?: BackendUnmatchedRecord }>(
    `/local-test/unmatched/${encodeURIComponent(unmatchedId)}/unassign`,
    {
      method: 'PATCH',
      body: JSON.stringify({ actor: currentActor(), reason }),
    },
  )
  return mapUnmatchedRecord(data.record || {})
}

export async function markUnmatchedOutsideProject(unmatchedId: string, note = ''): Promise<UnmatchedRecord> {
  const data = await api<{ record?: BackendUnmatchedRecord }>(
    `/local-test/unmatched/${encodeURIComponent(unmatchedId)}/outside-project`,
    {
      method: 'POST',
      body: JSON.stringify({ actor: currentActor(), note }),
    },
  )
  return mapUnmatchedRecord(data.record || {})
}

export async function deleteUnmatchedRecord(unmatchedId: string, reason = ''): Promise<UnmatchedRecord> {
  const data = await api<BackendUnmatchedRecord>(
    `/local-test/unmatched/${encodeURIComponent(unmatchedId)}/delete`,
    {
      method: 'POST',
      body: JSON.stringify({ actor: currentActor(), reason }),
    },
  )
  return mapUnmatchedRecord(data || {})
}

export async function rematchUnmatchedRecord(
  unmatchedId: string,
  payload: {
    meterNo?: string
    oldMeterNo?: string
    terminal?: string
    updates?: Record<string, unknown>
  },
): Promise<{ matched: boolean; record?: UnmatchedRecord; group?: MaterialGroup }> {
  const data = await api<{ matched?: boolean; record?: BackendUnmatchedRecord; group?: BackendGroup }>(
    `/local-test/unmatched/${encodeURIComponent(unmatchedId)}/rematch`,
    {
      method: 'POST',
      body: JSON.stringify({
        actor: currentActor(),
        meter_no: payload.meterNo || '',
        old_meter_no: payload.oldMeterNo || '',
        terminal: payload.terminal || '',
        updates: payload.updates || {},
      }),
    },
  )
  return {
    matched: Boolean(data.matched || data.group),
    record: data.record ? mapUnmatchedRecord(data.record) : undefined,
    group: data.group ? mapGroup(data.group) : undefined,
  }
}

export async function fetchExceptionGroups(): Promise<MaterialGroup[]> {
  const data = await api<{ total: number; items: BackendGroup[] }>(
    `/local-test/exception-groups?limit=1000&reviewer=${encodeURIComponent(currentActor())}`,
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
): Promise<string> {
  const url = `${groupPhotoContentUrl(groupId, photoId, kind)}${version ? `&v=${encodeURIComponent(version)}` : ''}`
  const response = await fetch(url, { headers: formHeaders() })
  if (!response.ok) {
    throw new Error(response.statusText || `HTTP ${response.status}`)
  }
  const blob = await response.blob()
  if (!blob.type.startsWith('image/')) {
    throw new Error('图片接口返回内容不是图片')
  }
  return URL.createObjectURL(blob)
}

type DeliveryPhotoManifest = {
  id?: string | number
  image_url?: string
  preview_url?: string
  delivery_cache_url?: string
  category_label?: string
  archive_filename?: string
}

type DeliveryGroupManifest = {
  id?: string | number
  terminal?: string
  address?: string
  meter_no?: string
  status?: string
  reviewer?: string
  photo_count?: number
  photos?: DeliveryPhotoManifest[]
}

type DeliveryManifest = {
  groups?: DeliveryGroupManifest[]
}

type DeliveryExportProgress = {
  text: string
  percent: number
}

function filenameFromDisposition(disposition: string, fallbackName: string) {
  const match = disposition.match(/filename="?([^"]+)"?/)
  return match?.[1] || fallbackName
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

async function downloadExcel(path: string, body: Record<string, unknown>, fallbackName: string): Promise<void> {
  const response = await fetch(path, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new Error(response.statusText || fallbackName)
  }
  const blob = await response.blob()
  triggerBrowserDownload(blob, filenameFromDisposition(response.headers.get('Content-Disposition') || '', fallbackName))
}

export async function exportTaskDetail(taskId: string): Promise<void> {
  await downloadExcel('/exports/task-detail', { task_id: Number(taskId) }, `task-detail-${taskId}.xlsx`)
}

export async function exportExceptionMeters(reviewer = ''): Promise<void> {
  const response = await fetch('/exports/exception-meters', {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ reviewer, team_id: currentTeamId() }),
  })
  if (!response.ok) {
    throw new Error(response.statusText || '导出异常表计失败')
  }
  const blob = await response.blob()
  triggerBrowserDownload(
    blob,
    filenameFromDisposition(response.headers.get('Content-Disposition') || '', `exception-meters-${Date.now()}.xlsx`),
  )
}

export async function exportProjectOutsideConstruction(): Promise<void> {
  await downloadExcel('/exports/project-outside', { team_id: currentTeamId() }, `project-outside-${Date.now()}.xlsx`)
}

const zipEncoder = new TextEncoder()
const deliveryDownloadConcurrency = 6

const crcTable = (() => {
  const table = new Uint32Array(256)
  for (let index = 0; index < 256; index += 1) {
    let value = index
    for (let bit = 0; bit < 8; bit += 1) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1
    table[index] = value >>> 0
  }
  return table
})()

function bytesLE(value: number, length: number) {
  const bytes = new Uint8Array(length)
  let remaining = value >>> 0
  for (let index = 0; index < length; index += 1) {
    bytes[index] = remaining & 0xff
    remaining = Math.floor(remaining / 256)
  }
  return bytes
}

function concatBytes(parts: Uint8Array[]) {
  const total = parts.reduce((sum, part) => sum + part.length, 0)
  const merged = new Uint8Array(total)
  let offset = 0
  for (const part of parts) {
    merged.set(part, offset)
    offset += part.length
  }
  return merged
}

function crc32(bytes: Uint8Array) {
  let crc = 0xffffffff
  for (const byte of bytes) crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8)
  return (crc ^ 0xffffffff) >>> 0
}

function dosTimestamp(date = new Date()) {
  const time = (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2)
  const dosDate = ((Math.max(1980, date.getFullYear()) - 1980) << 9) | ((date.getMonth() + 1) << 5) | Math.max(1, date.getDate())
  return { time, date: dosDate }
}

async function zipEntryBytes(data: Blob | Uint8Array | string) {
  if (data instanceof Uint8Array) return data
  if (data instanceof Blob) return new Uint8Array(await data.arrayBuffer())
  return zipEncoder.encode(String(data ?? ''))
}

async function createZipBlob(entries: Array<{ name: string; data: Blob | Uint8Array | string }>) {
  const localParts: Uint8Array[] = []
  const centralParts: Uint8Array[] = []
  const stamp = dosTimestamp()
  let offset = 0
  for (const entry of entries) {
    const nameBytes = zipEncoder.encode(entry.name.replace(/\\/g, '/'))
    const data = await zipEntryBytes(entry.data)
    const checksum = crc32(data)
    const size = data.length
    if (offset + size > 0xffffffff) throw new Error('当前浏览器导出超过 4GB，请按终端分批导出。')
    const localHeader = concatBytes([
      bytesLE(0x04034b50, 4),
      bytesLE(20, 2),
      bytesLE(0x0800, 2),
      bytesLE(0, 2),
      bytesLE(stamp.time, 2),
      bytesLE(stamp.date, 2),
      bytesLE(checksum, 4),
      bytesLE(size, 4),
      bytesLE(size, 4),
      bytesLE(nameBytes.length, 2),
      bytesLE(0, 2),
      nameBytes,
      data,
    ])
    localParts.push(localHeader)
    centralParts.push(
      concatBytes([
        bytesLE(0x02014b50, 4),
        bytesLE(20, 2),
        bytesLE(20, 2),
        bytesLE(0x0800, 2),
        bytesLE(0, 2),
        bytesLE(stamp.time, 2),
        bytesLE(stamp.date, 2),
        bytesLE(checksum, 4),
        bytesLE(size, 4),
        bytesLE(size, 4),
        bytesLE(nameBytes.length, 2),
        bytesLE(0, 2),
        bytesLE(0, 2),
        bytesLE(0, 2),
        bytesLE(0, 2),
        bytesLE(0, 4),
        bytesLE(offset, 4),
        nameBytes,
      ]),
    )
    offset += localHeader.length
  }
  const centralSize = centralParts.reduce((sum, part) => sum + part.length, 0)
  const end = concatBytes([
    bytesLE(0x06054b50, 4),
    bytesLE(0, 2),
    bytesLE(0, 2),
    bytesLE(entries.length, 2),
    bytesLE(entries.length, 2),
    bytesLE(centralSize, 4),
    bytesLE(offset, 4),
    bytesLE(0, 2),
  ])
  const toBlobPart = (bytes: Uint8Array): ArrayBuffer => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer
  return new Blob([...localParts.map(toBlobPart), ...centralParts.map(toBlobPart), toBlobPart(end)], { type: 'application/zip' })
}

function safePathPart(value: unknown, fallback: string) {
  const cleaned = String(value || fallback || '').replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').replace(/\s+/g, ' ').trim()
  return (cleaned || fallback || '未命名').slice(0, 96)
}

function csvCell(value: unknown) {
  const text = String(value ?? '')
  return `"${text.replace(/"/g, '""')}"`
}

function buildCsv(rows: unknown[][]) {
  return `\ufeff${rows.map((row) => row.map(csvCell).join(',')).join('\r\n')}`
}

function photoExportUrl(photo: DeliveryPhotoManifest) {
  return photo.delivery_cache_url || photo.preview_url || photo.image_url || ''
}

function imageExtension(photo: DeliveryPhotoManifest, blob: Blob) {
  const typeMap: Record<string, string> = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
    'image/bmp': '.bmp',
    'image/gif': '.gif',
  }
  const fromType = typeMap[String(blob.type || '').toLowerCase()]
  if (fromType) return fromType
  const path = String(photo.image_url || '').split('?', 1)[0].toLowerCase()
  const match = path.match(/\.(jpg|jpeg|png|webp|bmp|gif)$/)
  return match ? `.${match[1]}` : '.jpg'
}

async function fetchImageBlob(url: string) {
  const requestUrl = new URL(url, window.location.origin)
  const sameOrigin = requestUrl.origin === window.location.origin
  try {
    const response = await fetch(requestUrl.href, sameOrigin ? { headers: formHeaders() } : {})
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
    return await response.blob()
  } catch (directError) {
    if (sameOrigin) throw directError
    const proxyResponse = await fetch(`/local-test/photo-proxy?url=${encodeURIComponent(requestUrl.href)}`, {
      headers: formHeaders(),
    })
    if (!proxyResponse.ok) throw directError
    return await proxyResponse.blob()
  }
}

function uniqueName(folderNames: Set<string>, desiredName: string) {
  const dotIndex = desiredName.lastIndexOf('.')
  const base = dotIndex > 0 ? desiredName.slice(0, dotIndex) : desiredName
  const suffix = dotIndex > 0 ? desiredName.slice(dotIndex) : ''
  let candidate = desiredName
  let counter = 2
  while (folderNames.has(candidate)) {
    candidate = `${base}-${counter}${suffix}`
    counter += 1
  }
  folderNames.add(candidate)
  return candidate
}

async function runConcurrentJobs(jobs: Array<() => Promise<void>>, limit: number) {
  let cursor = 0
  const workers = Array.from({ length: Math.min(limit, jobs.length) }, async () => {
    while (cursor < jobs.length) {
      const job = jobs[cursor]
      cursor += 1
      await job()
    }
  })
  await Promise.all(workers)
}

export async function exportTerminalDeliveryPackage(options: {
  taskId: string
  terminal?: string
  reviewScope: 'reviewed' | 'all'
  onProgress?: (progress: DeliveryExportProgress) => void
}): Promise<{ downloaded: number; failed: number; groups: number }> {
  if (!options.taskId && !options.terminal) throw new Error('只支持单终端导出，请从终端任务行发起。')
  options.onProgress?.({ text: '准备清单...', percent: 2 })
  const params = new URLSearchParams()
  if (options.taskId) params.set('task_id', options.taskId)
  if (options.terminal) params.set('terminal', options.terminal)
  params.set('review_scope', options.reviewScope || 'reviewed')
  const manifest = await api<DeliveryManifest>(`/local-test/export-manifest/final-delivery?${params.toString()}`)
  const groups = manifest.groups || []
  if (!groups.length) {
    throw new Error(options.reviewScope === 'reviewed' ? '当前终端还没有已归档完成的资料。' : '当前终端没有可导出的资料。')
  }

  const entries: Array<{ name: string; data: Blob | Uint8Array | string }> = []
  const csvRows: unknown[][] = [[
    '终端',
    '安装地址',
    '表号',
    '资料组ID',
    '状态',
    '审阅人',
    '照片数',
    '导出照片数',
    '照片1分类',
    '照片1URL',
    '照片2分类',
    '照片2URL',
    '照片3分类',
    '照片3URL',
    '照片4分类',
    '照片4URL',
  ]]
  const downloadJobs: Array<() => Promise<void>> = []
  let downloaded = 0
  let failed = 0

  for (const group of groups) {
    const photos = (group.photos || []).filter((photo) => photoExportUrl(photo)).slice(0, 4)
    const row: unknown[] = [
      group.terminal || '',
      group.address || '',
      group.meter_no || '',
      group.id || '',
      group.status || '',
      group.reviewer || '',
      group.photo_count || 0,
      photos.length,
    ]
    for (let index = 0; index < 4; index += 1) {
      row.push(photos[index]?.category_label || '')
      row.push(photoExportUrl(photos[index] || {}) || '')
    }
    csvRows.push(row)
    if (!photos.length) continue
    const terminal = safePathPart(group.terminal, '未关联终端')
    const address = safePathPart(group.address || group.meter_no || group.id, '未填写地址')
    const folder = `${terminal}/${address}`
    const usedNames = new Set<string>()
    for (const [photoIndex, photo] of photos.entries()) {
      downloadJobs.push(async () => {
        const url = new URL(photoExportUrl(photo), window.location.origin).href
        try {
          const blob = await fetchImageBlob(url)
          const archiveName = safePathPart(photo.archive_filename || photo.category_label || `图片${photoIndex + 1}`, `图片${photoIndex + 1}`)
          const extension = imageExtension(photo, blob)
          const withoutExt = archiveName.replace(/\.(jpg|jpeg|png|webp|bmp|gif)$/i, '')
          const filename = uniqueName(usedNames, `${String(photoIndex + 1).padStart(2, '0')}-${withoutExt}${extension}`)
          entries.push({ name: `${folder}/${filename}`, data: blob })
          downloaded += 1
        } catch (error) {
          const filename = uniqueName(usedNames, `${String(photoIndex + 1).padStart(2, '0')}-下载失败.txt`)
          entries.push({
            name: `${folder}/${filename}`,
            data: `图片下载失败，请检查图片 URL 是否可访问。\r\n资料组：${group.id || ''}\r\n表号：${group.meter_no || ''}\r\nURL：${url}\r\n错误：${error instanceof Error ? error.message : String(error)}`,
          })
          failed += 1
        }
        const finished = downloaded + failed
        options.onProgress?.({
          text: `并发下载图片 ${finished}/${downloadJobs.length}`,
          percent: downloadJobs.length ? Math.max(5, Math.round((finished / downloadJobs.length) * 90)) : 50,
        })
      })
    }
  }

  if (downloadJobs.length) {
    options.onProgress?.({ text: `并发下载图片 0/${downloadJobs.length}`, percent: 5 })
    await runConcurrentJobs(downloadJobs, deliveryDownloadConcurrency)
  }
  entries.sort((left, right) => left.name.localeCompare(right.name, 'zh-Hans'))
  entries.unshift({ name: '清单表格.csv', data: buildCsv(csvRows) })
  options.onProgress?.({ text: '生成压缩包...', percent: 96 })
  const zip = await createZipBlob(entries)
  const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)
  const scopeName = safePathPart(options.terminal || groups[0]?.terminal || `task-${options.taskId}`, '终端')
  const scopeLabel = options.reviewScope === 'all' ? 'all' : 'reviewed'
  triggerBrowserDownload(zip, `终端-${scopeName}-${scopeLabel}-${stamp}.zip`)
  options.onProgress?.({ text: failed ? `压缩包已生成，${failed} 张图片下载失败` : `压缩包已生成，已下载 ${downloaded} 张图片`, percent: 100 })
  return { downloaded, failed, groups: groups.length }
}
