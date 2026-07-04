# Field Template Hierarchy Hints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carry field hierarchy semantics from graphical field configuration into template preview and downloaded template guidance.

**Architecture:** The backend template service remains the authority for template fields. It will include hierarchy metadata in preview `field_rows` and the workbook `fields` sheet; the frontend API mapping keeps those values, and `FieldGraphDesigner.vue` renders compact hierarchy hints in the template binding preview.

**Tech Stack:** Python template service, Vue 3, TypeScript, Element Plus, Node guard scripts, Vite build.

---

### Task 1: Add Guard

**Files:**
- Create: `scripts/verify_field_template_hierarchy_hints.js`

- [x] **Step 1: Write failing guard**

The guard requires backend tokens:

- `template_hierarchy_role`
- `_template_hierarchy_role`
- `_template_parent_label`
- `_template_condition_hint`
- `parent_key`
- `relation_role`
- `required_when`
- workbook headers `层级角色`, `父字段`, `条件采集`

The guard requires frontend tokens:

- `parentKey`
- `relationRole`
- `requiredWhen`
- `showInConstructionPanel`
- `templateHierarchyHint`
- `template-preview-field-list`
- `任务核心`
- `附属设备确认`
- `条件采集`

- [x] **Step 2: Verify red**

Run:

```powershell
node scripts\verify_field_template_hierarchy_hints.js
```

Expected: fails before implementation because the template metadata is not yet wired.

Result before implementation: `[FAIL] backend preview must expose a readable hierarchy role`.

### Task 2: Add Backend Template Metadata

**Files:**
- Modify: `v2-api/app/services/platform/templates.py`

- [x] **Step 1: Add helper functions**

Add helpers that convert `relation_role`, `parent_key`, and `required_when` into readable template hints.

- [x] **Step 2: Extend preview field rows**

Include raw hierarchy metadata plus readable hints in `build_project_template_preview()`.

- [x] **Step 3: Extend downloaded workbook fields sheet**

Add `层级角色`, `父字段`, and `条件采集` columns to the `fields` sheet so downloaded templates keep the same operator guidance.

### Task 3: Map API Types And Frontend UI

**Files:**
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- Modify: `v2-web/src/views/ProjectsView.vue`

- [x] **Step 1: Extend preview field types**

Add hierarchy fields to `ProjectTemplatePreviewField`.

- [x] **Step 2: Map backend preview metadata**

Map snake_case backend preview fields to frontend camelCase values.

- [x] **Step 3: Pass full preview field rows into field graph**

Keep existing label tag lists, but also pass field row metadata into `FieldGraphDesigner.vue`.

- [x] **Step 4: Render compact hierarchy hints**

Show each template field with label, hierarchy role, parent hint, and conditional hint in the template binding preview.

### Task 4: Verify And Document

**Files:**
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Modify: `docs/superpowers/plans/2026-07-03-field-template-hierarchy-hints.md`
- Create: `docs/reports/pm-platform-field-template-hierarchy-hints-2026-07-03.md`

- [x] **Step 1: Run verification**

Run:

```powershell
node scripts\verify_field_template_hierarchy_hints.js
node scripts\verify_vue_project_field_graph_template_actions.js
node scripts\verify_vue_field_graph_backend_readiness_echo.js
python scripts\verify_platform_line_loss_template_contract.py
pnpm --dir v2-web build
```

Result: all commands passed. The frontend build retained the existing VueUse annotation and large chunk warnings.

- [x] **Step 2: Browser smoke**

Open `/platform-projects`, open field configuration, and verify template binding preview shows hierarchy hints such as `任务核心`, `附属设备确认`, or `条件采集`.

Result: after restarting local port `52147`, `字段配置：更换终端` showed two `.template-preview-field-list` sections, 29 field cards, and visible `任务核心`, `附属设备确认`, `条件采集`, and `父字段` hints.

- [x] **Step 3: Safety checks**

Run:

```powershell
git diff --check
git status --short -- .env data uploads v2-api/data v2-api/app/static/uploads
```

Result: both commands passed with no output.

- [x] **Step 4: Record results**

Update this plan, the report, and team memory with verification, risks, migration notes, and rollback notes.
