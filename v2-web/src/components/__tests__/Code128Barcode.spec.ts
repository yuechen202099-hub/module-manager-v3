import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import Code128Barcode from '../Code128Barcode.vue'

describe('Code128Barcode', () => {
  it('renders an accessible barcode image and the exact original value', () => {
    const wrapper = mount(Code128Barcode, {
      props: { value: '001234', label: '采集器条形码' },
    })

    const barcode = wrapper.get('[role="img"]')
    expect(barcode.attributes('aria-label')).toBe('采集器条形码：001234')
    expect(wrapper.text()).toContain('001234')
  })

  it('does not render a barcode for an all-whitespace value and provides a clear empty state', () => {
    const wrapper = mount(Code128Barcode, { props: { value: '   ' } })

    expect(wrapper.find('[role="img"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('编号为空')
    expect(wrapper.text()).toContain('未提供编号')
  })

  it('shows the original unsupported value without rendering an invalid barcode', () => {
    const wrapper = mount(Code128Barcode, { props: { value: '采集器' } })

    expect(wrapper.find('[role="img"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('采集器')
    expect(wrapper.text()).toContain('不支持的字符')
  })
})
