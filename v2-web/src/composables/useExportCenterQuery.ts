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
  terminalPage: number
  terminalPageSize: ExportCenterPageSize
  jobPage: number
  jobPageSize: ExportCenterPageSize
  filter: string
}

const DEFAULT_QUERY: ExportCenterRouteQuery = {
  tab: 'terminal',
  terminalPage: 1,
  terminalPageSize: 20,
  jobPage: 1,
  jobPageSize: 20,
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

function parsePageSize(value: unknown): ExportCenterPageSize {
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
    terminalPage: parsePositiveInteger(query.terminal_page || query.page, 1, MAX_EXPORT_CENTER_PAGE),
    terminalPageSize: parsePageSize(query.terminal_page_size || query.page_size || query.pageSize),
    jobPage: parsePositiveInteger(query.job_page, 1, MAX_EXPORT_CENTER_PAGE),
    jobPageSize: parsePageSize(query.job_page_size),
    filter: first(query.filter || query.query),
  }
}

function serializeQuery(state: ExportCenterRouteQuery) {
  const query: Record<string, string> = {}
  if (state.tab !== DEFAULT_QUERY.tab) query.tab = state.tab
  if (state.terminalPage !== DEFAULT_QUERY.terminalPage) query.terminal_page = String(state.terminalPage)
  if (state.terminalPageSize !== DEFAULT_QUERY.terminalPageSize) query.terminal_page_size = String(state.terminalPageSize)
  if (state.jobPage !== DEFAULT_QUERY.jobPage) query.job_page = String(state.jobPage)
  if (state.jobPageSize !== DEFAULT_QUERY.jobPageSize) query.job_page_size = String(state.jobPageSize)
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
    page: state.jobPage,
    pageSize: state.jobPageSize,
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
  const terminalPage = ref<TerminalReadinessPage>(emptyTerminalPage(query.terminalPage, query.terminalPageSize))
  const jobsPage = ref<ExportJobPage>(emptyJobsPage(query.jobPage, query.jobPageSize))
  const loading = ref(false)
  const jobsLoading = ref(false)
  const errorMessage = ref('')
  // requestSerial is split into terminalRequestSerial and jobsRequestSerial.
  let terminalRequestSerial = 0
  let jobsRequestSerial = 0
  let terminalController: AbortController | null = null
  let jobsController: AbortController | null = null

  function replace(next: ExportCenterRouteQuery) {
    return router.replace({ query: serializeQuery(next) })
  }

  function setTab(tab: ExportCenterTab) {
    return replace({ ...query, tab, terminalPage: 1, jobPage: 1 })
  }

  function setTerminalPage(page: number) {
    return replace({ ...query, terminalPage: parsePositiveInteger(page, 1, MAX_EXPORT_CENTER_PAGE) })
  }

  function setTerminalPageSize(size: ExportCenterPageSize) {
    return replace({ ...query, terminalPage: 1, terminalPageSize: parsePageSize(size) })
  }

  function setJobPage(page: number) {
    return replace({ ...query, jobPage: parsePositiveInteger(page, 1, MAX_EXPORT_CENTER_PAGE) })
  }

  function setJobPageSize(size: ExportCenterPageSize) {
    return replace({ ...query, jobPage: 1, jobPageSize: parsePageSize(size) })
  }

  function setFilter(filter: string) {
    return replace({ ...query, terminalPage: 1, jobPage: 1, filter: String(filter || '').trim() })
  }

  async function loadCatalog() {
    catalog.value = await fetchExportCatalog()
  }

  async function loadTerminalPage() {
    const serial = terminalRequestSerial + 1
    terminalRequestSerial = serial
    terminalController?.abort()
    terminalController = new AbortController()
    if (query.tab !== 'terminal') {
      terminalPage.value = emptyTerminalPage(query.terminalPage, query.terminalPageSize)
      loading.value = false
      return
    }
    loading.value = true
    try {
      const readinessPage = await fetchTerminalReadinessPage({
        page: query.terminalPage,
        pageSize: query.terminalPageSize,
        filter: query.filter,
        signal: terminalController.signal,
      })
      if (serial !== terminalRequestSerial) return
      terminalPage.value = readinessPage
    } catch (error) {
      if (serial !== terminalRequestSerial || (error instanceof DOMException && error.name === 'AbortError')) return
      errorMessage.value = error instanceof Error ? error.message : '导出中心加载失败'
      terminalPage.value = emptyTerminalPage(query.terminalPage, query.terminalPageSize)
    } finally {
      if (serial === terminalRequestSerial) {
        loading.value = false
      }
    }
  }

  async function loadJobsPage() {
    const serial = jobsRequestSerial + 1
    jobsRequestSerial = serial
    jobsController?.abort()
    jobsController = new AbortController()
    jobsLoading.value = true
    try {
      const exportJobsPage = await fetchExportJobs({
        ...buildJobHistoryQuery(query),
        signal: jobsController.signal,
      })
      if (serial !== jobsRequestSerial) return
      jobsPage.value = exportJobsPage
    } catch (error) {
      if (serial !== jobsRequestSerial || (error instanceof DOMException && error.name === 'AbortError')) return
      errorMessage.value = error instanceof Error ? error.message : '导出中心加载失败'
      jobsPage.value = emptyJobsPage(query.jobPage, query.jobPageSize)
    } finally {
      if (serial === jobsRequestSerial) {
        jobsLoading.value = false
      }
    }
  }

  async function loadData() {
    errorMessage.value = ''
    try {
      await loadCatalog()
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '导出中心加载失败'
      catalog.value = []
    }
    await Promise.all([loadTerminalPage(), loadJobsPage()])
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
    setTerminalPage,
    setTerminalPageSize,
    setJobPage,
    setJobPageSize,
    setFilter,
    refresh,
  }
}
