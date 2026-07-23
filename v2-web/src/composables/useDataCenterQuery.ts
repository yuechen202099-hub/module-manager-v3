import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchDataCenterRows } from '@/api/services'
import type { DataCenterDataType, DataCenterPageSize, DataCenterRow } from '@/api/types'

export const DATA_CENTER_PAGE_SIZES = [20, 50, 100] as const

export interface DataCenterRouteQuery {
  page: number
  pageSize: 20 | 50 | 100
  dataType: DataCenterDataType
  constructionStatus: string
  archiveStatus: string
  barcodeStatus: string
  classificationStatus: string
  exceptionStatus: string
  installer: string
  dateFrom: string
  dateTo: string
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
  archiveStatus: 'all',
  barcodeStatus: 'all',
  classificationStatus: 'all',
  exceptionStatus: '',
  installer: '',
  dateFrom: '',
  dateTo: '',
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
  return {
    page,
    pageSize: pageSize(query.page_size || query.pageSize),
    dataType: ['all', 'group', 'unmatched'].includes(dataType) ? dataType as DataCenterDataType : 'all',
    constructionStatus: first(query.construction_status || query.constructionStatus) || 'all',
    archiveStatus: first(query.archive_status || query.archiveStatus) || 'all',
    barcodeStatus: first(query.barcode_status || query.barcodeStatus) || 'all',
    classificationStatus: first(query.classification_status || query.classificationStatus) || 'all',
    exceptionStatus: first(query.exception_status || query.exceptionStatus),
    installer: first(query.installer),
    dateFrom: first(query.date_from || query.dateFrom),
    dateTo: first(query.date_to || query.dateTo),
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
    ['archiveStatus', 'archive_status', state.archiveStatus],
    ['barcodeStatus', 'barcode_status', state.barcodeStatus],
    ['classificationStatus', 'classification_status', state.classificationStatus],
    ['exceptionStatus', 'exception_status', state.exceptionStatus],
    ['installer', 'installer', state.installer],
    ['dateFrom', 'date_from', state.dateFrom],
    ['dateTo', 'date_to', state.dateTo],
    ['terminal', 'terminal', state.terminal],
    ['keyword', 'keyword', state.keyword],
    ['sort', 'sort', state.sort],
    ['groupId', 'group_id', state.groupId],
  ]
  for (const [key, serialized, value] of entries) {
    if (value !== DEFAULT_QUERY[key] && value !== '') query[serialized] = String(value)
  }
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
    if (!query.review || !query.groupId || query.dataType === 'all') return null
    return {
      kind: query.dataType,
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
        archiveStatus: query.archiveStatus,
        barcodeStatus: query.barcodeStatus,
        classificationStatus: query.classificationStatus,
        exceptionStatus: query.exceptionStatus,
        installer: query.installer,
        dateFrom: query.dateFrom,
        dateTo: query.dateTo,
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
