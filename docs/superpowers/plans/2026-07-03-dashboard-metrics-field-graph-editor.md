# Dashboard Metrics Field Graph Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let operators edit a project's dashboard metric口径 inside the visual field graph configuration screen.

**Architecture:** Keep the backend `dashboard_metrics` contract unchanged. Add a small frontend editor in `FieldGraphDesigner.vue` that receives `dashboardMetrics`, renders recommended metric cards for progress, delivery, field collection, review, and KPI efficiency, and emits updates to `ProjectsView.vue`, which stores them in the existing `WorkItemSchemaForm.dashboardMetrics` array for create/update saves.

**Tech Stack:** Vue 3 + TypeScript, Element Plus, existing project schema API mapping, source-level verification scripts, Vite build.

---

### Task 1: Frontend Guard

**Files:**
- Create: `scripts/verify_vue_dashboard_metrics_field_graph_editor.js`
- Read: `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- Read: `v2-web/src/views/ProjectsView.vue`

- [ ] **Step 1: Write the failing verifier**

Create a verifier that asserts:
- `FieldGraphDesigner` defines `DashboardMetricForm`, accepts `dashboardMetrics`, and emits `update-dashboard-metrics`.
- `FieldGraphDesigner` contains `dashboardMetricPresetCards`, `selectedDashboardMetricKeys`, `toggleDashboardMetric`, and `dashboard-metric-editor-card`.
- The visible editor has the label `驾驶舱指标口径`.
- `ProjectsView` passes `dashboard-metrics` into both create and edit graph designers.
- `ProjectsView` handles `update-dashboard-metrics` for both create and edit forms.

- [ ] **Step 2: Run verifier to confirm RED**

Run:

```powershell
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' scripts\verify_vue_dashboard_metrics_field_graph_editor.js
```

Expected before implementation: failure because the visual field graph does not expose a dashboard metric editor.

### Task 2: Field Graph Editor

**Files:**
- Modify: `v2-web/src/components/project-fields/FieldGraphDesigner.vue`

- [ ] **Step 1: Add metric form type and prop**

Add:

```ts
type DashboardMetricForm = {
  key: string
  label: string
  source?: string
  scope?: string
}
```

Add `dashboardMetrics?: DashboardMetricForm[]` to props and emit:

```ts
(event: 'update-dashboard-metrics', payload: DashboardMetricForm[]): void
```

- [ ] **Step 2: Add recommended metric cards**

Add `dashboardMetricPresetCards` with five operator-facing groups:
- project_progress: `total_work_orders`, `completed_work_orders`
- delivery_capability: `completed_work_orders`, `average_completion_duration`
- field_collection: `collected_work_orders`
- review_quality: `exception_work_orders`
- kpi_efficiency: `average_online_duration`, `average_completion_duration`

- [ ] **Step 3: Add selection helpers**

Add `selectedDashboardMetricKeys`, `metricSelectionCount`, `metricCardSelected`, and `toggleDashboardMetric(card)`. Toggling a card should add missing metrics and remove all metrics from that card when all of its metrics are already selected. Preserve any custom metrics that are not part of the card being toggled.

- [ ] **Step 4: Render compact visual editor**

Render a `field-dashboard-metric-editor` panel after the replacement hierarchy mode cards. Each `dashboard-metric-editor-card` should show title, helper, selected count, and metric labels. Disable toggling when `editable` is false.

- [ ] **Step 5: Style responsive cards**

Add grid styling with 5 cards on wide screens, 2-3 on medium screens, and 1 on narrow screens using existing media query areas.

### Task 3: Projects View Wiring

**Files:**
- Modify: `v2-web/src/views/ProjectsView.vue`

- [ ] **Step 1: Add update handlers**

Add:

```ts
function handleCreateDashboardMetricsUpdate(metrics: ProjectDashboardMetric[]) {
  createForm.dashboardMetrics = metrics.map((metric) => ({ ...metric }))
}

function handleSchemaDashboardMetricsUpdate(metrics: ProjectDashboardMetric[]) {
  schemaForm.dashboardMetrics = metrics.map((metric) => ({ ...metric }))
}
```

- [ ] **Step 2: Wire FieldGraphDesigner props/events**

For create graph:

```vue
:dashboard-metrics="createForm.dashboardMetrics"
@update-dashboard-metrics="handleCreateDashboardMetricsUpdate"
```

For schema graph:

```vue
:dashboard-metrics="schemaForm.dashboardMetrics"
@update-dashboard-metrics="handleSchemaDashboardMetricsUpdate"
```

### Task 4: Verification And Handoff

**Files:**
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Create: `docs/reports/pm-platform-dashboard-metrics-field-graph-editor-2026-07-03.md`

- [ ] **Step 1: Run new verifier**

Run:

```powershell
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' scripts\verify_vue_dashboard_metrics_field_graph_editor.js
```

Expected: `OK: Vue dashboard metrics field graph editor is wired.`

- [ ] **Step 2: Run existing contract guards**

Run:

```powershell
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' scripts\verify_vue_dashboard_metrics_contract.js
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\verify_platform_dashboard_metrics_contract.py
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' scripts\verify_vue_field_graph_smart_drop.js
```

- [ ] **Step 3: Build frontend**

Run:

```powershell
$env:PATH='C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin;C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin;' + $env:PATH
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\pnpm.cmd' --dir v2-web build
```

- [ ] **Step 4: Browser smoke**

Open `/platform-projects`, open field configuration, and verify `驾驶舱指标口径` is visible in the field graph screen without current-load console errors.

- [ ] **Step 5: Document risk and rollback**

Report baseline, modified files, feature summary, test results, no production data mutation, migration note, and rollback steps.
