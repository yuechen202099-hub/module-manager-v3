# Delivery Archive Hierarchy Evidence Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a delivery-package evidence coverage summary on the project board, grouping required archive evidence by the same device hierarchy semantics used in construction and review.

**Architecture:** Reuse the existing delivery archive manifest data. Compute a small frontend summary from `requiredEvidence.fields` and `requiredEvidence.photos`, grouping evidence by `relationRole`, `requiredWhen`, and KPI-like keys; render compact cards inside the existing delivery archive manifest preview.

**Tech Stack:** Vue 3, TypeScript, Element Plus, Node static guard scripts, Vite build.

---

### Task 1: Add Guard

**Files:**
- Create: `scripts/verify_vue_delivery_archive_hierarchy_evidence_summary.js`

- [x] **Step 1: Write the failing guard**

The guard requires `ProjectBoardView.vue` to compute and render `platformArchiveEvidenceHierarchySummary`, `archiveEvidenceHierarchyIntentLabel`, and the visible label `交付证据覆盖摘要`.

- [x] **Step 2: Run guard to verify it fails**

Run: `node scripts\verify_vue_delivery_archive_hierarchy_evidence_summary.js`

Observed: `[FAIL] board must render archive evidence summary`

### Task 2: Compute Delivery Evidence Coverage

**Files:**
- Modify: `v2-web/src/views/ProjectBoardView.vue`

- [x] **Step 1: Add `ArchiveEvidenceHierarchySummaryCard` type**

The type stores `id`, `label`, `helper`, `count`, `fieldCount`, `photoCount`, `className`, and `items`.

- [x] **Step 2: Add grouping helpers**

Add `archiveEvidenceHierarchyIntentLabel()` to map:

- `requiredWhen.fieldKey` -> `条件补采`
- `replacement_device` -> `主设备本体`
- `accessory_replace_confirm` -> `附属设备确认`
- `old_device` or `accessory_new_device` -> `任务对象下的附属设备`
- `evidence_photo` -> `照片证据`
- KPI keys such as `installer`, `started_at`, `completed_at`, `uploaded_at`, `online_duration_minutes`, `photo_count`, `old_device_recovered` -> `KPI资料`

- [x] **Step 3: Add computed summary**

Merge required field evidence and required photo evidence into one list, then group it into summary cards in the order: main device, accessory, accessory confirmation, conditional follow-up, photo evidence, KPI, supplemental.

### Task 3: Render And Verify

**Files:**
- Modify: `v2-web/src/views/ProjectBoardView.vue`
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Create: `docs/reports/pm-platform-delivery-archive-hierarchy-evidence-summary-2026-07-03.md`

- [x] **Step 1: Render cards**

Render the summary under the existing delivery archive manifest KPI cards, using class `platform-archive-evidence-summary`.

- [x] **Step 2: Style cards**

Add responsive card styling without nesting cards inside cards.

- [x] **Step 3: Run verification**

Run:

```powershell
node scripts\verify_vue_delivery_archive_hierarchy_evidence_summary.js
node scripts\verify_vue_delivery_archive_manifest_evidence_details.js
node scripts\verify_vue_delivery_archive_manifest.js
python scripts\verify_platform_delivery_archive_manifest.py
pnpm --dir v2-web build
```

Observed:

- `node scripts\verify_vue_delivery_archive_hierarchy_evidence_summary.js` -> `[OK] Vue delivery archive hierarchy evidence summary is visible.`
- `node scripts\verify_vue_delivery_archive_manifest_evidence_details.js` -> `[OK] Vue delivery archive manifest evidence details are visible.`
- `node scripts\verify_vue_delivery_archive_manifest.js` -> `[OK] Vue delivery archive manifest is wired.`
- `python scripts\verify_platform_delivery_archive_manifest.py` -> `[OK] platform delivery archive manifest is summarized`
- `python scripts\verify_pm_platform_team_operating_model.py` -> `[OK] PM platform team operating model is locked`
- `pnpm --dir v2-web build` -> passed with existing VueUse annotation and large chunk warnings.

- [x] **Step 4: Browser smoke**

Open `/project-board?project_id=draft-project` and verify the delivery archive section includes `交付证据覆盖摘要`, `主设备本体`, `任务对象下的附属设备`, `附属设备确认`, `条件补采`, `照片证据`, and `KPI资料`.

Observed at `http://127.0.0.1:52147/project-board?project_id=draft-project`: 6 summary cards, including `KPI资料` with `7项证据`, plus `换模块：任务对象下换附属设备` and `换终端：主设备更换并确认附属设备`.

- [x] **Step 5: Safety checks**

Run `git diff --check` and `git status --short -- .env data uploads v2-api/data v2-api/app/static/uploads`.

Observed: both commands passed with no output. Local preview is listening on `127.0.0.1:52147`.
