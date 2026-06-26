import { defineStore } from 'pinia'

import * as services from '@/api/services'
import type { CurrentUser } from '@/api/types'

type AuthState = {
  token: string
  user: CurrentUser | null
}

function clearStoredAuth() {
  localStorage.removeItem('v2-web-token')
  localStorage.removeItem('v2-web-user')
  localStorage.removeItem('module_manager_session')
  localStorage.removeItem('module_manager_reviewer')
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const part = token.split('.')[1]
  if (!part) return null
  try {
    const normalized = part.replace(/-/g, '+').replace(/_/g, '/')
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=')
    return JSON.parse(window.atob(padded)) as Record<string, unknown>
  } catch {
    return null
  }
}

function isTokenExpired(token: string) {
  const payload = decodeJwtPayload(token)
  const exp = Number(payload?.exp || 0)
  if (!Number.isFinite(exp) || exp <= 0) return true
  return exp * 1000 <= Date.now()
}

function readStoredUser() {
  try {
    return JSON.parse(localStorage.getItem('v2-web-user') || 'null') as CurrentUser | null
  } catch {
    return null
  }
}

function readStoredToken() {
  const token = localStorage.getItem('v2-web-token')
  if (token) {
    if (isTokenExpired(token)) {
      clearStoredAuth()
      return ''
    }
    return token
  }
  try {
    const session = JSON.parse(localStorage.getItem('module_manager_session') || 'null') as { access_token?: string } | null
    const legacyToken = session?.access_token || ''
    if (legacyToken && isTokenExpired(legacyToken)) {
      clearStoredAuth()
      return ''
    }
    return legacyToken
  } catch {
    return ''
  }
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    token: readStoredToken(),
    user: readStoredUser(),
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.token),
    displayName: (state) => state.user?.name || '未登录',
  },
  actions: {
    async login(username: string, password: string, teamId?: string) {
      const result = await services.login(username, password, teamId)
      this.token = result.token
      this.user = result.user
      localStorage.setItem('v2-web-token', result.token)
      localStorage.setItem('v2-web-user', JSON.stringify(result.user))
    },
    async hydrateFromLegacySession() {
      if (this.user) return
      const user = await services.fetchCurrentUser()
      this.user = user
      this.token = readStoredToken()
      localStorage.setItem('v2-web-token', this.token)
      localStorage.setItem('v2-web-user', JSON.stringify(user))
    },
    logout() {
      this.token = ''
      this.user = null
      clearStoredAuth()
    },
  },
})
