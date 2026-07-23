import { reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchExportCatalog, fetchExportJobs, fetchTerminalReadinessPage } from '@/api/services'
import type {
  ExportCatalogItem,
  ExportCenterPageSize,
  ExportCenterTab,
  ExportJobPage,
  TerminalReadinessPage,
} from '@/api/types'

export const EXPORT_CENTER_PAGE_SIZES = [20, 50, 100] as const
const MAX_EXPORT_CENTER_PAGE = 1000
const EXPORT_CENTER_JOB_TYPES_BY_TAB: Record<ExportCenterTab, readonly string[]> = {
  terminal: ['final_delivery'],
  device: ['device_terminal', 'device_meter', 'device_module', 'device_collector'],
  business: [
    'task_detail',
    'exception_meter',
    'exception_missing_photo',
    'replacement',
    'unmatched',
    'project_outside',
  ],
  statistics: ['barcode_review', 'installer_kpi', 'installer_daily_completion'],
}
const EXPORT_CENTER_JOB_STATUS_FILTERS = new Set(['pending', 'processing', 'succeeded', 'failed'])

export interface ExportCenterRouteQuery {
  tab: ExportCenterTab
  page: number
  pageSize: ExportCenterPageSize
  filter: string
}

const DEFAULT_QUERY: ExportCenterRouteQuery = {
  tab: 'terminal',
  page: 1,
  pageSize: 20,
  filter: '',
}

function first(value: unknown): string {
  return Array.isArray(value) ? String(value[0] || '') : String(value || '')
}

function parsePositiveInteger(value: unknown, fallback: number, max: number): number {
  const parsed = Number(first(value))
  if (!Number.isFinite(parsed) || !Number.isInteger(parsed) || parsed <= 0) {
    return fallback
  }
  return Math.min(parsed, max)
}

function pageSize(value: unknown): ExportCenterPageSize {
  const parsed = Number(first(value))
  return EXPORT_CENTER_PAGE_SIZES.includes(parsed as ExportCenterPageSize) ? (parsed as ExportCenterPageSize) : 20
}

function normalizeTab(value: unknown): ExportCenterTab {
  const tab = first(value)
  return ['terminal', 'device', 'business', 'statistics'].includes(tab) ? (tab as ExportCenterTab) : 'terminal'
}

function routeQueryToState(query: Record<string, unknown>): ExportCenterRouteQuery {
  return {
    tab: normalizeTab(query.tab),
    page: parsePositiveInteger(query.page, 1, MAX_EXPORT_CENTER_PAGE),
    pageSize: pageSize(query.page_size || query.pageSize),
    filter: first(query.filter || query.query),
  }
}

function serializeQuery(state: ExportCenterRouteQuery) {
  const query: Record<string, string> = {}
  if (state.tab !== DEFAULT_QUERY.tab) query.tab = state.tab
  if (state.page !== DEFAULT_QUERY.page) query.page = String(state.page)
  if (state.pageSize !== DEFAULT_QUERY.pageSize) query.page_size = String(state.pageSize)
  if (state.filter) query.filter = state.filter
  return query
}

function emptyTerminalPage(page: number, pageSizeValue: ExportCenterPageSize): TerminalReadinessPage {
  return {
    total: 0,
    page,
    pageSize: pageSizeValue,
    items: [],
  }
}

function emptyJobsPage(page: number, pageSizeValue: ExportCenterPageSize): ExportJobPage {
  return {
    total: 0,
    page,
    pageSize: pageSizeValue,
    items: [],
  }
}

function buildJobHistoryQuery(state: ExportCenterRouteQuery) {
  const filter = state.filter.trim().toLowerCase()
  const allowedJobTypes = EXPORT_CENTER_JOB_TYPES_BY_TAB[state.tab]
  return {
    page: state.page,
    pageSize: state.pageSize,
    category: state.tab,
    jobTypes: allowedJobTypes.includes(filter) ? [filter] : undefined,
    status: EXPORT_CENTER_JOB_STATUS_FILTERS.has(filter) ? [filter] : undefined,
  }
}

export function useExportCenterQuery() {
  const route = useRoute()
  const router = useRouter()
  const query = reactive<ExportCenterRouteQuery>(routeQueryToState(route.query as Record<string, unknown>))
  const catalog = ref<ExportCatalogItem[]>([])
  const terminalPage = ref<TerminalReadinessPage>(emptyTerminalPage(query.page, query.pageSize))
  const jobsPage = ref<ExportJobPage>(emptyJobsPage(query.page, query.pageSize))
  const loading = ref(false)
  const jobsLoading = ref(false)
  const errorMessage = ref('')
  let requestSerial = 0
  let controller: AbortController | null = null

  function replace(next: ExportCenterRouteQuery) {
    return router.replace({ query: serializeQuery(next) })
  }

  function setTab(tab: ExportCenterTab) {
    return replace({ ...query, tab, page: 1 })
  }

  function setPage(page: number) {
    return replace({ ...query, page: parsePositiveInteger(page, 1, MAX_EXPORT_CENTER_PAGE) })
  }

  function setPageSize(size: ExportCenterPageSize) {
    return replace({ ...query, page: 1, pageSize: size })
  }

  function setFilter(filter: string) {
    return replace({ ...query, page: 1, filter: String(filter || '').trim() })
  }

  async function loadData() {
    const serial = requestSerial + 1
    requestSerial = serial
    controller?.abort()
    controller = new AbortController()
    loading.value = true
    jobsLoading.value = true
    errorMessage.value = ''
    try {
      const [catalogItems, exportJobsPage, readinessPage] = await Promise.all([
        fetchExportCatalog(controller.signal),
        fetchExportJobs({ ...buildJobHistoryQuery(query), signal: controller.signal }),
        query.tab === 'terminal'
          ? fetchTerminalReadinessPage({
              page: query.page,
              pageSize: query.pageSize,
              filter: query.filter,
              signal: controller.signal,
            })
          : Promise.resolve(emptyTerminalPage(query.page, query.pageSize)),
      ])
      if (serial !== requestSerial) return
      catalog.value = catalogItems
      jobsPage.value = exportJobsPage
      terminalPage.value = readinessPage
    } catch (error) {
      if (serial !== requestSerial || (error instanceof DOMException && error.name === 'AbortError')) return
      errorMessage.value = error instanceof Error ? error.message : '导出中心加载失败'
      terminalPage.value = emptyTerminalPage(query.page, query.pageSize)
      jobsPage.value = emptyJobsPage(query.page, query.pageSize)
      catalog.value = []
    } finally {
      if (serial === requestSerial) {
        loading.value = false
        jobsLoading.value = false
      }
    }
  }

  function refresh() {
    return loadData()
  }

  watch(
    () => route.query,
    (value) => {
      Object.assign(query, routeQueryToState(value as Record<string, unknown>))
      void loadData()
    },
    { immediate: true },
  )

  return {
    query,
    catalog,
    terminalPage,
    jobsPage,
    loading,
    jobsLoading,
    errorMessage,
    setTab,
    setPage,
    setPageSize,
    setFilter,
    refresh,
  }
}
