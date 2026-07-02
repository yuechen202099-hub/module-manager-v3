# Project Persistence Readiness Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show read-only persistence readiness inside the project field configuration dialog, so operators can see where project config is stored now and what must be approved before PostgreSQL migration.

**Architecture:** Reuse the existing read-only backend endpoints: `GET /projects/persistence/status` and `GET /projects/{project_id}/persistence/contract`. Add frontend types, mapping functions, fetch helpers, and a compact panel inside `ProjectsView.vue`. No migration, database write, production version bump, tag, or deployment is included.

**Tech Stack:** Vue 3 + TypeScript + Element Plus, existing FastAPI persistence endpoints, Node guard script, Vite build, browser smoke.

---

## File Structure

- Create: `scripts/verify_vue_project_persistence_readiness.js`
  - Guard frontend persistence readiness wiring.
- Modify: `v2-web/src/api/types.ts`
  - Add `PlatformPersistenceStatus`, `ProjectConfigPersistenceContract`, and related nested types.
- Modify: `v2-web/src/api/services.ts`
  - Add backend types, mapping helpers, `fetchPlatformPersistenceStatus`, and `fetchProjectConfigPersistenceContract`.
- Modify: `v2-web/src/views/ProjectsView.vue`
  - Load persistence status/contract when opening field configuration.
  - Render a read-only `持久化准备` panel with status, target backend, round-trip, safety, and refresh.
- Create: `docs/reports/pm-platform-persistence-readiness-frontend-2026-07-02.md`
  - Record scope, verification, migration/rollback, and risk.
- Update: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`, PR/patch handoff docs, and handoff guard.

## Task 1: Frontend Guard Red

- [x] Create `scripts/verify_vue_project_persistence_readiness.js`.
- [x] Require these frontend tokens:

```text
PlatformPersistenceStatus
ProjectConfigPersistenceContract
fetchPlatformPersistenceStatus
fetchProjectConfigPersistenceContract
projectPersistenceStatus
projectPersistenceContractsById
loadProjectPersistenceReadiness
schemaProjectPersistenceContract
persistence-readiness-panel
持久化准备
当前存储
PostgreSQL
safety
```

- [x] Run:

```powershell
node scripts\verify_vue_project_persistence_readiness.js
```

Expected RED observed: `types.ts missing persistence readiness token: PlatformPersistenceStatus`.

## Task 2: Frontend Types And API

- [x] Add persistence status and contract types to `types.ts`.
- [x] Add backend response types and mapping helpers to `services.ts`.
- [x] Add:

```ts
export async function fetchPlatformPersistenceStatus(): Promise<PlatformPersistenceStatus>
export async function fetchProjectConfigPersistenceContract(projectId: string): Promise<ProjectConfigPersistenceContract>
```

- [x] Run the guard until type/API tokens are present.

## Task 3: Project Dialog Panel

- [x] Add persistence refs and computed values in `ProjectsView.vue`.
- [x] When `openSchemaDialog(project)` runs, load readiness, template preview, and persistence readiness together.
- [x] Render a read-only panel inside the field configuration dialog:
  - status backend and database state,
  - source backend and target backend,
  - target tables,
  - round-trip status,
  - safety gates,
  - refresh button.
- [x] Keep copy non-technical and warning-oriented.

## Task 4: Verify And Handoff

- [x] Run:

```powershell
node scripts\verify_vue_project_persistence_readiness.js
pnpm --dir v2-web build
```

- [x] Browser smoke:
  - Open `/platform-projects`.
  - Open `字段配置`.
  - Confirm `持久化准备`, `当前存储`, `PostgreSQL`, and safety tags are visible.
  - Click refresh and confirm the panel remains visible.

- [x] Run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_pm_platform_handoff_package.py
.\.venv\Scripts\python.exe scripts\verify_pm_platform_team_operating_model.py
.\.venv\Scripts\python.exe scripts\verify_production_baseline.py
git diff --check
git status --short -- .env data v2-api/data v2-api/app/static/uploads uploads
```

## Self-Review

- Scope is read-only frontend consumption of existing backend endpoints.
- No database migration or write-path behavior is added.
- The panel should make persistence risk visible to operators without adding another row-level action button.

## Evidence

- RED: `node scripts\verify_vue_project_persistence_readiness.js` failed with `types.ts missing persistence readiness token: PlatformPersistenceStatus`.
- GREEN: `node scripts\verify_vue_project_persistence_readiness.js` returned `[OK] Vue project persistence readiness is wired.`
- Build: `pnpm --dir v2-web build` exited 0 with `1894 modules transformed`, built in `8.57s`.
- Browser smoke: `/platform-projects` first row `字段配置` opened a dialog showing `持久化准备`, `当前存储`, `PostgreSQL`, `迁移审批`, `目标表`, and `安全门槛`; `刷新准备状态` kept the panel visible.
- Report: `docs/reports/pm-platform-persistence-readiness-frontend-2026-07-02.md`.
