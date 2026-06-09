import { defineStore } from 'pinia'

import * as services from '@/api/services'
import type { CurrentUser } from '@/api/types'

type AuthState = {
  token: string
  user: CurrentUser | null
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    token: localStorage.getItem('v2-web-token') || '',
    user: JSON.parse(localStorage.getItem('v2-web-user') || 'null') as CurrentUser | null,
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.token),
    displayName: (state) => state.user?.name || '未登录',
  },
  actions: {
    async login(username: string, password: string) {
      const result = await services.login(username, password)
      this.token = result.token
      this.user = result.user
      localStorage.setItem('v2-web-token', result.token)
      localStorage.setItem('v2-web-user', JSON.stringify(result.user))
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('v2-web-token')
      localStorage.removeItem('v2-web-user')
    },
  },
})
