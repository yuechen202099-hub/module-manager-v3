# Dashboard Metrics Schema Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make project dashboard metric definitions a structured, round-trippable part of each project field schema.

**Architecture:** The backend remains the source of truth for schema normalization and default metrics. The frontend maps metric objects losslessly, preserves them when saving project field schemas, and exposes the configured dashboard口径 on the project board without changing production versioning or production data.

**Tech Stack:** FastAPI/Pydantic backend, Vue 3 + TypeScript frontend, existing verification scripts under `scripts/`.

---

### Task 1: Backend Contract Guard

**Files:**
- Create: `scripts/verify_platform_dashboard_metrics_contract.py`
- Read: `v2-api/app/services/platform/catalog.py`
- Read: `v2-api/app/schemas/project.py`

- [ ] **Step 1: Write the failing backend verifier**

Create `scripts/verify_platform_dashboard_metrics_contract.py` with assertions that:
- default project schemas expose `dashboard_metrics` as a non-empty list of objects;
- project creation accepts custom metric objects with `key`, `label`, `source`, and `scope`;
- project schema updates preserve the custom metric list.

- [ ] **Step 2: Run verifier and confirm RED**

Run:

```powershell
$env:PYTHONPATH='v2-api'
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\verify_platform_dashboard_metrics_contract.py
```

Expected before implementation: failure because custom `dashboard_metrics` are ignored by the create/update schema path.

### Task 2: Frontend Contract Guard

**Files:**
- Create: `scripts/verify_vue_dashboard_metrics_contract.js`
- Read: `v2-web/src/api/types.ts`
- Read: `v2-web/src/api/services.ts`
- Read: `v2-web/src/views/ProjectsView.vue`
- Read: `v2-web/src/views/ProjectBoardView.vue`

- [ ] **Step 1: Write the failing frontend verifier**

Create `scripts/verify_vue_dashboard_metrics_contract.js` with source checks that require:
- `ProjectDashboardMetric` type;
- backend metric object type;
- typed mapping in both read and create/update directions;
- schema forms preserve `dashboardMetrics`;
- project board renders configured dashboard metric cards.

- [ ] **Step 2: Run verifier and confirm RED**

Run:

```powershell
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' scripts\verify_vue_dashboard_metrics_contract.js
```

Expected before implementation: failure because the frontend currently maps metrics as `string[]` and does not render or preserve them.

### Task 3: Backend Implementation

**Files:**
- Modify: `v2-api/app/schemas/project.py`
- Modify: `v2-api/app/services/platform/catalog.py`

- [ ] **Step 1: Add Pydantic metric input model**

Add `ProjectDashboardMetricCreate` with `key`, `label`, optional `source`, and optional `scope`; add `dashboard_metrics` to `ProjectWorkItemSchemaCreate`.

- [ ] **Step 2: Normalize metric objects**

Add `_normalize_dashboard_metrics(raw_metrics)` in `catalog.py`. It should sanitize keys, preserve labels/source/scope, drop duplicate keys, and fall back to `_DEFAULT_DASHBOARD_METRICS` when no usable custom metric is supplied.

- [ ] **Step 3: Wire schema normalization**

Update `_normalize_work_item_schema` to use `_normalize_dashboard_metrics(raw.get("dashboard_metrics"))`.

- [ ] **Step 4: Run backend verifier and confirm GREEN**

Run the backend verifier from Task 1 and require exit code 0.

### Task 4: Frontend Implementation

**Files:**
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/views/ProjectsView.vue`
- Modify: `v2-web/src/views/ProjectBoardView.vue`

- [ ] **Step 1: Add typed dashboard metric model**

Add `ProjectDashboardMetric` and change `ProjectWorkItemSchema.dashboardMetrics` from `string[]` to `ProjectDashboardMetric[]`.

- [ ] **Step 2: Map metric objects in both directions**

Add `mapDashboardMetric` and `mapDashboardMetricForCreate`; update backend schema types and `mapWorkItemSchemaForCreate`.

- [ ] **Step 3: Preserve metrics in project schema forms**

Add `dashboardMetrics` to `WorkItemSchemaForm`, initialize it in create/schema forms, reset it, hydrate it from `project.workItemSchema`, and include it in `buildWorkItemSchemaPayload`.

- [ ] **Step 4: Show configured metric口径 on project board**

Add `platformDashboardMetricCards` and a compact card band so users can see which configured metrics are powering the project cockpit.

- [ ] **Step 5: Run frontend verifier and confirm GREEN**

Run the frontend verifier from Task 2 and require exit code 0.

### Task 5: Full Verification and Handoff Notes

**Files:**
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Create: `docs/reports/pm-platform-dashboard-metrics-schema-contract-2026-07-03.md`

- [ ] **Step 1: Run targeted backend tests**

Run:

```powershell
$env:PYTHONPATH='v2-api'
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest v2-api\tests\test_api.py::test_review_detail_deep_link_serves_vue_shell -q
```

- [ ] **Step 2: Run project verification scripts**

Run:

```powershell
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\verify_platform_dashboard_metrics_contract.py
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' scripts\verify_vue_dashboard_metrics_contract.js
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\verify_platform_device_replacement_hierarchy_mode.py
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' scripts\verify_vue_device_replacement_hierarchy_mode.js
```

- [ ] **Step 3: Build frontend assets**

Run:

```powershell
$env:PATH='C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin;C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin;' + $env:PATH
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\pnpm.cmd' --dir v2-web build
```

- [ ] **Step 4: Browser smoke**

Open `/project-board?project_id=draft-project` or `/project-board?project_id=replacement-project` on the local server and verify the cockpit renders without current asset console errors.

- [ ] **Step 5: Document migration and rollback**

Write the report with baseline commit, modified files, feature summary, commands/results, risk, and rollback. No production `.env`, data, uploads, tag, release, OSS, or PostgreSQL mutation is allowed.
