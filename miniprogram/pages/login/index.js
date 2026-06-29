const { request } = require('../../utils/api')
const { setSession } = require('../../utils/session')

Page({
  data: {
    username: '',
    password: '',
    loading: false,
    status: '请输入施工员账号和密码'
  },

  onLoad() {
  },

  onInput(event) {
    const field = event.currentTarget.dataset.field
    this.setData({ [field]: event.detail.value })
  },

  async passwordLogin() {
    const username = this.data.username.trim()
    const password = this.data.password
    if (!username || !password) {
      wx.showToast({ title: '请输入账号密码', icon: 'none' })
      return
    }
    this.setData({ loading: true, status: '正在登录' })
    try {
      const payload = await request('/auth/login', {
        method: 'POST',
        data: { username, password }
      })
      const roles = payload.user && payload.user.roles ? payload.user.roles : []
      if (roles.indexOf('constructor') === -1) {
        throw new Error('仅施工员账号可登录小程序')
      }
      setSession(payload)
      wx.reLaunch({ url: '/pages/tasks/index' })
    } catch (error) {
      this.setData({ status: error.message || '登录失败' })
      wx.showToast({ title: error.message || '登录失败', icon: 'none' })
    } finally {
      this.setData({ loading: false })
    }
  }
})
