import { createApp } from 'vue'
import { describe, expect, it } from 'vitest'

import { installElementPlus } from '@/plugins/element-plus'

describe('installElementPlus', () => {
  it('registers the checkbox used by the data-center unclassified-photo filter', () => {
    const app = createApp({ template: '<div />' })

    installElementPlus(app)

    expect(app.component('ElCheckbox')).toBeTruthy()
  })
})
