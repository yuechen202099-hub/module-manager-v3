const api = require("../../utils/api");
const queue = require("../../utils/queue");
const photo = require("../../utils/photo");

const SLOT_DEFS = [
  { key: "before_box", label: "改造前照片", required: true },
  { key: "collector_barcode", label: "采集器照片", required: false },
  { key: "module_meter", label: "模块与电表照片", required: true },
  { key: "after_box", label: "改造后照片", required: true }
];

function emptySlots() {
  return SLOT_DEFS.map((slot) => ({ ...slot, filePath: "", client_photo_id: "" }));
}

function restoreSlots(cachedSlots) {
  const byKey = {};
  (cachedSlots || []).forEach((slot) => {
    byKey[slot.key] = slot;
  });
  return SLOT_DEFS.map((slot) => ({ ...slot, ...(byKey[slot.key] || {}) }));
}

function existingPhotoForSlot(group, slotKey) {
  const photos = (group?.photos || []).filter((item) => item.image_url);
  return photos.find((item) => item.construction_slot === slotKey)
    || photos.find((item) => item.category === slotKey)
    || null;
}

function coveredSlotsForGroup(group) {
  return SLOT_DEFS.filter((slot) => existingPhotoForSlot(group, slot.key)).map((slot) => slot.key);
}

