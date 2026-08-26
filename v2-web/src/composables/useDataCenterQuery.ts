import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchDataCenterRows } from '@/api/services'
import type {
  DataCenterBarcodeFilterStatus,
  DataCenterBarcodeEligibility,
  DataCenterDataType,
  DataCenterInstallerSource,
  DataCenterPageSize,
  DataCenterRow,
  DataCenterTerminalFilterStatus,
} from '@/api/types'

export const DATA_CENTER_PAGE_SIZES = [20, 50, 100] as const

export interface DataCenterRouteQuery {
  page: number
  pageSize: 20 | 50 | 100
  dataType: DataCenterDataType
  constructionStatus: string
  terminalStatus: DataCenterTerminalFilterStatus
  archiveStatus: string
  barcodeStatus: DataCenterBarcodeFilterStatus
  barcodeEligibility: DataCenterBarcodeEligibility
  classificationStatus: string
  exceptionStatus: string
  installer: string
  installerSource: DataCenterInstallerSource
  hasPhotos: boolean
  dateFrom: string
  dateTo: string
  activityDateFrom: string
  activityDateTo: string
  terminal: string
  keyword: string
  sort: string
  groupId: string
  review: boolean
}

const DEFAULT_QUERY: DataCenterRouteQuery = {
  page: 1,
  pageSize: 20,
  dataType: 'all',
  constructionStatus: 'all',
  terminalStatus: 'all',
  archiveStatus: 'all',
  barcodeStatus: 'all',
  barcodeEligibility: 'all',
  classificationStatus: 'all',
  exceptionStatus: '',
  installer: '',
  installerSource: 'all',
  hasPhotos: false,
  dateFrom: '',
  dateTo: '',
  activityDateFrom: '',
  activityDateTo: '',
  terminal: '',
  keyword: '',
  sort: 'updated_desc',
  groupId: '',
  review: false,
}

function first(value: unknown): string {
  return Array.isArray(value) ? String(value[0] || '') : String(value || '')
}

function pageSize(value: unknown): DataCenterPageSize {
  const parsed = Number(first(value))
  return DATA_CENTER_PAGE_SIZES.includes(parsed as DataCenterPageSize) ? parsed as DataCenterPageSize : 20
}

function routeQueryToState(query: Record<string, unknown>): DataCenterRouteQuery {
  const page = Math.max(1, Math.floor(Number(first(query.page)) || 1))
  const dataType = first(query.data_type || query.dataType)
  const terminalStatus = first(query.terminal_status || query.terminalStatus)
  const barcodeStatus = first(query.barcode_status || query.barcodeStatus)
  const barcodeEligibility = first(query.barcode_eligibility || query.barcodeEligibility)
  const installerSource = first(query.installer_source || query.installerSource)
  return {
    page,
    pageSize: pageSize(query.page_size || query.pageSize),
    dataType: ['all', 'group', 'unmatched'].includes(dataType) ? dataType as DataCenterDataType : 'all',
    constructionStatus: first(query.construction_status || query.constructionStatus) || 'all',
    terminalStatus: ['all', 'completed', 'incomplete', 'pending_archive', 'archived'].includes(terminalStatus)
      ? terminalStatus as DataCenterTerminalFilterStatus
      : 'all',
    archiveStatus: first(query.archive_status || query.archiveStatus) || 'all',
    barcodeStatus: ['all', 'passed', 'manual', 'manual_confirmed', 'mismatched', 'failed', 'unreadable', 'ineligible', 'verified', 'needs_review'].includes(barcodeStatus)
      ? barcodeStatus as DataCenterBarcodeFilterStatus
      : 'all',
    barcodeEligibility: ['all', 'eligible', 'ineligible'].includes(barcodeEligibility)
      ? barcodeEligibility as DataCenterBarcodeEligibility
      : 'all',
    classificationStatus: first(query.classification_status || query.classificationStatus) || 'all',
    exceptionStatus: first(query.exception_status || query.exceptionStatus),
    installer: first(query.installer),
    installerSource: ['all', 'photo'].includes(installerSource) ? installerSource as DataCenterInstallerSource : 'all',
    hasPhotos: first(query.has_photos || query.hasPhotos) === '1',
    dateFrom: first(query.date_from || query.dateFrom),
    dateTo: first(query.date_to || query.dateTo),
    activityDateFrom: first(query.activity_date_from || query.activityDateFrom),
    activityDateTo: first(query.activity_date_to || query.activityDateTo),
    terminal: first(query.terminal),
    keyword: first(query.keyword || query.query),
    sort: first(query.sort) || 'updated_desc',
    groupId: first(query.group_id || query.groupId),
    review: first(query.review) === '1',
  }
}

