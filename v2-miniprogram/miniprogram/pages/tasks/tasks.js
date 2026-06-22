const api = require("../../utils/api");
const queue = require("../../utils/queue");

const MAX_ACTIVE_CONSTRUCTION_TASKS = 5;

Page({
  data: {
    actor: "",
    tasks: [],
    hasClaimedTask: false,
    claimedTaskId: "",
    claimedTaskIds: [],
    claimedTerminal: "",
    listTitle: "可处理终端",
    listHint: "0 个可处理终端",
    queueCount: 0,
    readyCacheCount: 0,
    loading: false,
    online: true
  },

  onShow() {
    this.ensureLogin();
    this.refresh();
  },

  ensureLogin() {
    const session = api.session();
    if (!session?.access_token) {
      wx.reLaunch({ url: "/pages/login/login" });
      return;
    }
    const summary = queue.getCacheSummary();
    this.setData({
      actor: session.user?.username || "constructor",
      queueCount: summary.total,
      readyCacheCount: summary.ready,
      online: getApp().globalData.online
    });
  },

  async refresh() {
    const actor = this.data.actor || api.session()?.user?.username || "constructor";
    const summary = queue.getCacheSummary();
    this.setData({
      loading: true,
      queueCount: summary.total,
      readyCacheCount: summary.ready,
      online: getApp().globalData.online
    });
    try {
      const result = await api.getConstructionTasks(actor, false);
      const items = result.items || [];
      const mine = items.filter((task) => task.construction_claimed_by === actor);
      const visibleTasks = (mine.length ? mine : items).map((task) => this.decorateTask(task, actor));
      this.setData({
        tasks: visibleTasks,
        hasClaimedTask: mine.length > 0,
        claimedTaskId: mine[0]?.id || "",
        claimedTaskIds: mine.map((task) => String(task.id)),
        claimedTerminal: mine[0]?.terminal || "",
        listTitle: mine.length ? "我的施工终端" : "可处理终端",
        listHint: mine.length
          ? `当前账号已指派 ${mine.length}/${MAX_ACTIVE_CONSTRUCTION_TASKS} 个终端`
          : `${items.length} 个可处理终端`
      });
    } catch (error) {
      const snapshots = queue.listTerminalSnapshots()
        .sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")))
        .slice(0, MAX_ACTIVE_CONSTRUCTION_TASKS);
      if (snapshots.length) {
        const offlineTasks = snapshots.map((snapshot) => this.decorateTask({
          ...(snapshot.task || {}),
          id: snapshot.taskId,
          terminal: snapshot.terminal || snapshot.task?.terminal || "",
          construction_claimed_by: actor,
          construction_enabled: true,
          offline_cached: true,
          unconstructed_groups: snapshot.groups?.length || 0
        }, actor));
        this.setData({
          tasks: offlineTasks,
          hasClaimedTask: true,
          claimedTaskId: offlineTasks[0]?.id || "",
          claimedTaskIds: offlineTasks.map((task) => String(task.id)),
          claimedTerminal: offlineTasks[0]?.terminal || "",
          listTitle: "离线施工终端",
          listHint: `已使用本机缓存，可继续采集 ${offlineTasks.length} 个终端`
        });
      } else {
        wx.showToast({ title: error.message || "加载失败", icon: "none" });
      }
    } finally {
      this.setData({ loading: false });
    }
  },

  async claimTask(event) {
    const id = event.currentTarget.dataset.id;
    const task = this.findTask(id);
    if (task?.construction_claimed_by === this.data.actor) {
      this.openGroups(id);
      return;
    }
    const claimedTaskIds = this.data.claimedTaskIds || [];
    if (this.data.hasClaimedTask && !claimedTaskIds.includes(String(id)) && claimedTaskIds.length >= MAX_ACTIVE_CONSTRUCTION_TASKS) {
      wx.showToast({ title: `当前账号已指派 ${MAX_ACTIVE_CONSTRUCTION_TASKS} 个终端，请先释放后再处理其他终端`, icon: "none" });
      return;
    }
    try {
      await api.claimConstructionTask(id, this.data.actor);
      this.openGroups(id);
    } catch (error) {
      await this.refresh();
      wx.showToast({ title: error.message || "领取失败", icon: "none" });
    }
  },

  async releaseTask(event) {
    const id = event.currentTarget.dataset.id;
    try {
      await api.releaseConstructionTask(id, this.data.actor);
      await this.refresh();
    } catch (error) {
      wx.showToast({ title: error.message || "释放失败", icon: "none" });
    }
  },

  openTask(event) {
    const id = event.currentTarget.dataset.id;
    const task = this.findTask(id);
    if (!task) return;
    if (task.construction_claimed_by && task.construction_claimed_by !== this.data.actor) {
      wx.showToast({ title: "该终端已被其他施工员领取", icon: "none" });
      return;
    }
    if (task.construction_claimed_by !== this.data.actor) {
      wx.showToast({ title: "请先领取该终端", icon: "none" });
      return;
    }
    this.openGroups(id);
  },

  findTask(id) {
    return this.data.tasks.find((item) => String(item.id) === String(id));
  },

  openGroups(id) {
    const task = this.findTask(id) || {};
    wx.navigateTo({ url: `/pages/groups/groups?taskId=${id}&terminal=${encodeURIComponent(task.terminal || "")}` });
  },

  decorateTask(task, actor) {
    const claimedBy = task.construction_claimed_by || "";
    const isMine = claimedBy === actor;
    return {
      ...task,
      statusText: task.offline_cached ? "离线缓存" : (claimedBy ? "已领取" : "可领取"),
      statusClass: claimedBy ? "warn" : "ok",
      ownerText: task.offline_cached ? "已加载整终端，可离线施工" : (isMine ? "当前账号正在施工" : `领取人：${claimedBy || "无"}`),
      actionText: isMine ? "继续施工" : "领取施工"
    };
  },

  openCache() {
    wx.navigateTo({ url: "/pages/cache/cache" });
  },

  logout() {
    getApp().clearSession();
    wx.reLaunch({ url: "/pages/login/login" });
  }
});
