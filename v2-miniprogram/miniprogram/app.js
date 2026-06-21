const { DEFAULT_API_BASE } = require("./utils/config");
const queue = require("./utils/queue");

App({
  globalData: {
    apiBase: DEFAULT_API_BASE,
    session: null,
    online: true,
    networkType: "unknown"
  },

  onLaunch() {
    const session = wx.getStorageSync("session") || null;
    this.globalData.apiBase = DEFAULT_API_BASE;
    wx.setStorageSync("apiBase", DEFAULT_API_BASE);
    this.globalData.session = session;

    wx.getNetworkType({
      success: (res) => {
        this.globalData.networkType = res.networkType;
        this.globalData.online = res.networkType !== "none";
      }
    });

    wx.onNetworkStatusChange((res) => {
      this.globalData.networkType = res.networkType;
      this.globalData.online = res.isConnected;
      if (res.isConnected) {
        queue.processQueue().catch(() => {});
      }
    });
  },

  setApiBase() {
    this.globalData.apiBase = DEFAULT_API_BASE;
    wx.setStorageSync("apiBase", DEFAULT_API_BASE);
  },

  setSession(session) {
    this.globalData.session = session;
    wx.setStorageSync("session", session);
    if (session && session.team_id) {
      wx.setStorageSync("teamId", session.team_id);
    }
  },

  clearSession() {
    this.globalData.session = null;
    wx.removeStorageSync("session");
  }
});
