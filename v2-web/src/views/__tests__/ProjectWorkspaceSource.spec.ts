import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchProjects } from '@/api/services'

describe('workspace project source', () => {
  afterEach(() => {
    localStorage.clear()
    vi.unstubAllGlobals()
  })

  it('loads real PostgreSQL project ids for the current workspace', async () => {
    const projectId = '11111111-1111-4111-8111-111111111111'
    localStorage.setItem('module_manager_session', JSON.stringify({
      access_token: 'local-test-token',
      team_id: 'demo-team',
      user: {
        username: 'admin',
        team_id: 'demo-team',
        roles: ['admin'],
      },
    }))
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      data: {
        items: [{
          id: projectId,
          name: '城南改造',
          status: 'active',
          updated_at: '2026-08-24T10:00:00Z',
        }],
      },
      error: null,
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })))

    await expect(fetchProjects()).resolves.toEqual([{
      id: projectId,
      name: '城南改造',
      status: 'active',
      totalGroups: 0,
      completedGroups: 0,
      exceptionGroups: 0,
      updatedAt: '2026-08-24T10:00:00Z',
    }])
  })
})
