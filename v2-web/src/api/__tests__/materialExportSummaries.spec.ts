import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchMaterialExportSummaries } from '@/api/services'

describe('material export summary requests', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('does not broadcast a data mutation for the read-only summary POST', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [] }),
    }))
    const postMessage = vi.spyOn(window, 'postMessage')

    await fetchMaterialExportSummaries(['task-1'])

    expect(postMessage).not.toHaveBeenCalledWith(
      expect.objectContaining({ type: 'module-manager:data-mutated' }),
      window.location.origin,
    )
  })
})
