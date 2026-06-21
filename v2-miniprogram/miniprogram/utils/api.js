const { DEFAULT_API_BASE } = require("./config");

function app() {
  return getApp();
}

function apiBase() {
  app().globalData.apiBase = DEFAULT_API_BASE;
  wx.setStorageSync("apiBase", DEFAULT_API_BASE);
  return DEFAULT_API_BASE;
}

function session() {
  return app().globalData.session || wx.getStorageSync("session") || null;
}

function teamId() {
  const current = session();
  return current?.team_id || wx.getStorageSync("teamId") || "default-team";
}

function headers(extra = {}) {
  const current = session();
  const auth = current?.access_token
    ? { Authorization: `${current.token_type || "bearer"} ${current.access_token}` }
    : {};
  return {
    "X-Team-Id": teamId(),
    ...auth,
    ...extra
  };
}

function unwrap(response) {
  const payload = response.data || {};
  if (response.statusCode === 401) {
    app().clearSession();
    wx.reLaunch({ url: "/pages/login/login" });
    throw new Error("登录已过期，请重新登录");
  }
  if (response.statusCode < 200 || response.statusCode >= 300 || payload.error) {
    throw new Error(localizeError(payload.detail || payload.error?.message || response.errMsg || "请求失败"));
  }
  return payload.data;
}

function localizeError(message) {
  const text = String(message || "请求失败");
  const claimed = text.match(/Current account already claimed terminal\s+([^.\s]+)/i);
  if (claimed) return `当前账号已领取终端 ${claimed[1]}，请先释放后再领取其他终端`;
  if (/Construction task is not open/i.test(text)) return "该终端尚未开放施工";
  if (/Construction task is already claimed/i.test(text)) return "该终端已被其他施工员领取";
  if (/Only the current constructor can release this task/i.test(text)) return "只有当前施工员可以释放该终端";
  if (/Task not found/i.test(text)) return "任务不存在或已被删除";
  return text;
}

function request(path, options = {}) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${apiBase()}${path}`,
      method: options.method || "GET",
      data: options.data || undefined,
      header: headers({ "Content-Type": "application/json", ...(options.header || {}) }),
      timeout: options.timeout || 30000,
      success: (res) => {
        try {
          resolve(unwrap(res));
        } catch (error) {
          reject(error);
        }
      },
      fail: (error) => reject(new Error(error.errMsg || "网络请求失败"))
    });
  });
}

function uploadPhoto(groupId, draft, photo, onProgress) {
  return new Promise((resolve, reject) => {
    const task = wx.uploadFile({
      url: `${apiBase()}/local-test/construction/groups/${encodeURIComponent(groupId)}/upload-batch`,
      filePath: photo.filePath,
      name: "files",
      header: headers(),
      formData: {
        actor: draft.actor,
        client_batch_id: draft.client_batch_id,
        collector: draft.collector || "",
        module_asset_no: draft.module_asset_no || "",
        photo_slots: photo.slot || "other",
        client_photo_ids: photo.client_photo_id
      },
      success: (res) => {
        try {
          const payload = JSON.parse(res.data || "{}");
          resolve(unwrap({ statusCode: res.statusCode, data: payload, errMsg: res.errMsg }));
        } catch (error) {
          reject(error);
        }
      },
      fail: (error) => reject(new Error(error.errMsg || "上传失败"))
    });
    if (typeof onProgress === "function") {
      task.onProgressUpdate((progress) => onProgress(progress));
    }
  });
}

function submitConstructionExceptionOrder(orderId, draft = {}) {
  return request(`/local-test/construction/exception-orders/${encodeURIComponent(orderId)}/submit`, {
    method: "PATCH",
    data: {
      actor: draft.actor || session()?.user?.username || "constructor",
      updates: {
        meter_no: draft.meter_no || "",
        collector: draft.collector || "",
        module_asset_no: draft.module_asset_no || ""
      },
      note: "现场已处理异常工单"
    }
  });
}

function login(username, password, team_id) {
  return request("/auth/login", {
    method: "POST",
    data: { username, password, team_id }
  });
}

function getConstructionTasks(actor, includeClosed = false) {
  return request(`/local-test/construction/tasks?actor=${encodeURIComponent(actor)}&include_closed=${includeClosed ? "true" : "false"}`);
}

function claimConstructionTask(taskId, actor) {
  return request(`/local-test/construction/tasks/${taskId}/claim`, {
    method: "POST",
    data: { actor }
  });
}

function releaseConstructionTask(taskId, actor) {
  return request(`/local-test/construction/tasks/${taskId}/release`, {
    method: "POST",
    data: { actor }
  });
}

function getConstructionGroups(taskId) {
  return request(`/local-test/construction/tasks/${taskId}/groups?limit=1000&summary=true`);
}

function getGroup(groupId) {
  return request(`/local-test/groups/${encodeURIComponent(groupId)}`);
}

module.exports = {
  apiBase,
  headers,
  login,
  getConstructionTasks,
  claimConstructionTask,
  releaseConstructionTask,
  getConstructionGroups,
  getGroup,
  uploadPhoto,
  submitConstructionExceptionOrder,
  request,
  session,
  teamId
};
