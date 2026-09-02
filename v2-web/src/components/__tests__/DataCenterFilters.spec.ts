import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import DataCenterFilters from '@/components/data-center/DataCenterFilters.vue'
import type { DataCenterRouteQuery } from '@/composables/useDataCenterQuery'

const query: DataCenterRouteQuery = {
  page: 1,
  pageSize: 20,
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
  groupId: '',
  review: false,
}

describe('DataCenterFilters', () => {
  it('offers only unarchived and archived choices for terminal archival', () => {
    const wrapper = mount(DataCenterFilters, {
      props: { modelValue: query },
      global: {
        stubs: {
          'el-input': true,
          'el-select': { template: '<div><slot /></div>' },
          'el-option': { props: ['label'], template: '<span>{{ label }}</span>' },
          'el-date-picker': true,
          'el-button': { template: '<button><slot /></button>' },
        },
      },
    })

    expect(wrapper.text()).toContain('未归档')
    expect(wrapper.text()).toContain('已归档')
    expect(wrapper.text()).not.toContain('待归档')
  })
})
