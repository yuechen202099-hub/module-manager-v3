import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ProjectBoardView from '@/views/ProjectBoardView.vue'

const apiMock = vi.hoisted(() => ({
  boardEventHeaders: vi.fn(() => ({})),
  boardEventsUrl: vi.fn(() => '/events'),
  downloadProjectMeterModuleWorkbook: vi.fn(),
  fetchInstallerWorkload: vi.fn(),
  fetchProjectSummary: vi.fn(),
  fetchTasks: vi.fn(),
  fetchTaskStatus: vi.fn(),
  importTotalCatalog: vi.fn(),
}))

vi.mock('@/api/services', () => apiMock)
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { role: 'admin', roles: ['admin'] } }),
}))
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

describe('ProjectBoardView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.fetchProjectSummary.mockResolvedValue({
      summary: {
        totalCatalogRows: 0,
        groups: 0,
        scannedGroups: 0,
        approvedGroups: 0,
        reviewedGroups: 0,
        unreviewedGroups: 0,
        exceptionGroups: 0,
        incompleteGroups: 0,
        unconstructedGroups: 0,
        photoRowsLinked: 0,
        scanUnmatched: 0,
        reviewProgress: 0,
        photoAccuracyChecked: 0,
        photoAccuracyPassed: 0,
        photoAccuracyFailed: 0,
        photoAccuracyUnreadable: 0,
        photoAccuracyNotRequired: 0,
        photoAccuracyRate: 0,
        groupBarcodeAccuracyChecked: 0,
        groupBarcodeAccuracyPassed: 0,
        groupBarcodeAccuracyFailed: 0,
        groupBarcodeAccuracyUnreadable: 0,
        groupBarcodeAccuracyNotRequired: 0,
        groupBarcodeAccuracyRate: 0,
        installerDistribution: [],
      },
    })
    apiMock.fetchTaskStatus.mockResolvedValue({ total: 0 })
    apiMock.fetchTasks.mockResolvedValue([])
    apiMock.downloadProjectMeterModuleWorkbook.mockResolvedValue(undefined)
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, body: null })))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('downloads the current project meter-module workbook from the cockpit action', async () => {
    const wrapper = mount(ProjectBoardView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    const button = wrapper.get('[data-testid="export-meter-module"]')
    expect(button.text()).toContain('导出表号模块号')

    await button.trigger('click')
    await flushPromises()

    expect(apiMock.downloadProjectMeterModuleWorkbook).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
