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

  it('renders bar rectangles with a ten-module quiet zone on both sides', () => {
    const wrapper = mount(Code128Barcode, { props: { value: 'A' } })
    const svg = wrapper.get('svg')
    const barRects = wrapper.findAll('svg rect[x]')
    const firstBar = barRects[0]
    const lastBar = barRects.at(-1)
    const [, , moduleCount] = (svg.attributes('viewBox') || '').split(' ').map(Number)

    expect(barRects.length).toBeGreaterThan(0)
    expect(firstBar.attributes('x')).toBe('10')
    expect(barRects.every((rect) => rect.attributes('height') === '54')).toBe(true)
    expect(moduleCount - (Number(lastBar?.attributes('x')) + Number(lastBar?.attributes('width')))).toBe(10)
  })

  it('keeps every visible whitespace character in the human-readable caption', () => {
    const value = '  A  B  '
    const wrapper = mount(Code128Barcode, { props: { value } })
    const caption = wrapper.get('figcaption')

    expect(caption.element.textContent).toBe(value)
    expect(window.getComputedStyle(caption.element).whiteSpace).toBe('pre-wrap')
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
