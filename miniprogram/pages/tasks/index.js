const { fetchTasks } = require('../../services/tasks')
const { requireSession, clearSession, getSession } = require('../../utils/session')
const { compactDateTime } = require('../../utils/format')

Page({
  data: {
    loading: false,
    userName: '',
    tasks: [],
    error: ''
  },

  onShow() {
    const session = requireSession()
    if (!session) return
    this.setData({ userName: session.user ? session.user.name : '' })
    this.loadTasks()
  },

  onPullDownRefresh() {
    this.loadTasks().finally(() => wx.stopPullDownRefresh())
  },

  async loadTasks() {
    this.setData({ loading: true, error: '' })
    try {
      const items = await fetchTasks()
      this.setData({
        tasks: items.map((item) => ({
          ...item,
          updatedText: compactDateTime(item.updated_at)
        }))
      })
    } catch (error) {
      this.setData({ error: error.message || '任务加载失败' })
      wx.showToast({ title: error.message || '任务加载失败', icon: 'none' })
    } finally {
      this.setData({ loading: false })
    }
  },

  openTask(event) {
    const task = this.data.tasks[Number(event.currentTarget.dataset.index)]
    if (!task) return
    wx.navigateTo({
      url: `/pages/groups/index?taskId=${encodeURIComponent(task.id)}&title=${encodeURIComponent(task.title || '施工任务')}`
    })
  },

  logout() {
    clearSession()
    wx.reLaunch({ url: '/pages/login/index' })
  },

  refresh() {
    this.loadTasks()
  }
})
