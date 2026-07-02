# Project Readiness Panel Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the backend project readiness result inside the project field configuration dialog, so a non-technical operator can see whether a project is ready for import, site collection, review, and delivery.

**Architecture:** The backend already exposes `GET /projects/{project_id}/readiness`. This package adds a typed frontend API client, stores readiness by project id in `ProjectsView.vue`, and renders a compact server-backed readiness panel next to the existing local configuration preview.

**Tech Stack:** Vue 3, TypeScript, Element Plus, existing platform project API client, focused Node guard script, Vite build, browser smoke test.

---

### Task 1: Frontend Readiness Guard

**Files:**
- Create: `scripts/verify_vue_project_readiness_panel.js`
- Read: `v2-web/src/api/types.ts`
- Read: `v2-web/src/api/services.ts`
- Read: `v2-web/src/views/ProjectsView.vue`

- [ ] **Step 1: Write the failing guard**

Create a Node script that requires these implementation signals:

```javascript
const requiredTypeTokens = [
  'ProjectReadinessCheckStatus',
  'ProjectReadinessCheck',
  'ProjectReadinessSummary',
  'ProjectReadiness',
]

const requiredServiceTokens = [
  'ProjectReadiness,',
  'type BackendProjectReadiness',
  'type BackendProjectReadinessCheck',
  'function mapProjectReadiness',
  'export async function fetchProjectReadiness',
  '/readiness`',
]

const requiredViewTokens = [
  'fetchProjectReadiness',
  'ProjectReadiness',
  'projectReadinessById',
  'loadingReadinessProjectId',
  'schemaProjectReadiness',
  'loadProjectReadiness',
  'readiness-server-panel',
  'readiness-check-list',
  '上线检查',
  'readinessStatusType',
  'readinessSummaryText',
]
```

- [ ] **Step 2: Run guard to verify RED**

Run:

```powershell
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' scripts\verify_vue_project_readiness_panel.js
```

Expected: FAIL, because the readiness API is not yet wired into the frontend.

### Task 2: API Types And Service

**Files:**
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`

- [ ] **Step 1: Add frontend readiness types**

Add:

```ts
export type ProjectReadinessCheckStatus = 'passed' | 'failed'

export type ProjectReadinessCheck = {
  id: string
  group: string
  label: string
  status: ProjectReadinessCheckStatus
  severity: string
  evidence: Record<string, unknown>
  action: string
}

export type ProjectReadinessSummary = {
  total: number
  passed: number
  failed: number
  blockers: number
}

export type ProjectReadiness = {
  readinessVersion: number
  projectId: string
  ready: boolean
  summary: ProjectReadinessSummary
  checks: ProjectReadinessCheck[]
  nextActions: string[]
  safety: string[]
}
```

- [ ] **Step 2: Add backend mapping**

Import `ProjectReadiness`, add backend readiness types, map snake_case to camelCase, and expose:

```ts
export async function fetchProjectReadiness(projectId: string): Promise<ProjectReadiness> {
  const data = await api<BackendProjectReadiness>(`/projects/${encodeURIComponent(projectId)}/readiness`)
  return mapProjectReadiness(data)
}
```

- [ ] **Step 3: Run guard**

Run the guard again. Expected: still FAIL until the view renders the panel.

### Task 3: Field Configuration Readiness Panel

**Files:**
- Modify: `v2-web/src/views/ProjectsView.vue`

- [ ] **Step 1: Import and state**

Import `fetchProjectReadiness` and `ProjectReadiness`, then add:

```ts
const projectReadinessById = ref<Record<string, ProjectReadiness>>({})
const loadingReadinessProjectId = ref('')
const schemaProjectReadiness = computed(() => schemaProject.value ? projectReadinessById.value[schemaProject.value.id] : null)
```

- [ ] **Step 2: Load readiness when opening or saving field config**

Call `void loadProjectReadiness(project)` inside `openSchemaDialog`. After a successful schema save and project reload, refresh the readiness result for the same project id.

- [ ] **Step 3: Render server-backed readiness**

Inside the field configuration dialog, add a panel with class `readiness-server-panel`, a refresh button, a summary tag, a `readiness-check-list`, and next actions. Use plain operator language:

```vue
<strong>上线检查</strong>
<span>按已保存配置检查字段、证据、KPI 和流程是否可接入。</span>
```

- [ ] **Step 4: Add compact styles**

Add styles for `.readiness-server-panel`, `.readiness-server-header`, `.readiness-server-summary`, `.readiness-check-list`, `.readiness-check-list article`, and `.readiness-next-actions`. Keep the panel compact and responsive.

- [ ] **Step 5: Run guard**

Run:

```powershell
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' scripts\verify_vue_project_readiness_panel.js
```

Expected: PASS.

### Task 4: Verification And Handoff Notes

**Files:**
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Modify: `docs/reports/pm-platform-pr-patch-handoff-2026-07-02.md`
- Modify: `docs/reports/pm-platform-pr-body-2026-07-02.md`
- Modify: `scripts/verify_pm_platform_handoff_package.py`
- Create: `docs/reports/pm-platform-readiness-panel-frontend-2026-07-02.md`

- [ ] **Step 1: Run focused frontend checks**

Run:

```powershell
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' scripts\verify_vue_project_readiness_panel.js
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' scripts\verify_vue_project_field_graph_template_actions.js
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' scripts\verify_vue_project_workflow_module_toggles.js
```

Expected: all PASS.

- [ ] **Step 2: Run build and backend readiness guard**

Run:

```powershell
$env:PATH = 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin;C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin;' + $env:PATH
& 'C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\pnpm.cmd' --dir v2-web build
.\.venv\Scripts\python.exe scripts\verify_platform_project_readiness.py
```

Expected: build succeeds and backend readiness guard passes.

- [ ] **Step 3: Browser smoke**

Start the local platform server if needed, open `/platform-projects`, open the existing `字段配置` action, and confirm the dialog shows `上线检查` and readiness checks without adding a new row-level operation button.

- [ ] **Step 4: Update handoff docs**

Record changed files, verification commands, risks, migration notes, and rollback notes. Migration note: this frontend package adds no database migration and performs read-only readiness checks. Rollback note: revert the readiness panel API client, view changes, guard script, and docs.