Page({
  data: {
    taskId: "",
    groupId: "",
    group: {},
    collector: "",
    moduleAssetNo: "",
    slots: emptySlots(),
    clientBatchId: "",
    uploading: false,
    online: true,
    cacheText: "未保存"
  },

  onLoad(options) {
    this.setData({
      taskId: options.taskId || "",
      groupId: decodeURIComponent(options.groupId || "")
    });
  },

  onShow() {
    if (!api.session()?.access_token) {
      wx.reLaunch({ url: "/pages/login/login" });
      return;
    }
    this.setData({ online: getApp().globalData.online });
    this.loadGroup();
  },

  onHide() {
    this.persistGroupDraft();
  },

  onUnload() {
    this.persistGroupDraft();
  },

  async loadGroup() {
    if (!this.data.groupId) return;
    try {
      let group;
      let offlineGroup = false;
      try {
        group = await api.getGroup(this.data.groupId);
      } catch (error) {
        const cachedGroup = queue.getCachedGroup(this.data.taskId, this.data.groupId);
        if (!cachedGroup) throw error;
        group = { ...cachedGroup, photos: cachedGroup.photos || [] };
        offlineGroup = true;
      }
      const existing = (group.photos || []).find((item) => item.image_url) || {};
      const cached = queue.loadGroupDraft(this.data.taskId, this.data.groupId);
      this.setData({
        group,
        collector: cached?.collector ?? group.construction_collector ?? existing.collector ?? this.data.collector,
        moduleAssetNo: cached?.module_asset_no ?? group.construction_module_asset_no ?? existing.asset_no ?? this.data.moduleAssetNo,
        slots: restoreSlots(cached?.slots),
        clientBatchId: cached?.client_batch_id || queue.uuid("batch"),
        cacheText: cached ? "已恢复本地缓存" : (offlineGroup ? "已加载终端离线包" : "未保存")
      });
    } catch (error) {
      wx.showToast({ title: error.message || "加载失败", icon: "none" });
    }
  },

  persistGroupDraft() {
    if (!this.data.groupId) return;
    const collector = this.data.collector.trim();
    const moduleAssetNo = this.data.moduleAssetNo.trim();
    const hasPhoto = this.data.slots.some((slot) => slot.filePath);
    if (!collector && !moduleAssetNo && !hasPhoto) {
      queue.removeGroupDraft(this.data.taskId, this.data.groupId);
      this.setData({ cacheText: "未保存" });
      return;
    }
    const draft = {
      client_batch_id: this.data.clientBatchId || queue.uuid("batch"),
      actor: api.session()?.user?.username || "constructor",
      teamId: api.teamId(),
      taskId: this.data.taskId,
      groupId: this.data.groupId,
      meter_no: this.data.group.meter_no || "",
      terminal: this.data.group.terminal || "",
      address: this.data.group.address || "",
      collector,
      module_asset_no: moduleAssetNo,
      work_order_id: this.data.group?.exception_order_id || this.data.group?.exception_work_order_id || "",
      exception_category: this.data.group?.exception_category || "",
      exception_note: this.data.group?.exception_note || "",
      covered_slots: coveredSlotsForGroup(this.data.group),
      slots: this.data.slots.map((slot) => ({
        key: slot.key,
        label: slot.label,
        required: slot.required,
        filePath: slot.filePath || "",
        client_photo_id: slot.client_photo_id || ""
      }))
    };
    queue.saveGroupDraft(this.data.taskId, this.data.groupId, draft);
    this.setData({ clientBatchId: draft.client_batch_id, cacheText: "已保存本地缓存" });
  },

  onCollectorInput(event) {
    this.setData({ collector: event.detail.value });
    this.persistGroupDraft();
  },

  onModuleInput(event) {
    this.setData({ moduleAssetNo: event.detail.value });
    this.persistGroupDraft();
  },

  scanCode() {
    return new Promise((resolve, reject) => {
      wx.scanCode({
        onlyFromCamera: false,
        scanType: ["barCode", "qrCode"],
        success: (res) => resolve(res.result || ""),
        fail: (error) => reject(new Error(error.errMsg || "扫码失败"))
      });
    });
  },

  async scanCollector() {
    try {
      const value = await this.scanCode();
      this.setData({ collector: value });
      this.persistGroupDraft();
    } catch (error) {
      wx.showToast({ title: error.message || "扫码失败", icon: "none" });
    }
  },

  async scanModule() {
    try {
      const value = await this.scanCode();
      this.setData({ moduleAssetNo: value });
      this.persistGroupDraft();
    } catch (error) {
      wx.showToast({ title: error.message || "扫码失败", icon: "none" });
    }
  },

  async choosePhoto(event) {
    await this.choosePhotoByKey(event.currentTarget.dataset.key);
  },

  async choosePhotoByKey(key) {
    try {
      wx.showLoading({ title: "处理照片..." });
      const filePath = await photo.chooseCompressedSavedImage();
      const old = this.data.slots.find((item) => item.key === key);
      if (old?.filePath) queue.removeLocalFile(old.filePath);
      const slots = this.data.slots.map((item) => (
        item.key === key
          ? { ...item, filePath, client_photo_id: item.client_photo_id || queue.uuid(key) }
          : item
      ));
      this.setData({ slots });
      this.persistGroupDraft();
    } catch (error) {
      wx.showToast({ title: error.message || "照片处理失败", icon: "none" });
    } finally {
      wx.hideLoading();
    }
  },

  removePhoto(event) {
    const key = event.currentTarget.dataset.key;
    const old = this.data.slots.find((item) => item.key === key);
    if (old?.filePath) queue.removeLocalFile(old.filePath);
    const slots = this.data.slots.map((item) => (
      item.key === key ? { ...item, filePath: "", client_photo_id: "" } : item
    ));
    this.setData({ slots });
    this.persistGroupDraft();
  },

  validateForUpload() {
    if (!this.data.moduleAssetNo.trim()) {
      throw new Error("模块号为必填项");
    }
    const covered = new Set(coveredSlotsForGroup(this.data.group));
    const missing = this.data.slots
      .filter((slot) => slot.required && !slot.filePath && !covered.has(slot.key))
      .map((slot) => slot.label);
    if (missing.length) {
      throw new Error(`请补齐：${missing.join("、")}`);
    }
  },

  buildUploadDraft() {
    this.validateForUpload();
    const session = api.session();
    const photos = this.data.slots
      .filter((item) => item.filePath)
      .map((item) => ({
        slot: item.key,
        label: item.label,
        filePath: item.filePath,
        client_photo_id: item.client_photo_id || queue.uuid(item.key)
      }));
    return {
      client_batch_id: this.data.clientBatchId || queue.uuid("batch"),
      actor: session?.user?.username || "constructor",
      teamId: api.teamId(),
      taskId: this.data.taskId,
      groupId: this.data.groupId,
      meter_no: this.data.group.meter_no || "",
      terminal: this.data.group.terminal || "",
      address: this.data.group.address || "",
      collector: this.data.collector.trim(),
      module_asset_no: this.data.moduleAssetNo.trim(),
      work_order_id: this.data.group?.exception_order_id || this.data.group?.exception_work_order_id || "",
      exception_category: this.data.group?.exception_category || "",
      exception_note: this.data.group?.exception_note || "",
      covered_slots: coveredSlotsForGroup(this.data.group),
      photos,
      created_at: new Date().toISOString()
    };
  },

  saveDraft() {
    this.persistGroupDraft();
    wx.showToast({ title: "已保存缓存", icon: "success" });
  },

  async uploadNow() {
    let draft;
    try {
      this.persistGroupDraft();
      draft = this.buildUploadDraft();
      queue.enqueueDraft(draft);
    } catch (error) {
      wx.showToast({ title: error.message || "资料不完整", icon: "none" });
      return;
    }
    if (!getApp().globalData.online) {
      wx.showToast({ title: "已离线缓存", icon: "success" });
      return;
    }
    this.setData({ uploading: true });
    try {
      await queue.processQueue();
      queue.removeGroupDraft(this.data.taskId, this.data.groupId);
      wx.showToast({ title: "上传完成", icon: "success" });
      setTimeout(() => wx.navigateBack(), 600);
    } catch (error) {
      wx.showToast({ title: error.message || "已缓存待重试", icon: "none" });
    } finally {
      this.setData({ uploading: false });
    }
  }
});
