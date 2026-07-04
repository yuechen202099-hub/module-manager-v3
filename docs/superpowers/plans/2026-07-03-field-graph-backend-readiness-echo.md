# Field Graph Backend Readiness Echo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show backend `device_hierarchy` readiness evidence directly inside the graphical field configuration experience.

**Architecture:** Keep backend readiness as the saved-configuration authority. `/platform-projects` passes the saved project's `device_hierarchy` readiness check into `FieldGraphDesigner.vue`; the designer renders a backend echo panel and highlights field graph nodes whose keys appear in backend evidence gaps.

**Tech Stack:** Vue 3, TypeScript, Element Plus, Node guard scripts, Vite build.

---

### Task 1: Add Guard

**Files:**
- Create: `scripts/verify_vue_field_graph_backend_readiness_echo.js`

- [x] **Step 1: Write failing guard**

The guard requires:

- `type BackendDeviceHierarchyReadinessCheck`
- `type BackendDeviceHierarchyIssue`
- `backend-readiness-check`
- `const schemaDeviceHierarchyReadinessCheck`
- `const backendDeviceHierarchyIssues`
- `const backendDeviceHierarchyIssueKeys`
- `function backendDeviceHierarchyIssueList`
- `function backendDeviceHierarchyEvidenceList`
- visible copy `后端上线检查回显`, `设备更换层级`, `后端已通过`, `后端需补齐`
- evidence keys `missing_parent_keys`, `missing_confirmation_keys`, `invalid_conditional_keys`, `unconditional_child_keys`, `confirmation_without_child_keys`, `missing_main_accessory_confirmation`
- node class `backend-issue-node`

- [x] **Step 2: Verify red**

Run:

```powershell
node scripts\verify_vue_field_graph_backend_readiness_echo.js
```

Result before implementation: `[FAIL] designer must define backend readiness check type`.

### Task 2: Render Backend Echo In Field Graph

**Files:**
- Modify: `v2-web/src/components/project-fields/FieldGraphDesigner.vue`

- [x] **Step 1: Add backend readiness prop and types**

Accept a nullable backend readiness check with `status`, `action`, and `evidence`.

- [x] **Step 2: Map backend evidence to operator issues**

Map backend evidence arrays into short business-language issue rows:

- `missing_parent_keys`: fields not attached to the task object
- `missing_confirmation_keys`: confirmation-like fields missing the confirmation role
- `invalid_conditional_keys`: conditional fields not linked to a valid confirmation field
- `unconditional_child_keys`: terminal accessory children that must be conditional
- `confirmation_without_child_keys`: confirmation fields with no conditional child
- `missing_main_accessory_confirmation`: terminal replacement missing accessory confirmation

- [x] **Step 3: Highlight nodes**

Add `backend-issue-node` class to mind-map nodes whose `key` is in backend issue evidence.

### Task 3: Wire Projects View

**Files:**
- Modify: `v2-web/src/views/ProjectsView.vue`

- [x] **Step 1: Add computed device hierarchy check**

Add `schemaDeviceHierarchyReadinessCheck` from `schemaProjectReadiness.checks`.

- [x] **Step 2: Pass prop**

Pass `:backend-readiness-check="schemaDeviceHierarchyReadinessCheck"` to the schema dialog `FieldGraphDesigner`.

### Task 4: Verify And Document

**Files:**
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Modify: `docs/superpowers/plans/2026-07-03-field-graph-backend-readiness-echo.md`
- Create: `docs/reports/pm-platform-field-graph-backend-readiness-echo-2026-07-03.md`

- [x] **Step 1: Run verification**

Run:

```powershell
node scripts\verify_vue_field_graph_backend_readiness_echo.js
node scripts\verify_vue_field_graph_hierarchy_save_gate.js
node scripts\verify_vue_device_hierarchy_config.js
python scripts\verify_platform_project_readiness.py
python scripts\verify_pm_platform_team_operating_model.py
pnpm --dir v2-web build
```

Result: all commands passed. The build retained the existing VueUse annotation and large chunk warnings.

- [x] **Step 2: Browser smoke**

Open `/platform-projects`, open field configuration, and verify visible text includes `后端上线检查回显`, `设备更换层级`, and either `后端已通过` or `后端需补齐`.

Result: `/platform-projects` on `http://127.0.0.1:52147/` opened `字段配置：更换终端`; the backend echo panel rendered once with `后端已通过`, and no backend issue nodes were highlighted for that saved configuration.

- [x] **Step 3: Safety checks**

Run:

```powershell
git diff --check
git status --short -- .env data uploads v2-api/data v2-api/app/static/uploads
```

Result: both commands passed with no output.

- [x] **Step 4: Record results**

Update this plan, the report, and team memory with verification, risks, migration notes, and rollback notes.
