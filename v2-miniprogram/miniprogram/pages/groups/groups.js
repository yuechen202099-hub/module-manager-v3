const api = require("../../utils/api");
const queue = require("../../utils/queue");

const zhAddressCollator = new Intl.Collator("zh-Hans-CN", { numeric: true, sensitivity: "base" });

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

function groupSearchBlob(group) {
  return normalizeSearchText(`${group.meter_no || ""} ${group.address || ""} ${group.terminal || ""} ${group.construction_collector || ""} ${group.construction_module_asset_no || ""}`);
}

function normalizeCode(value) {
  return String(value || "")
    .normalize("NFKC")
    .replace(/[^0-9a-zA-Z]/g, "")
    .toUpperCase();
}

function totalMeterMatchKey(value) {
  const normalized = normalizeCode(value);
  return normalized.length > 2 ? normalized.slice(2) : normalized;
}

function scannedBarcodeMatchKey(value) {
  const normalized = normalizeCode(value);
  if (normalized.length >= 22) return normalized.slice(11, -1);
  if (normalized.length >= 13) return normalized.slice(0, -1);
  return totalMeterMatchKey(normalized);
}

function meterCodeCandidates(value) {
  const normalized = normalizeCode(value);
  const candidates = new Set([normalized, totalMeterMatchKey(normalized), scannedBarcodeMatchKey(normalized)]);
  if (normalized.length > 2) candidates.add(normalized.slice(2));
  if (normalized.length > 12) candidates.add(normalized.slice(0, -1));
  if (normalized.length > 12) candidates.add(normalized.slice(11, -1));
  candidates.delete("");
  return candidates;
}

function groupMeterCandidates(group) {
  const candidates = new Set();
  [group?.meter_no, group?.meter_match_key, group?.id].forEach((value) => {
    meterCodeCandidates(value).forEach((candidate) => candidates.add(candidate));
  });
  return candidates;
}

function matchesGroupQuery(group, query) {
  const tokens = queryTokens(query);
  if (!tokens.length) return true;
  const blob = groupSearchBlob(group);
  return tokens.every((token) => fuzzyIncludes(blob, token));
}

function addressNumber(text, unitPattern) {
  const match = String(text || "").match(new RegExp(`([a-z]?\\d+(?:-\\d+)?)(?=${unitPattern})`, "i"));
  return match ? match[1] : "";
}

function addressSortKey(group) {
  const address = normalizeSearchText(group.address || "");
  return [
    address ? 0 : 1,
    address.replace(/\d+/g, ""),
    addressNumber(address, "弄|巷|里"),
    addressNumber(address, "号"),
    addressNumber(address, "栋|幢|座|楼"),
    addressNumber(address, "单元"),
    addressNumber(address, "层|楼"),
    addressNumber(address, "室|房"),
    addressNumber(address, "车位"),
    address,
    normalizeSearchText(group.meter_no || group.id || "")
  ];
}

function compareGroupsByAddress(a, b) {
  const ak = addressSortKey(a);
  const bk = addressSortKey(b);
  for (let index = 0; index < ak.length; index += 1) {
    const diff = zhAddressCollator.compare(String(ak[index]), String(bk[index]));
    if (diff) return diff;
  }
  return 0;
}

function sortGroupsByAddress(groups) {
  return [...(groups || [])].sort(compareGroupsByAddress);
}

