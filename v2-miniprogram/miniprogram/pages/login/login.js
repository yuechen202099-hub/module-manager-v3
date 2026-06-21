const api = require("../../utils/api");

Page({
  data: {
    teamId: "default-team",
    username: "constructor",
    password: "",
    loading: false
  },

  onLoad() {
    this.setData({
      teamId: wx.getStorageSync("teamId") || "default-team",
      username: wx.getStorageSync("lastUsername") || "constructor"
    });
  },

  onTeamInput(event) {
    this.setData({ teamId: event.detail.value });
  },

  onUsernameInput(event) {
    this.setData({ username: event.detail.value });
  },

  onPasswordInput(event) {
    this.setData({ password: event.detail.value });
  },

  async login() {
    const username = this.data.username.trim();
    const password = this.data.password;
    const teamId = this.data.teamId.trim() || "default-team";
    if (!username || !password) {
      wx.showToast({ title: "请填写完整", icon: "none" });
      return;
    }
    this.setData({ loading: true });
    try {
      getApp().setApiBase();
      wx.setStorageSync("teamId", teamId);
      const session = await api.login(username, password, teamId);
      const roles = session.user?.roles || [];
      if (!roles.includes("constructor") && !roles.includes("admin")) {
        throw new Error("当前账号不是施工员");
      }
      getApp().setSession(session);
      wx.setStorageSync("lastUsername", username);
      wx.reLaunch({ url: "/pages/tasks/tasks" });
    } catch (error) {
      wx.showToast({ title: error.message || "登录失败", icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  }
});
