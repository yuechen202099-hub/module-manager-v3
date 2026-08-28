import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'

import PhotoLightbox from '@/components/PhotoLightbox.vue'


describe('PhotoLightbox', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('keeps keyboard focus inside the dialog and restores the opener after closing', async () => {
    const opener = document.createElement('button')
    opener.textContent = '查看大图'
    document.body.append(opener)
    opener.focus()

    const wrapper = mount(PhotoLightbox, {
      attachTo: document.body,
      props: { src: '', alt: '电表和模块照片' },
    })
    await nextTick()

    const hiddenTab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    opener.dispatchEvent(hiddenTab)
    expect(hiddenTab.defaultPrevented).toBe(false)
    expect(document.activeElement).toBe(opener)

    await wrapper.setProps({ src: '/photo.jpg' })
    await nextTick()

    const closeButton = wrapper.get('[data-testid="close-photo-lightbox"]')
    expect(document.activeElement).toBe(closeButton.element)

    const forwardTab = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    closeButton.element.dispatchEvent(forwardTab)
    expect(forwardTab.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(closeButton.element)

    const backwardTab = new KeyboardEvent('keydown', {
      key: 'Tab',
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    })
    closeButton.element.dispatchEvent(backwardTab)
    expect(backwardTab.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(closeButton.element)

    await wrapper.setProps({ src: '' })
    expect(document.activeElement).toBe(opener)

    wrapper.unmount()
  })
})
