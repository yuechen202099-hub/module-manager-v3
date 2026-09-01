import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'

import MaterialExportToolbar from '../MaterialExportToolbar.vue'

function mountToolbar(overrides: Partial<InstanceType<typeof MaterialExportToolbar>['$props']> = {}) {
  return mount(MaterialExportToolbar, {
    props: {
      selectedCount: 1,
      allSelected: false,
      running: false,
      paused: false,
      hasJob: false,
      progressText: '',
      ...overrides,
    },
    global: { plugins: [ElementPlus] },
  })
}

describe('MaterialExportToolbar', () => {
  it('requests a safe pause while a file is running', async () => {
    const wrapper = mountToolbar({ running: true, hasJob: true })

    await wrapper.get('[data-testid="material-export-pause"]').trigger('click')

    expect(wrapper.emitted('pause')).toHaveLength(1)
    expect(wrapper.find('[data-testid="material-export-resume"]').exists()).toBe(false)
  })

  it('offers resume and explicit reservation release after pausing', async () => {
    const wrapper = mountToolbar({ paused: true, hasJob: true, progressText: '已暂停 1/2 个文件' })

    await wrapper.get('[data-testid="material-export-resume"]').trigger('click')
    await wrapper.get('[data-testid="material-export-release"]').trigger('click')

    expect(wrapper.emitted('resume')).toHaveLength(1)
    expect(wrapper.emitted('release')).toHaveLength(1)
  })
})
