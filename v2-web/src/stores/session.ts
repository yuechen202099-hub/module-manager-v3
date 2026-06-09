import { defineStore } from 'pinia'

export const useSessionStore = defineStore('session', {
  state: () => ({
    token: '',
    role: 'admin',
    username: 'admin',
  }),
  actions: {
    setSession(token: string, role: string, username: string) {
      this.token = token
      this.role = role
      this.username = username
    },
  },
})

