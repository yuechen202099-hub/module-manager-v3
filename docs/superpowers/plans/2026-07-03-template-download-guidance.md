# Template Download Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show operators, before downloading a project template, how the Excel workbook maps to field hierarchy, upload-time generated fields, and module/terminal replacement modes.

**Architecture:** Keep the behavior local to the field graph designer because it already owns template preview and download actions. Add a static source-level verifier for the UI contract, then add small computed guide cards and a compact guide panel beside the existing template binding preview.

**Tech Stack:** Vue 3 single-file component, Element Plus buttons/tags, Node-based source verification script.

---

### Task 1: Frontend Guard

**Files:**
- Create: `scripts/verify_vue_template_download_guidance.js`

- [ ] **Step 1: Write the failing verifier**

```js
const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const graphSource = fs.readFileSync(
  path.join(root, 'v2-web', 'src', 'components', 'project-fields', 'FieldGraphDesigner.vue'),
  'utf8',
)

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

for (const token of [
  'templateDownloadGuideCards',
  'template-download-guide',
  'template / fields / instructions',
  'Excel说明页',
  '任务对象下更换附属设备',
  '主设备更换后确认附属设备',
  '换模块下载前会提示附属设备挂在任务对象下',
  '换终端下载前会提示先记录旧主设备和新主设备',
]) {
  if (!graphSource.includes(token)) fail(`FieldGraphDesigner.vue missing download guidance token: ${token}`)
}

console.log('[OK] Vue template download guidance explains workbook sheets and device hierarchy modes.')
```

- [ ] **Step 2: Run verifier to confirm red**

Run: `node scripts/verify_vue_template_download_guidance.js`

Expected: fails on `templateDownloadGuideCards`.

### Task 2: Field Graph UI

**Files:**
- Modify: `v2-web/src/components/project-fields/FieldGraphDesigner.vue`

- [ ] **Step 1: Add guide types and computed cards**

Add `TemplateDownloadGuideCard`, `templateDownloadHierarchyGuide`, and `templateDownloadGuideCards` near the existing template preview computed values.

- [ ] **Step 2: Render guide panel**

Render `<div class="template-download-guide">` after the template impact summary and before the template binding grid.

- [ ] **Step 3: Style guide panel**

Add scoped CSS for `.template-download-guide` and its cards, keeping the panel compact and consistent with the existing design.

- [ ] **Step 4: Verify green**

Run: `node scripts/verify_vue_template_download_guidance.js`

Expected: passes.

### Task 3: Documentation And Verification

**Files:**
- Create: `docs/reports/pm-platform-template-download-guidance-2026-07-03.md`
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

- [ ] **Step 1: Add report**

Record baseline branch, baseline commit, modified files, verification commands, risks, and rollback.

- [ ] **Step 2: Update team ledger**

Append package 60: `Template Download Guidance`.

- [ ] **Step 3: Run final verification**

Run:

```powershell
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' scripts\verify_vue_template_download_guidance.js
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' scripts\verify_vue_template_impact_preview.js
git diff --check
```

Expected: all commands exit 0.
