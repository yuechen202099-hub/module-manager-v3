# Field Graph Hierarchy Save Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent operators from saving an incomplete graphical device hierarchy for module and terminal replacement projects.

**Architecture:** Keep the existing backend `device_hierarchy` readiness gate as the saved-configuration authority, and add a matching frontend pre-save gate inside `/platform-projects`. `FieldGraphDesigner.vue` computes visible hierarchy readiness cards from the current unsaved field graph; `ProjectsView.vue` uses the same field roles to block save/create when required relationships are missing.

**Tech Stack:** Vue 3, TypeScript, Element Plus, Node static guard scripts, Vite build.

---

### Task 1: Add Guard Scripts

**Files:**
- Create: `scripts/verify_vue_field_graph_hierarchy_save_gate.js`
- Modify: `docs/superpowers/plans/2026-07-03-field-graph-hierarchy-save-gate.md`

- [x] **Step 1: Write the failing guard**

The guard must require:

- `type FieldHierarchyReadinessIssue`
- `const fieldGraphHierarchyReadinessCards`
- `function fieldGraphHierarchyIssueList`
- visible labels `层级完整性`, `可保存`, `需补齐`, `换模块完整性`, `换终端完整性`
- module rule copy `换模块需要在任务对象下保留新附属设备和旧设备/回收证据`
- terminal rule copy `换终端需要主设备更换、旧设备、附属设备确认和条件采集`
- `function validateFieldHierarchyBeforeSave`
- save and create flows call `validateFieldHierarchyBeforeSave(createForm)` and `validateFieldHierarchyBeforeSave(schemaForm)`

- [x] **Step 2: Run guard to verify it fails**

Run:

```powershell
node scripts\verify_vue_field_graph_hierarchy_save_gate.js
```

Expected: fails because the new save gate does not exist yet.

### Task 2: Add Frontend Hierarchy Readiness

**Files:**
- Modify: `v2-web/src/components/project-fields/FieldGraphDesigner.vue`

- [x] **Step 1: Add issue and card types**

Add `FieldHierarchyReadinessIssue` and `FieldHierarchyReadinessCard` near the other local UI types.

- [x] **Step 2: Add `fieldGraphHierarchyIssueList()`**

The function should inspect the current `customFields` and return business-language issues:

- Module replacement mode (`accessory_new_device` without `replacement_device`) needs at least one direct accessory new device and at least one direct old-device or evidence-photo field under the task object.
- Terminal replacement mode (`replacement_device`) needs at least one new main device, one old main device, one accessory confirmation, and one conditional child field linked to an accessory confirmation.

- [x] **Step 3: Add `fieldGraphHierarchyReadinessCards`**

Render scan-friendly cards with:

- `层级完整性`
- `换模块完整性`
- `换终端完整性`
- status labels `可保存` and `需补齐`

### Task 3: Add Save Gate

**Files:**
- Modify: `v2-web/src/views/ProjectsView.vue`

- [x] **Step 1: Add local hierarchy issue helper**

Add `fieldHierarchySaveIssues(form)` and `validateFieldHierarchyBeforeSave(form)` near `validateFieldForm()`.

- [x] **Step 2: Block create and schema save**

Call:

```ts
if (!validateFieldHierarchyBeforeSave(createForm)) return
if (!validateFieldHierarchyBeforeSave(schemaForm)) return
```

before the API request.

### Task 4: Verify And Document

**Files:**
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Create: `docs/reports/pm-platform-field-graph-hierarchy-save-gate-2026-07-03.md`

- [x] **Step 1: Run verification**

Run:

```powershell
node scripts\verify_vue_field_graph_hierarchy_save_gate.js
node scripts\verify_vue_device_hierarchy_config.js
node scripts\verify_vue_field_graph_smart_drop.js
python scripts\verify_platform_project_readiness.py
python scripts\verify_pm_platform_team_operating_model.py
pnpm --dir v2-web build
```

Observed:

- `node scripts\verify_vue_field_graph_hierarchy_save_gate.js` -> `[OK] Vue field graph hierarchy save gate is wired.`
- `node scripts\verify_vue_device_hierarchy_config.js` -> `[OK] Vue device hierarchy configuration is represented.`
- `node scripts\verify_vue_field_graph_smart_drop.js` -> `[OK] Vue field graph smart drop is wired.`
- `python scripts\verify_platform_project_readiness.py` -> `[OK] platform project readiness is consistent`
- `python scripts\verify_pm_platform_team_operating_model.py` -> `[OK] PM platform team operating model is locked`
- `pnpm --dir v2-web build` -> passed with existing VueUse annotation and large chunk warnings.

- [x] **Step 2: Browser smoke**

Open `/platform-projects`, open field configuration, and verify the field graph shows `层级完整性`, `换模块完整性`, `换终端完整性`, and either `可保存` or `需补齐`.

Observed at `http://127.0.0.1:52147/platform-projects`: first field configuration dialog showed 3 hierarchy cards: `层级完整性`, `换模块完整性`, `换终端完整性`; current sample project showed `可保存`.

- [x] **Step 3: Safety checks**

Run:

```powershell
git diff --check
git status --short -- .env data uploads v2-api/data v2-api/app/static/uploads
```

Observed: both commands passed with no output. Local preview remained listening on `127.0.0.1:52147`.

- [x] **Step 4: Record outcome**

Update this plan, the team operating model, and the report with changed files, verification results, migration notes, rollback notes, and risks.
