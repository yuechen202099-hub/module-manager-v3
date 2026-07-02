# Platform Persistence Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose a read-only backend persistence status for PM platform project configuration, workflow definitions, import batches, work-order tasks, platform work orders, and construction photo storage.

**Architecture:** Reuse the existing local JSON/file persistence paths already used by platform catalog and template services. Add a small service module that builds a safe status snapshot, then expose it through `GET /projects/persistence/status` without changing write behavior or adding migrations.

**Tech Stack:** FastAPI, Python 3.12, pytest, existing platform catalog/template persistence paths.

---

## Context

- Production baseline: `production/V3/3.0.71`.
- Feature branch: `pm-platform/project-drafts`.
- Lead role: Backend Field Schema Agent + Backend Flow Engine Agent + Ops And Release Agent.
- User need: project field schemas and workflows must become durable and understandable as the platform grows beyond a single project; operators also need to know what database/backend is currently connected.
- Data safety: read-only status only; no database migration, no production data edit, no version bump, no tag, no deployment.

## Files

- Create: `v2-api/app/services/platform/persistence.py`
- Create: `v2-api/tests/test_platform_persistence_status.py`
- Create: `scripts/verify_platform_persistence_status.py`
- Create: `docs/reports/pm-platform-persistence-status-2026-07-02.md`
- Modify: `v2-api/app/api/routes/projects.py`
- Update: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Update: `docs/superpowers/plans/2026-07-02-platform-persistence-status.md`

## Tasks

### Task 1: Write failing tests

- [x] **Step 1: Create `v2-api/tests/test_platform_persistence_status.py`**

Test requirements:

```text
GET /projects/persistence/status returns 200.
The response shows project drafts store, import batches store, work-order tasks store, platform work orders store, and construction photo storage.
The project draft store path respects configure_project_draft_store_path().
The response states field schemas and workflow definitions are persisted in the project draft store.
The database URL is redacted and must not include the raw password.
The status is read-only and does not create files.
```

- [x] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api/tests/test_platform_persistence_status.py -q
```

Expected:

```text
404 Not Found or ModuleNotFoundError before implementation.
```

### Task 2: Add the persistence status service

- [x] **Step 1: Create `v2-api/app/services/platform/persistence.py`**

Expected implementation:

```text
build_platform_persistence_status() returns a plain dict with:
- state_backend
- database.configured
- database.url_redacted
- stores[]
- guarantees[]
- safety[]
```

- [x] **Step 2: Keep the module read-only**

Expected behavior:

```text
It may inspect paths with exists() and parent.exists().
It must not mkdir, write files, connect to PostgreSQL, touch OSS, or read secret files.
```

### Task 3: Expose the status route and guard script

- [x] **Step 1: Add route in `v2-api/app/api/routes/projects.py`**

Route:

```text
GET /projects/persistence/status
```

- [x] **Step 2: Create `scripts/verify_platform_persistence_status.py`**

Expected output:

```text
[OK] platform persistence status is consistent
```

### Task 4: Verify and document

- [x] **Step 1: Run focused checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api/tests/test_platform_persistence_status.py -q
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
GET /projects/persistence/status returned 404.
```

- Focused pytest:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api/tests/test_platform_persistence_status.py -q
```

Observed:

```text
1 passed, 1 warning
```

- Guard script:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_platform_persistence_status.py
```

Observed:

```text
[OK] platform persistence status is consistent
```

- Existing persistence regression checks:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api/tests/test_platform_overview.py::test_project_draft_work_item_schema_can_be_updated_and_persisted -q
.\.venv\Scripts\python.exe -m pytest v2-api/tests/test_platform_overview.py::test_project_draft_registry_recovers_projects_after_memory_reset -q
```

Observed:

```text
1 passed, 1 warning
1 passed, 1 warning
```

- Handoff report: `docs/reports/pm-platform-persistence-status-2026-07-02.md`.
- Combined contract and persistence check:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api/tests/test_platform_persistence_status.py v2-api/tests/test_platform_contracts.py -q
```

Observed:

```text
2 passed, 1 warning
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

- No database migration.
- No write-path behavior change.
- No production data edit.
- This status makes current local JSON/file persistence explicit; PostgreSQL migration remains a future package that requires a separate migration and rollback plan.

## Rollback Notes

- Remove `v2-api/app/services/platform/persistence.py`.
- Remove `v2-api/tests/test_platform_persistence_status.py`.
- Remove `scripts/verify_platform_persistence_status.py`.
- Remove the `/projects/persistence/status` route.
- Revert the team development document entry if this package is rolled back.
