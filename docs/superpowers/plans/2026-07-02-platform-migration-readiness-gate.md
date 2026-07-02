# Platform Migration Readiness Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only migration readiness gate for the future PostgreSQL project configuration migration, so operators can see the required backup, dry-run, verification, rollback, and approval conditions before any high-risk migration is allowed.

**Architecture:** Reuse the existing persistence status, PostgreSQL design, and project config persistence contract preview. Add a backend service and route that summarizes migration gate items without connecting to PostgreSQL or writing files. Extend the existing frontend `持久化准备` panel to show the gate checklist.

**Tech Stack:** FastAPI, Python pytest, Vue 3 + TypeScript + Element Plus, Node frontend guard, Vite build, browser smoke.

---

## File Structure

- Create: `v2-api/app/services/platform/migration_readiness.py`
  - Builds the read-only migration gate.
- Modify: `v2-api/app/api/routes/projects.py`
  - Adds `GET /projects/persistence/migration-readiness`.
- Create: `v2-api/tests/test_platform_migration_readiness.py`
  - API and service-level checks for gate shape and safety.
- Create: `scripts/verify_platform_migration_readiness.py`
  - Standalone guard for CI/PR handoff.
- Modify: `v2-web/src/api/types.ts`
  - Adds `PlatformMigrationReadiness` and `PlatformMigrationGateItem`.
- Modify: `v2-web/src/api/services.ts`
  - Adds backend mapping and `fetchPlatformMigrationReadiness`.
- Modify: `v2-web/src/views/ProjectsView.vue`
  - Shows migration gate items in the existing `持久化准备` panel.
- Modify: `scripts/verify_vue_project_persistence_readiness.js`
  - Requires the new API and UI tokens.
- Create: `docs/reports/pm-platform-migration-readiness-gate-2026-07-02.md`
  - Records verification, migration note, rollback note, and risks.
- Update: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`, PR/patch reports, and `scripts/verify_pm_platform_handoff_package.py`.

## Task 1: Backend RED

- [x] Create `v2-api/tests/test_platform_migration_readiness.py`.
- [x] The test calls `GET /projects/persistence/migration-readiness` and expects:
  - `ready_for_migration` is false,
  - `requires_user_approval` is true,
  - `creates_migration` is false,
  - gate items include `backup`, `dry_run`, `verification`, `rollback`, `approval`, and `cutover_flag`,
  - safety includes `no_database_connection`, `no_postgres_schema_change`, and `no_production_data_edit`,
  - target tables include `platform_project_configs` and `platform_project_config_events`.
- [x] Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_migration_readiness.py -q
```

Expected RED observed: route returned `404 Not Found`.

## Task 2: Backend GREEN

- [x] Create `v2-api/app/services/platform/migration_readiness.py`.
- [x] Add `build_platform_migration_readiness()` that returns:
  - `readiness_version`,
  - `scope`,
  - `ready_for_migration`,
  - `requires_user_approval`,
  - `creates_migration`,
  - `target_tables`,
  - `gate_items`,
  - `migration_plan`,
  - `rollback_plan`,
  - `safety`.
- [x] Add the route in `projects.py`.
- [x] Create `scripts/verify_platform_migration_readiness.py`.
- [x] Run pytest and guard until green.

## Task 3: Frontend RED And GREEN

- [x] Extend `scripts/verify_vue_project_persistence_readiness.js` to require:

```text
PlatformMigrationReadiness
PlatformMigrationGateItem
fetchPlatformMigrationReadiness
projectMigrationReadiness
migrationGateStatusText
迁移门禁
备份
dry-run
回滚
审批
```

- [x] Run the guard and observe RED.
- [x] Add frontend types, service mapping, fetch helper, page state, panel rendering, and copy.
- [x] Run the guard until green.

## Task 4: Verification And Handoff

- [x] Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_migration_readiness.py -q
.\.venv\Scripts\python.exe scripts\verify_platform_migration_readiness.py
node scripts\verify_vue_project_persistence_readiness.js
pnpm --dir v2-web build
```

- [x] Browser smoke:
  - Open `/platform-projects`.
  - Open `字段配置`.
  - Confirm `持久化准备` and `迁移门禁` are visible.
  - Confirm backup, dry-run, rollback, and approval gate items are visible.
  - Confirm refresh keeps the gate populated.

- [ ] Run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_pm_platform_handoff_package.py
.\.venv\Scripts\python.exe scripts\verify_pm_platform_team_operating_model.py
.\.venv\Scripts\python.exe scripts\verify_production_baseline.py
git diff --check
git status --short -- .env data v2-api/data v2-api/app/static/uploads uploads
```

## Self-Review

- This package is read-only and explicitly keeps `ready_for_migration` false.
- No Alembic file, PostgreSQL connection, production data edit, version bump, tag, or deployment is included.
- It makes the future migration approval gate visible and testable before any high-risk action.

## Evidence

- RED: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_migration_readiness.py -q` failed with `404 Not Found`.
- GREEN: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_migration_readiness.py -q` returned `1 passed, 1 warning`.
- Backend guard: `.\.venv\Scripts\python.exe scripts\verify_platform_migration_readiness.py` returned `[OK] platform migration readiness gate is consistent`.
- Frontend RED: `node scripts\verify_vue_project_persistence_readiness.js` failed with `types.ts missing persistence readiness token: PlatformMigrationGateItem`.
- Frontend GREEN: `node scripts\verify_vue_project_persistence_readiness.js` returned `[OK] Vue project persistence readiness is wired.`
- Build: `pnpm --dir v2-web build` exited 0 with `1894 modules transformed`, built in `8.85s`.
- Browser smoke: `/platform-projects` -> first row `字段配置` showed `持久化准备` and `迁移门禁`, including backup, dry-run, rollback, approval and `待审批` gates; refresh kept the gate populated.
