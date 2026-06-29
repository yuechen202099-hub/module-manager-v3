# Frontend Project Module Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change the Vue project page data path so project module sections are read from the new `/projects/{id}/...` endpoints instead of relying on one large overview payload.

**Architecture:** Keep `workspace.loadProjects()` and `fetchProjects()` as the public frontend call path. Internally, `fetchProjects()` first reads `/projects` for identity/top-level rows, then fetches progress, delivery, field, review, risks, and tasks modules per project and merges them into the existing `Project` type. Add a type-only contract file so the module-loading service shape is checked by `vue-tsc`.

**Tech Stack:** Vue 3, TypeScript, Pinia, existing API envelope helper, Vite build.

---

## File Structure

- Create `v2-web/src/api/projectModuleContracts.ts`: compile-time contract for project module service functions.
- Modify `v2-web/src/api/services.ts`: add backend module response types, section mappers, `fetchProjectModuleSections()`, and module-backed `fetchProjects()`.
- Modify `v2-web/src/stores/workspace.ts`: keep `loadProjects()` as the stable page-facing action; no behavior change required unless loading flags need tightening.
- Build output may update `v2-api/app/static/vue` after `pnpm build`.

## Task 1: Add Compile-Time Contract

**Files:**
- Create: `v2-web/src/api/projectModuleContracts.ts`

- [ ] **Step 1: Write failing contract**

Create:

```ts
import { fetchProjectModuleSections, fetchProjectsWithModules } from './services'
import type { Project } from './types'

type ProjectModuleSections = Awaited<ReturnType<typeof fetchProjectModuleSections>>

const projectListContract: () => Promise<Project[]> = fetchProjectsWithModules

function assertProjectModuleShape(sections: ProjectModuleSections) {
  sections.progress.stage
  sections.delivery.completedItems
  sections.field.photoRowsLinked
  sections.review.pendingGroups
  sections.risks.deliveryBlockers
  sections.tasks.archived
}

void projectListContract
void assertProjectModuleShape
```

- [ ] **Step 2: Run frontend build and confirm failure**

Run:

```powershell
pnpm build
```

Expected: `vue-tsc` fails because `fetchProjectModuleSections` and `fetchProjectsWithModules` do not exist.

## Task 2: Implement Module Loading Services

**Files:**
- Modify: `v2-web/src/api/services.ts`

- [ ] **Step 1: Add section response types**

Define backend section types for progress, delivery, field, review, risks, and tasks.

- [ ] **Step 2: Extract section mappers**

Add `mapProjectProgress`, `mapProjectDelivery`, `mapProjectField`, `mapProjectReview`, `mapProjectRisks`, and `mapProjectTasks`.

- [ ] **Step 3: Add `fetchProjectModuleSections(projectId)`**

Fetch the six endpoints in parallel:

```ts
api<BackendProjectProgress>(`/projects/${id}/progress`)
api<BackendProjectDelivery>(`/projects/${id}/delivery`)
api<BackendProjectField>(`/projects/${id}/field`)
api<BackendProjectReview>(`/projects/${id}/review`)
api<BackendProjectRisks>(`/projects/${id}/risks`)
api<BackendProjectTasks>(`/projects/${id}/tasks`)
```

- [ ] **Step 4: Add `fetchProjectsWithModules()` and update `fetchProjects()`**

`fetchProjectsWithModules()` calls `/projects`, maps base rows, loads module sections for each project, and merges module results over the base row. `fetchProjects()` returns `fetchProjectsWithModules()` so existing page/store calls stay stable.

- [ ] **Step 5: Run frontend build**

Run:

```powershell
pnpm build
```

Expected: build passes.

## Task 3: Verification and Commit

**Files:**
- Verify all changed files and generated assets.

- [ ] **Step 1: Run backend project API tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py -q
```

Expected: pass.

- [ ] **Step 2: Run release gates**

Run:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_release_sop.py
.\.venv\Scripts\python.exe .\scripts\verify_vue_migration_gate.py --strict-native
```

Expected: both pass.

- [ ] **Step 3: Inspect Git status**

Run:

```powershell
git status -sb
git diff --stat
```

Expected: plan, frontend API files, generated Vue static assets, and no environment/data/upload files.

- [ ] **Step 4: Commit**

Run:

```powershell
git add docs/superpowers/plans/2026-06-29-frontend-project-module-loading.md v2-web/src/api/services.ts v2-web/src/api/projectModuleContracts.ts v2-api/app/static/vue
git commit -m "feat: load project modules in frontend"
```

Expected: commit created on `feat/operations-platform-phase-one`.

## Self-Review

- Spec coverage: front-end project data path now targets the module endpoints added in the previous step.
- Placeholder scan: no deferred behavior or TBD steps.
- Type consistency: contract uses existing `Project` type and the planned module section property names.
