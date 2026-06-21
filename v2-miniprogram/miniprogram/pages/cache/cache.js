const queue = require("../../utils/queue");
const api = require("../../utils/api");

function normalizeSearchText(value) {
  return String(value || "")
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[^\u4e00-\u9fa5a-z0-9]+/g, "");
}

function queryTokens(value) {
  const source = String(value || "").normalize("NFKC").toLowerCase();
  const tokens = source.split(/[^\u4e00-\u9fa5a-z0-9]+/).map(normalizeSearchText).filter(Boolean);
  return tokens.length ? tokens : (normalizeSearchText(source) ? [normalizeSearchText(source)] : []);
}

function fuzzyIncludes(haystack, needle) {
  if (!needle) return true;
  if (haystack.includes(needle)) return true;
  let index = 0;
  for (const char of haystack) {
    if (char === needle[index]) index += 1;
    if (index === needle.length) return true;
  }
  return false;
}

function cacheSearchBlob(item) {
  return normalizeSearchText(`${item.meter_no || ""} ${item.address || ""} ${item.terminal || ""} ${item.collector || ""} ${item.module_asset_no || ""} ${item.actor || ""} ${item.client_batch_id || ""}`);
}

function matchesCacheQuery(item, query) {
  const tokens = queryTokens(query);
  if (!tokens.length) return true;
  const blob = cacheSearchBlob(item);
  return tokens.every((token) => fuzzyIncludes(blob, token));
}

Page({
  data: {
    items: [],
    summary: { total: 0, ready: 0, blocked: 0, queued: 0, saved: 0, stale: 0 },
    uploading: false,
    uploadText: "等待操作",
    online: true,
    selectedId: "",
    query: ""
  },

  onShow() {
    this.refresh();
  },

  async refresh() {
    const items = queue.listCacheItems({ includeStale: true })
      .map((item) => ({
        ...item,
        photoCount: (item.photos || []).length,
        missingText: (item.missing || []).join("、"),
        kindLabel: item.kind === "group-draft" ? "保存缓存" : "待上传队列",
        statusLabel: item.stale ? "历史缓存" : item.ready ? "可上传" : "需补齐",
        detailOpen: item.client_batch_id === this.data.selectedId,
        staleText: item.staleReason || ""
      }))
      .filter((item) => matchesCacheQuery(item, this.data.query))
      .sort((a, b) => Number(a.stale) - Number(b.stale) || Number(b.ready) - Number(a.ready));
    this.setData({
      items,
      summary: queue.getCacheSummary({ includeStale: true }),
      online: getApp().globalData.online
    });
  },

  async uploadAll() {
    if (!getApp().globalData.online) {
      wx.showToast({ title: "当前离线，无法上传", icon: "none" });
      return;
    }
    this.setData({ uploading: true, uploadText: "正在上传完整缓存..." });
    try {
      const result = await queue.processAllCaches((event) => {
        this.setData({ uploadText: `正在上传 ${event.index + 1}/${event.total}，${event.progress.progress || 0}%` });
      });
      this.setData({ uploadText: `完成 ${result.uploaded} 组，失败 ${result.failed} 组` });
      this.refresh();
    } catch (error) {
      this.setData({ uploadText: error.message || "上传失败" });
    } finally {
      this.setData({ uploading: false });
    }
  },

  toggleDetail(event) {
    const id = event.currentTarget.dataset.id;
    this.setData({ selectedId: this.data.selectedId === id ? "" : id }, () => this.refresh());
  },

  stopEvent() {},

  onQueryInput(event) {
    this.setData({ query: event.detail.value || "" }, () => this.refresh());
  },

  clearQuery() {
    this.setData({ query: "" }, () => this.refresh());
  },

  onEditInput(event) {
    const { id, field } = event.currentTarget.dataset;
    const value = event.detail.value || "";
    const items = this.data.items.map((item) => (
      item.client_batch_id === id ? { ...item, [field]: value } : item
    ));
    this.setData({ items });
  },

  saveCacheEdit(event) {
    const id = event.currentTarget.dataset.id;
    const item = this.data.items.find((entry) => entry.client_batch_id === id);
    if (!item) return;
    queue.updateCacheItem(id, {
      terminal: item.terminal || "",
      meter_no: item.meter_no || "",
      address: item.address || "",
      collector: item.collector || "",
      module_asset_no: item.module_asset_no || ""
    });
    wx.showToast({ title: "已保存本机缓存", icon: "success" });
    this.refresh();
  },

  previewPhoto(event) {
    const { id, src } = event.currentTarget.dataset;
    const item = this.data.items.find((entry) => entry.client_batch_id === id);
    const urls = (item?.photos || []).map((photo) => photo.filePath).filter(Boolean);
    if (!urls.length || !src) return;
    wx.previewImage({ current: src, urls });
  },

  removeCache(event) {
    const id = event.currentTarget.dataset.id;
    const item = this.data.items.find((entry) => entry.client_batch_id === id);
    queue.removeCacheItem(item);
    this.setData({ selectedId: "" });
    this.refresh();
    wx.showToast({ title: "已删除缓存", icon: "success" });
  },

  clearHistory() {
    const stale = this.data.items.filter((item) => item.stale);
    stale.forEach((item) => queue.removeCacheItem(item));
    this.setData({ selectedId: "" });
    this.refresh();
    wx.showToast({ title: "历史缓存已清理", icon: "success" });
  },

  backToTasks() {
    const pages = getCurrentPages();
    if (pages.length > 1) wx.navigateBack();
    else wx.reLaunch({ url: "/pages/tasks/tasks" });
  }
});