function serializeQuery(state: DataCenterRouteQuery) {
  const query: Record<string, string> = {}
  const entries: Array<[keyof DataCenterRouteQuery, string, string | number | boolean]> = [
    ['page', 'page', state.page],
    ['pageSize', 'page_size', state.pageSize],
    ['dataType', 'data_type', state.dataType],
    ['constructionStatus', 'construction_status', state.constructionStatus],
    ['terminalStatus', 'terminal_status', state.terminalStatus],
    ['archiveStatus', 'archive_status', state.archiveStatus],
    ['barcodeStatus', 'barcode_status', state.barcodeStatus],
    ['barcodeEligibility', 'barcode_eligibility', state.barcodeEligibility],
    ['classificationStatus', 'classification_status', state.classificationStatus],
    ['exceptionStatus', 'exception_status', state.exceptionStatus],
    ['installer', 'installer', state.installer],
    ['installerSource', 'installer_source', state.installerSource],
    ['dateFrom', 'date_from', state.dateFrom],
    ['dateTo', 'date_to', state.dateTo],
    ['activityDateFrom', 'activity_date_from', state.activityDateFrom],
    ['activityDateTo', 'activity_date_to', state.activityDateTo],
    ['terminal', 'terminal', state.terminal],
    ['keyword', 'keyword', state.keyword],
    ['sort', 'sort', state.sort],
    ['groupId', 'group_id', state.groupId],
  ]
  for (const [key, serialized, value] of entries) {
    if (value !== DEFAULT_QUERY[key] && value !== '') query[serialized] = String(value)
  }
  if (state.hasPhotos) query.has_photos = '1'
  if (state.review) query.review = '1'
  return query
}

export function useDataCenterQuery() {
  const route = useRoute()
  const router = useRouter()
  const query = reactive<DataCenterRouteQuery>(routeQueryToState(route.query as Record<string, unknown>))
  const rows = ref<DataCenterRow[]>([])
  const total = ref(0)
  const loading = ref(false)
  const errorMessage = ref('')
  let requestSerial = 0
  let controller: AbortController | null = null

  const activeRow = computed<DataCenterRow | null>(() => {
    const matched = rows.value.find((row) => row.id === query.groupId)
    if (matched) return matched
    if (!query.review || !query.groupId) return null
    const fallbackKind = query.dataType === 'unmatched' ? 'unmatched' : 'group'
    return {
      kind: fallbackKind,
      id: query.groupId,
      terminal: '',
      meterNo: '',
      meterMatchKey: '',
      address: '',
      collector: '',
      moduleAssetNo: '',
      constructionCollector: '',
      constructionModuleAssetNo: '',
      installer: '',
      photoCount: 0,
      classificationStatus: '',
      classificationProgress: {},
      barcodeStatus: '',
      barcodeProgress: {},
      groupBarcodeMissingFields: [],
      constructionStatus: '',
      archiveStatus: '',
      exceptionStatus: '',
      reviewStatus: 'pending',
      updatedAt: '',
    }
  })

  function replace(next: DataCenterRouteQuery) {
    return router.replace({ query: serializeQuery(next) })
  }

  function setFilters(updates: Partial<DataCenterRouteQuery>) {
    return replace({ ...query, ...updates, page: 1 })
  }

  function setPage(page: number) {
    return replace({ ...query, page: Math.max(1, page) })
  }

  function setPageSize(size: DataCenterPageSize) {
    return replace({ ...query, page: 1, pageSize: size })
  }

  function openReview(row: DataCenterRow) {
    return replace({ ...query, groupId: row.id, dataType: row.kind, review: true })
  }

  function closeReview() {
    return replace({ ...query, groupId: '', review: false })
  }

  async function loadRows() {
    const serial = requestSerial + 1
    requestSerial = serial
    controller?.abort()
    controller = new AbortController()
    loading.value = true
    errorMessage.value = ''
    try {
      const page = await fetchDataCenterRows({
        dataType: query.dataType,
        constructionStatus: query.constructionStatus,
        terminalStatus: query.terminalStatus,
        archiveStatus: query.archiveStatus,
        barcodeStatus: query.barcodeStatus,
        barcodeEligibility: query.barcodeEligibility,
        classificationStatus: query.classificationStatus,
        exceptionStatus: query.exceptionStatus,
        installer: query.installer,
        installerSource: query.installerSource,
        hasPhotos: query.hasPhotos,
        dateFrom: query.dateFrom,
        dateTo: query.dateTo,
        activityDateFrom: query.activityDateFrom,
        activityDateTo: query.activityDateTo,
        terminal: query.terminal,
        keyword: query.keyword,
        page: query.page,
        pageSize: query.pageSize,
        sort: query.sort,
        signal: controller.signal,
      })
      if (serial !== requestSerial) return
      rows.value = page.items
      total.value = page.total
    } catch (error) {
      if (serial !== requestSerial || (error instanceof DOMException && error.name === 'AbortError')) return
      errorMessage.value = error instanceof Error ? error.message : '数据加载失败'
      rows.value = []
      total.value = 0
    } finally {
      if (serial === requestSerial) loading.value = false
    }
  }

  function refresh() {
    return loadRows()
  }

  watch(
    () => route.query,
    (value) => {
      Object.assign(query, routeQueryToState(value as Record<string, unknown>))
      void loadRows()
    },
    { immediate: true },
  )

  return {
    query,
    rows,
    total,
    loading,
    errorMessage,
    activeRow,
    setFilters,
    setPage,
    setPageSize,
    openReview,
    closeReview,
    refresh,
  }
}
