# Platform Postgres Persistence Design Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a machine-checkable PostgreSQL persistence design for PM platform field schemas and workflow definitions without running a migration.

**Architecture:** Add a read-only design module that describes the first database-backed slice: platform project configuration rows plus config change events. Guard it with pytest and a verification script so the real Alembic migration can be written later from a reviewed baseline.

**Tech Stack:** Python 3.12, pytest, PostgreSQL design conventions, existing platform contract and persistence status modules.

---

## Context

- Production baseline: `production/V3/3.0.71`.
- Feature branch: `pm-platform/project-drafts`.
- Lead role: Backend Field Schema Agent + Backend Flow Engine Agent + Ops And Release Agent.
- User need: field schemas and workflow definitions must eventually move from local JSON into durable multi-project persistence.
- Safety rule: this package does not create an Alembic migration and does not touch production PostgreSQL.

## Files

- Create: `v2-api/app/services/platform/postgres_design.py`
- Create: `v2-api/tests/test_platform_postgres_design.py`
- Create: `scripts/verify_platform_postgres_design.py`
- Create: `docs/reports/pm-platform-postgres-persistence-design-2026-07-02.md`
- Update: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Update: `docs/superpowers/plans/2026-07-02-platform-postgres-persistence-design.md`

## Tasks

### Task 1: Write the failing design test

- [x] **Step 1: Create `v2-api/tests/test_platform_postgres_design.py`**

Test requirements:

```text
build_platform_postgres_persistence_design() returns a plain dict.
The first slice is named project_config.
The design has no direct migration execution flag.
It defines platform_project_configs and platform_project_config_events.
Each table has a primary key.
Foreign key columns have matching indexes.
team_id, project_key, status, and updated_at are indexed for project configs.
field_schema and workflow_definition use jsonb.
Migration notes include backup, dry-run, backfill, verify, and cutover.
Rollback notes include disabling PostgreSQL reads, keeping JSON fallback, and dropping new tables only after backup.
```

- [x] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api/tests/test_platform_postgres_design.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'app.services.platform.postgres_design'
```

### Task 2: Add the read-only design module

- [x] **Step 1: Create `v2-api/app/services/platform/postgres_design.py`**

Expected design shape:

```text
contract_version
scope
creates_migration = false
tables[]
migration_plan[]
rollback_plan[]
safety[]
```

- [x] **Step 2: Follow current schema conventions**

Expected constraints:

```text
Use team_id and project_key for tenant/project lookup.
Use timestamptz for timestamps.
Use jsonb for field schema and workflow definition payloads.
Index foreign keys and common filter columns.
Do not include secrets, production paths, or SQL execution.
```

### Task 3: Add verification script and report

- [x] **Step 1: Create `scripts/verify_platform_postgres_design.py`**

Expected:

```text
[OK] platform postgres persistence design is consistent
```

- [x] **Step 2: Create report**

Report should include:

```text
table sketch, migration notes, rollback notes, and what still needs explicit user approval.
```

### Task 4: Verify and document

- [x] **Step 1: Run checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api/tests/test_platform_postgres_design.py -q
.\.venv\Scripts\python.exe .\scripts\verify_platform_postgres_design.py
.\.venv\Scripts\python.exe .\scripts\verify_platform_persistence_status.py
.\.venv\Scripts\python.exe .\scripts\verify_production_baseline.py
```

- [x] **Step 2: Sensitive path check**

Run:

```powershell
git status --short -- .env data v2-api/data v2-api/app/static/uploads uploads
```

Expected: no entries.

## Verification Evidence

- RED before implementation:

```text
ModuleNotFoundError: No module named 'app.services.platform.postgres_design'
```

- Focused pytest:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api/tests/test_platform_postgres_design.py -q
```

Observed:

```text
1 passed in 0.02s
```

- Design guard:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_platform_postgres_design.py
```

Observed:

```text
[OK] platform postgres persistence design is consistent
```

- Handoff report: `docs/reports/pm-platform-postgres-persistence-design-2026-07-02.md`.
- Combined focused tests:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api/tests/test_platform_postgres_design.py v2-api/tests/test_platform_persistence_status.py v2-api/tests/test_platform_contracts.py -q
```

Observed:

```text
3 passed, 1 warning
```

- Persistence status guard:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_platform_persistence_status.py
```

Observed:

```text
[OK] platform persistence status is consistent
```

- Backend contract guard:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_platform_backend_contract_snapshot.py
```

Observed:

```text
[OK] platform backend contract snapshot is consistent
```

- Production baseline check:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_production_baseline.py
```

Observed:

```text
[OK] production ref: origin/production/V3/3.0.71 @ 862659e0e659
[OK] baseline tag: v3.0.71 @ 825f88092701
[OK] current ref contains production baseline: HEAD @ 8035f3247b5f
```

- Sensitive path check:

```powershell
git status --short -- .env data v2-api/data v2-api/app/static/uploads uploads
```

Observed: no entries.

## Migration Notes

- No database migration in this package.
- The design requires explicit user approval before an Alembic file is created or run.
- The future migration must include backup, dry-run, backfill verification, cutover, and rollback instructions.

## Rollback Notes

- Remove `v2-api/app/services/platform/postgres_design.py`.
- Remove `v2-api/tests/test_platform_postgres_design.py`.
- Remove `scripts/verify_platform_postgres_design.py`.
- Remove the design report and revert team memory updates.
