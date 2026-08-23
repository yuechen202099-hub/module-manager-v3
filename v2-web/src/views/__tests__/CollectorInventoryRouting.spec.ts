import { describe, expect, it, vi } from 'vitest'

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    isAuthenticated: true,
    user: { role: 'constructor', roles: ['constructor'] },
    hydrateFromLegacySession: vi.fn(),
  }),
}))

import router from '@/router'
import { findStaticPage } from '@/router/staticPages'

describe('collector inventory route', () => {
  it('registers the native mobile page for admin and constructor only', () => {
    const page = findStaticPage('collector-inventory')
    expect(page).toMatchObject({
      routePath: '/collector-inventory',
      roles: ['admin', 'constructor'],
      migrationStatus: 'native_vue',
    })

    const route = router.getRoutes().find((item) => item.name === 'collector-inventory')
    expect(route?.path).toBe('/collector-inventory')
    expect(route?.meta.roles).toEqual(['admin', 'constructor'])
    expect(route?.components?.default).toBeTypeOf('function')
  })
})
