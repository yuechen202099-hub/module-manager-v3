function chooseOneImage() {
  return new Promise((resolve, reject) => {
    wx.chooseMedia({
      count: 1,
      mediaType: ["image"],
      sourceType: ["camera", "album"],
      camera: "back",
      success: (res) => {
        const file = res.tempFiles && res.tempFiles[0];
        if (!file?.tempFilePath) reject(new Error("未选择照片"));
        else resolve(file.tempFilePath);
      },
      fail: (error) => reject(new Error(error.errMsg || "选择照片失败"))
    });
  });
}

function compressImage(src) {
  return new Promise((resolve) => {
    wx.compressImage({
      src,
      quality: 72,
      success: (res) => resolve(res.tempFilePath || src),
      fail: () => resolve(src)
    });
  });
}

function saveImageFile(tempFilePath) {
  return new Promise((resolve, reject) => {
    wx.saveFile({
      tempFilePath,
      success: (res) => resolve(res.savedFilePath || tempFilePath),
      fail: (error) => reject(new Error(error.errMsg || "保存照片缓存失败"))
    });
  });
}

function saveImageToAlbum(filePath) {
  return new Promise((resolve) => {
    if (!filePath || !wx.saveImageToPhotosAlbum) {
      resolve({ saved: false, reason: "unsupported" });
      return;
    }
    wx.saveImageToPhotosAlbum({
      filePath,
      success: () => resolve({ saved: true }),
      fail: (error) => resolve({ saved: false, reason: error.errMsg || "save album failed" })
    });
  });
}

async function chooseCompressedSavedImage(options = {}) {
  const selected = await chooseOneImage();
  if (options.saveToAlbum !== false) {
    const albumResult = await saveImageToAlbum(selected);
    if (!albumResult.saved && /auth|authorize|permission|deny/i.test(albumResult.reason || "")) {
      wx.showToast({ title: "未授权保存到相册，已保留本机缓存", icon: "none" });
    }
  }
  const compressed = await compressImage(selected);
  return await saveImageFile(compressed);
}

module.exports = {
  chooseOneImage,
  compressImage,
  saveImageFile,
  saveImageToAlbum,
  chooseCompressedSavedImage
};
