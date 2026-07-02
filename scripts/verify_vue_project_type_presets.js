const fs = require("fs");
const path = require("path");

const root = process.cwd();
const source = fs.readFileSync(path.join(root, "v2-web", "src", "views", "ProjectsView.vue"), "utf8");

const requiredTokens = [
  "type ProjectTypePreset",
  "const projectTypePresets",
  "applyCreateProjectTypePreset",
  "更换终端",
  "终端（需更换）",
  "旧设备（拆回）",
  "通讯模块（需更换）",
  "新SIM卡",
  "改造前照片",
  "旧设备回收照片",
  "新旧模块照片",
  "改造后照片",
  "old_device_no",
  "old_device_recovery_photo",
  "captureMethod: 'scan'",
  "captureMethod: 'photo'",
  "dataType: 'image'",
  "v-model=\"selectedProjectTypePresetId\"",
];

const missing = requiredTokens.filter((token) => !source.includes(token));
if (missing.length) {
  for (const token of missing) {
    console.error(`[FAIL] Projects view missing project type preset token: ${token}`);
  }
  process.exit(1);
}

console.log("[OK] Vue project creation exposes reusable project type presets.");
