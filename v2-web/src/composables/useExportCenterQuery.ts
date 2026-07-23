import { reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchExportCatalog, fetchExportJobs, fetchTerminalReadinessPage } from '@/api/services'
import type {
  ExportCatalogItem,
  ExportCenterPageSize,
  ExportCenterTab,
  ExportJob,
  TerminalReadinessPage,
} from '@/api/types'

export const EXPORT_CENTER_PAGE_SIZES = [20, 50, 100] as const

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
    page: Math.max(1, Math.floor(Number(first(query.page)) || 1)),
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

function emptyTerminalPage(page: number, pageSize: ExportCenterPageSize): TerminalReadinessPage {
  return {
    total: 0,
    page,
    pageSize,
    items: [],
  }
}

export function useExportCenterQuery() {
  const route = useRoute()
  const router = useRouter()
  const query = reactive<ExportCenterRouteQuery>(routeQueryToState(route.query as Record<string, unknown>))
  const catalog = ref<ExportCatalogItem[]>([])
  const terminalPage = ref<TerminalReadinessPage>(emptyTerminalPage(query.page, query.pageSize))
  const jobs = ref<ExportJob[]>([])
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
    return replace({ ...query, page: Math.max(1, page) })
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
      const [catalogItems, latestJobs, readinessPage] = await Promise.all([
        fetchExportCatalog(controller.signal),
        fetchExportJobs({ page: 1, pageSize: 100, signal: controller.signal }),
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
      jobs.value = latestJobs.items
      terminalPage.value = readinessPage
    } catch (error) {
      if (serial !== requestSerial || (error instanceof DOMException && error.name === 'AbortError')) return
      errorMessage.value = error instanceof Error ? error.message : '导出中心加载失败'
      if (query.tab === 'terminal') terminalPage.value = emptyTerminalPage(query.page, query.pageSize)
      jobs.value = []
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
    jobs,
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