Page({
  data: {
    taskId: "",
    terminal: "",
    groups: [],
    filteredGroups: [],
    query: "",
    statusFilter: "all",
    filterCounts: { all: 0, unconstructed: 0, cached: 0 },
    offlineMode: false,
    snapshotText: "",
    loading: false,
    uploading: false,
    uploadText: ""
  },

  onLoad(options) {
    this.setData({
      taskId: options.taskId || "",
      terminal: decodeURIComponent(options.terminal || "")
    });
  },

  onShow() {
    if (!api.session()?.access_token) {
      wx.reLaunch({ url: "/pages/login/login" });
      return;
    }
    this.loadGroups();
  },

  async loadGroups() {
    if (!this.data.taskId) return;
    this.setData({ loading: true });
    try {
      const result = await api.getConstructionGroups(this.data.taskId);
      const groups = sortGroupsByAddress(result.items || []);
      const task = {
        id: this.data.taskId,
        terminal: this.data.terminal || groups[0]?.terminal || "",
        construction_claimed_by: api.session()?.user?.username || "constructor",
        construction_enabled: true,
        unconstructed_groups: groups.length
      };
      queue.saveTerminalSnapshot(task, groups);
      this.setData({
        groups,
        offlineMode: false,
        snapshotText: groups.length ? `已缓存整终端 ${groups.length} 个资料组` : "该终端暂无未施工资料组"
      });
      this.applyFilter();
    } catch (error) {
      const snapshot = queue.loadTerminalSnapshot(this.data.taskId);
      if (snapshot) {
        this.setData({
          groups: sortGroupsByAddress(snapshot.groups || []),
          terminal: this.data.terminal || snapshot.terminal || "",
          offlineMode: true,
          snapshotText: `离线包：${snapshot.groups?.length || 0} 个资料组`
        });
        this.applyFilter();
        wx.showToast({ title: "已加载终端离线包", icon: "none" });
      } else {
        wx.showToast({ title: error.message || "加载失败", icon: "none" });
      }
    } finally {
      this.setData({ loading: false });
    }
  },

  onQueryInput(event) {
    this.setData({ query: event.detail.value });
    this.applyFilter();
  },

  findGroupByMeterCode(value) {
    const scanned = meterCodeCandidates(value);
    if (!scanned.size) return null;
    const exact = this.data.groups.find((group) => {
      const groupKeys = groupMeterCandidates(group);
      return [...scanned].some((candidate) => groupKeys.has(candidate));
    });
    if (exact) return exact;
    const normalized = normalizeSearchText(value);
    const loose = this.data.groups.filter((group) => groupSearchBlob(group).includes(normalized));
    return loose.length === 1 ? loose[0] : null;
  },

  async scanMeter() {
    try {
      const res = await new Promise((resolve, reject) => {
        wx.scanCode({
          onlyFromCamera: false,
          scanType: ["barCode", "qrCode"],
          success: resolve,
          fail: (error) => reject(new Error(error.errMsg || "扫码失败"))
        });
      });
      const code = String(res.result || "").trim();
      if (!code) {
        wx.showToast({ title: "未识别到表号", icon: "none" });
        return;
      }
      const group = this.findGroupByMeterCode(code);
      this.setData({ query: code });
      if (!group) {
        this.applyFilter();
        wx.showToast({ title: "当前终端未找到该表号", icon: "none" });
        return;
      }
      wx.navigateTo({ url: `/pages/collect/collect?taskId=${this.data.taskId}&groupId=${encodeURIComponent(group.id)}` });
    } catch (error) {
      wx.showToast({ title: error.message || "扫码失败", icon: "none" });
    }
  },

  onStatusFilter(event) {
    this.setData({ statusFilter: event.currentTarget.dataset.filter || "all" });
    this.applyFilter();
  },

  logout() {
    getApp().clearSession();
    wx.reLaunch({ url: "/pages/login/login" });
  },

  async uploadCached() {
    if (!getApp().globalData.online) {
      wx.showToast({ title: "当前离线，无法上传", icon: "none" });
      return;
    }
    const activeGroupIds = {};
    this.data.groups.forEach((group) => {
      activeGroupIds[String(group.id)] = true;
    });
    const readyItems = queue.listCacheItems({ activeGroupIds }).filter((item) => (
      item.ready && !item.stale && String(item.taskId || "") === String(this.data.taskId)
    ));
    if (!readyItems.length) {
      wx.showToast({ title: "已缓存中没有完整资料组", icon: "none" });
      return;
    }
    this.setData({ uploading: true, uploadText: "正在上传已缓存资料组..." });
    try {
      const result = await queue.processAllCaches((event) => {
        this.setData({ uploadText: `正在上传 ${event.index + 1}/${event.total}，${event.progress?.progress || 0}%` });
      }, { taskId: this.data.taskId, activeGroupIds });
      this.setData({ uploadText: `完成 ${result.uploaded} 组，失败 ${result.failed} 组` });
      await this.loadGroups();
    } catch (error) {
      this.setData({ uploadText: error.message || "上传失败" });
    } finally {
      this.setData({ uploading: false });
    }
  },

  applyFilter() {
    const query = this.data.query.trim();
    const cacheItems = queue.listCacheItems({ includeStale: false });
    const cacheMap = {};
    cacheItems.forEach((item) => {
      if (String(item.taskId || "") === String(this.data.taskId) && item.groupId) {
        cacheMap[String(item.groupId)] = item;
      }
    });
    const groups = sortGroupsByAddress(this.data.groups).map((group) => {
      const cached = cacheMap[String(group.id)] || null;
      return {
        ...group,
        isCached: Boolean(cached),
        cachePhotoCount: cached?.photos?.length || 0,
        cacheModule: cached?.module_asset_no || "",
        statusText: cached ? "已缓存" : "未施工",
        statusClass: cached ? "ok" : "warn"
      };
    });
    const byQuery = query ? groups.filter((group) => matchesGroupQuery(group, query)) : groups;
    const cachedCount = byQuery.filter((group) => group.isCached).length;
    const filtered = byQuery.filter((group) => {
      if (this.data.statusFilter === "cached") return group.isCached;
      if (this.data.statusFilter === "unconstructed") return !group.isCached;
      return true;
    });
    this.setData({
      filteredGroups: filtered,
      filterCounts: {
        all: byQuery.length,
        cached: cachedCount,
        unconstructed: byQuery.length - cachedCount
      }
    });
  },

  openCollect(event) {
    const groupId = event.currentTarget.dataset.id;
    wx.navigateTo({ url: `/pages/collect/collect?taskId=${this.data.taskId}&groupId=${encodeURIComponent(groupId)}` });
  }
});
