(function () {
  const DEFAULT_OPTIONS = {
    maxSide: 1920,
    quality: 0.78,
    mimeType: "image/jpeg",
  };

  function asImageFileName(name) {
    const base = String(name || "photo").replace(/\.[^.]+$/, "") || "photo";
    return `${base}.jpg`;
  }

  function canvasToBlob(canvas, mimeType, quality) {
    return new Promise((resolve) => {
      canvas.toBlob((blob) => resolve(blob), mimeType, quality);
    });
  }

  function loadImageElement(file) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const image = new Image();
      image.onload = () => {
        URL.revokeObjectURL(url);
        resolve(image);
      };
      image.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error("Image decode failed"));
      };
      image.src = url;
    });
  }

  async function loadDrawable(file) {
    if ("createImageBitmap" in window) {
      try {
        const bitmap = await createImageBitmap(file);
        return {
          drawable: bitmap,
          width: bitmap.width,
          height: bitmap.height,
          close: () => bitmap.close?.(),
        };
      } catch {}
    }
    const image = await loadImageElement(file);
    return {
      drawable: image,
      width: image.naturalWidth || image.width,
      height: image.naturalHeight || image.height,
      close: () => {},
    };
  }

  async function compressImageFile(file, options = {}) {
    const config = { ...DEFAULT_OPTIONS, ...options };
    if (!(file instanceof Blob) || !String(file.type || "").startsWith("image/")) {
      return {
        blob: file,
        file,
        name: file?.name || "upload.bin",
        originalSize: file?.size || 0,
        compressedSize: file?.size || 0,
        compressed: false,
      };
    }

    const sourceName = options.name || file.name || "photo.jpg";
    const image = await loadDrawable(file);
    try {
      const scale = Math.min(1, config.maxSide / Math.max(image.width, image.height));
      const width = Math.max(1, Math.round(image.width * scale));
      const height = Math.max(1, Math.round(image.height * scale));
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d", { alpha: false });
      context.imageSmoothingEnabled = true;
      context.imageSmoothingQuality = "high";
      context.drawImage(image.drawable, 0, 0, width, height);
      const blob = await canvasToBlob(canvas, config.mimeType, config.quality);
      if (!blob) throw new Error("Image compression failed");

      const originalSize = file.size || blob.size;
      const shouldUseCompressed = blob.size < originalSize || scale < 1 || file.type !== config.mimeType;
      const outputBlob = shouldUseCompressed ? blob : file;
      const name = shouldUseCompressed ? asImageFileName(sourceName) : sourceName;
      let outputFile = outputBlob;
      try {
        outputFile = new File([outputBlob], name, {
          type: outputBlob.type || config.mimeType,
          lastModified: Date.now(),
        });
      } catch {
        outputBlob.name = name;
      }
      return {
        blob: outputFile,
        file: outputFile,
        name,
        originalSize,
        compressedSize: outputFile.size,
        compressed: shouldUseCompressed,
      };
    } finally {
      image.close();
    }
  }

  async function compressImageFiles(files, options = {}) {
    const output = [];
    for (const file of Array.from(files || [])) {
      output.push(await compressImageFile(file, options));
    }
    return output;
  }

  window.ModuleImageUpload = {
    compressImageFile,
    compressImageFiles,
  };
})();
