import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import GlobalSearchView from '@/views/GlobalSearchView.vue'

const dataCenterMock = vi.hoisted(() => ({
  query: {
    dataType: 'all',
    constructionStatus: 'all',
    terminalStatus: 'all',
    archiveStatus: 'all',
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
    page: 1,
    pageSize: 20,
    review: false,
  },
  rows: [{
    kind: 'group',
    id: 'g-1',
    terminal: '350000431865',
    meterNo: '110020564981',
    meterMatchKey: '110020564981',
    address: '测试地址',
    collector: 'collector-effective',
    moduleAssetNo: 'module-effective',
    constructionCollector: 'collector-effective',
    constructionModuleAssetNo: 'module-effective',
    installer: '施工员',
    photoCount: 2,
    classificationStatus: 'complete',
    classificationProgress: {},
    constructionStatus: 'completed',
    archiveStatus: 'unarchived',
    exceptionStatus: '',
    reviewStatus: 'pending',
    updatedAt: '2026-08-30T00:00:00Z',
  }],
  total: 1,
  loading: false,
  errorMessage: '',
  activeRow: null,
  setFilters: vi.fn(),
  setPage: vi.fn(),
  setPageSize: vi.fn(),
  openReview: vi.fn(),
  closeReview: vi.fn(),
  refresh: vi.fn(),
}))

vi.mock('@/composables/useDataCenterQuery', () => ({
  DATA_CENTER_PAGE_SIZES: [20, 50, 100],
  useDataCenterQuery: () => dataCenterMock,
}))

vi.mock('@/components/data-center/DataCenterFilters.vue', () => ({
  default: { template: '<div data-testid="data-center-filters" />' },
}))

vi.mock('@/components/data-center/DataCenterReviewDialog.vue', () => ({
  default: { template: '<div data-testid="data-center-review-dialog" />' },
}))

describe('GlobalSearchView', () => {
  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })

  afterEach(() => {
    document.body.innerHTML = ''
    vi.unstubAllGlobals()
  })

  it('shows only one collector column and one module column', async () => {
    const wrapper = mount(GlobalSearchView, {
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    const header = wrapper.get('.el-table__header-wrapper')
    const labels = header.findAll('th .cell').map((cell) => cell.text().trim())

    expect(labels.filter((label) => label === '采集器')).toHaveLength(1)
    expect(labels.filter((label) => label === '模块')).toHaveLength(1)
    expect(labels).not.toContain('施工采集器')
    expect(labels).not.toContain('施工模块')
    expect(labels).not.toContain('扫码')
  })
})
