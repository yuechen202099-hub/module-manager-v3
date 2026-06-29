const { GROUP_FILTERS, PHOTO_SLOTS, groupStatusLabel } = require('../../utils/constants')
const { requireSession } = require('../../utils/session')
const { fetchGroups, matchesGroup, findGroupByScan } = require('../../services/groups')
const drafts = require('../../services/drafts')
const uploadQueue = require('../../services/uploadQueue')

Page({
  data: {
    taskId: '',
    title: '资料组',
    filters: GROUP_FILTERS,
    activeFilter: 'todo',
    keyword: '',
    loading: false,
    uploading: false,
    groups: [],
    visibleGroups: [],
    localDrafts: [],
    sheetOpen: false,
    activeGroup: null,
    activeDraft: null,
    slots: PHOTO_SLOTS,
    activeSlots: [],
    error: ''
  },

  onLoad(options) {
    requireSession()
    this.setData({
      taskId: options.taskId || '',
      title: decodeURIComponent(options.title || '资料组')
    })
    wx.setNavigationBarTitle({ title: this.data.title })
    this.loadGroups()
  },

  onPullDownRefresh() {
    this.loadGroups().finally(() => wx.stopPullDownRefresh())
  },

  async loadGroups() {
    if (!this.data.taskId) return
    this.setData({ loading: true, error: '' })
    try {
      const localDrafts = drafts.listDrafts(this.data.taskId)
      const remoteFilter = this.data.activeFilter === 'draft' ? 'todo' : this.data.activeFilter
      const groups = await fetchGroups(this.data.taskId, remoteFilter)
      this.setData({ groups, localDrafts })
      this.applyFilters()
    } catch (error) {
      this.setData({ error: error.message || '资料组加载失败' })
      wx.showToast({ title: error.message || '资料组加载失败', icon: 'none' })
    } finally {
      this.setData({ loading: false })
    }
  },

  switchFilter(event) {
    const activeFilter = event.currentTarget.dataset.filter
    this.setData({ activeFilter })
    this.loadGroups()
  },

  onSearch(event) {
    this.setData({ keyword: event.detail.value })
    this.applyFilters()
  },

  applyFilters() {
    const keyword = this.data.keyword
    let visibleGroups = []
    if (this.data.activeFilter === 'draft') {
      visibleGroups = this.data.localDrafts
        .filter((draft) => matchesGroup(draft.group || {}, keyword))
        .map((draft) => this.decorateGroup(Object.assign({}, draft.group, {
          localDraft: draft,
          draftStatus: draft.status,
          statusLabel: '待上传'
        })))
    } else {
      visibleGroups = this.data.groups
        .filter((group) => matchesGroup(group, keyword))
        .map((group) => this.decorateGroup(group))
    }
    this.setData({ visibleGroups })
  },

  decorateGroup(group) {
    const status = group && (group.statusLabel || group.construction_status || group.status)
    return Object.assign({}, group, {
      statusLabel: groupStatusLabel(status)
    })
  },

  scanLocate() {
    wx.scanCode({
      onlyFromCamera: false,
      success: (result) => {
        const group = findGroupByScan(this.data.groups, result.result)
        if (!group) {
          wx.showToast({ title: '无工单', icon: 'none' })
          return
        }
        this.openSheetWithGroup(group)
      },
      fail: () => wx.showToast({ title: '扫码取消', icon: 'none' })
    })
  },

  openGroup(event) {
    const index = Number(event.currentTarget.dataset.index)
    const group = this.data.visibleGroups[index]
    if (group) this.openSheetWithGroup(group)
  },

  openSheetWithGroup(group) {
    const draft = drafts.mergeDraftWithGroup(this.data.taskId, group)
    this.setData({
      activeGroup: group,
      activeDraft: draft,
      activeSlots: this.buildSlots(draft),
      sheetOpen: true
    })
  },

  buildSlots(draft) {
    const photos = (draft && draft.photos) || {}
    return PHOTO_SLOTS.map((slot) => {
      const photo = photos[slot.key] || {}
      return Object.assign({}, slot, {
        photoPath: photo.path || ''
      })
    })
  },

  closeSheet() {
    this.setData({ sheetOpen: false, activeGroup: null, activeDraft: null })
    this.refreshDrafts()
  },

  refreshDrafts() {
    this.setData({ localDrafts: drafts.listDrafts(this.data.taskId) })
    this.applyFilters()
  },

  updateDraftField(event) {
    const field = event.currentTarget.dataset.field
    const value = event.detail.value
    const draft = Object.assign({}, this.data.activeDraft, { [field]: value })
    const saved = drafts.saveDraft(draft)
    this.setData({ activeDraft: saved, activeSlots: this.buildSlots(saved) })
  },

  choosePhoto(event) {
    const slot = event.currentTarget.dataset.slot
    wx.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sourceType: ['camera', 'album'],
      success: (result) => {
        const file = result.tempFiles && result.tempFiles[0]
        if (!file) return
        this.savePhoto(slot, file.tempFilePath)
      },
      fail: () => {
        wx.chooseImage({
          count: 1,
          sourceType: ['camera', 'album'],
          success: (result) => this.savePhoto(slot, result.tempFilePaths[0])
        })
      }
    })
  },

  savePhoto(slot, path) {
    const draft = Object.assign({}, this.data.activeDraft)
    draft.photos = Object.assign({}, draft.photos || {}, {
      [slot]: {
        path,
        clientPhotoId: `${slot}-${Date.now()}`
      }
    })
    const saved = drafts.saveDraft(draft)
    this.setData({ activeDraft: saved, activeSlots: this.buildSlots(saved) })
  },

  scanField(event) {
    const field = event.currentTarget.dataset.field
    wx.scanCode({
      onlyFromCamera: false,
      success: (result) => {
        const draft = Object.assign({}, this.data.activeDraft, { [field]: result.result || '' })
        const saved = drafts.saveDraft(draft)
        this.setData({ activeDraft: saved, activeSlots: this.buildSlots(saved) })
      }
    })
  },

  saveCurrentDraft() {
    const saved = drafts.saveDraft(this.data.activeDraft)
    this.setData({ activeDraft: saved, activeSlots: this.buildSlots(saved) })
    uploadQueue.recordNonIdle(saved, 'group_draft_completed')
    wx.showToast({ title: '已保存草稿', icon: 'success' })
    this.refreshDrafts()
  },

  async submitCurrentDraft() {
    const draft = this.data.activeDraft
    if (!drafts.draftIsSubmittable(draft)) {
      wx.showToast({ title: '必填照片未完成', icon: 'none' })
      return
    }
    this.setData({ uploading: true })
    try {
      await uploadQueue.uploadDraft(draft)
      wx.showToast({ title: '已上传', icon: 'success' })
      this.closeSheet()
      this.loadGroups()
    } catch (error) {
      draft.lastError = error.message || '上传失败'
      const saved = drafts.saveDraft(draft)
      this.setData({ activeDraft: saved, activeSlots: this.buildSlots(saved) })
      wx.showToast({ title: draft.lastError, icon: 'none' })
    } finally {
      this.setData({ uploading: false })
    }
  },

  async batchUpload() {
    const ready = drafts.listDrafts(this.data.taskId).filter(drafts.draftIsSubmittable)
    if (!ready.length) {
      wx.showToast({ title: '暂无可上传草稿', icon: 'none' })
      return
    }
    this.setData({ uploading: true })
    try {
      const results = await uploadQueue.uploadDrafts(ready)
      const okCount = results.filter((item) => item.ok).length
      wx.showToast({ title: `已上传 ${okCount} 组`, icon: 'success' })
      this.loadGroups()
    } finally {
      this.setData({ uploading: false })
    }
  }
})
