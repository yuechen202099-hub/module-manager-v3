# Platform Project Config Persistence Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only API contract preview that shows how a platform project's field schema and workflow would map into the future PostgreSQL project configuration tables, without creating a migration or touching a database.

**Architecture:** Keep the current local JSON project store as the source of truth. Add a small platform service that projects a `ProjectDefinition` into future `platform_project_configs` row shape, verifies a restore/round-trip preview, and exposes it through a read-only project API route.

**Tech Stack:** FastAPI, existing platform catalog services, Python pytest, Python verification script.

---

## File Structure

- Create: `v2-api/app/services/platform/config_persistence_contract.py`
  - Builds a future database-row preview for project config.
  - Reconstructs a normalized project definition from the preview record.
  - Reports round-trip preservation and migration safety gates.
- Modify: `v2-api/app/api/routes/projects.py`
  - Adds `GET /projects/{project_id}/persistence/contract`.
- Create: `v2-api/tests/test_platform_project_config_persistence_contract.py`
  - API-level test that creates a sample project, updates workflow, reads the contract preview, and checks field/workflow preservation.
- Create: `scripts/verify_platform_project_config_persistence_contract.py`
  - Standalone guard for the same read-only contract.
- Create: `docs/reports/pm-platform-config-persistence-contract-2026-07-02.md`
  - Records feature scope, migration/rollback notes, verification, and safety.
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
  - Records this completed package and the next gated step.

### Task 1: Write The Failing API Test

**Files:**
- Create: `v2-api/tests/test_platform_project_config_persistence_contract.py`

- [ ] **Step 1: Add a test for the missing route**

The test creates a local draft project for "更换终端", configures terminal-related fields, updates workflow, then calls:

```text
GET /projects/{project_id}/persistence/contract
```

Expected before implementation: `404` or import failure because the route/service does not exist.

- [ ] **Step 2: Run the focused test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_config_persistence_contract.py -q
```

Expected: FAIL before route implementation.

### Task 2: Implement The Read-Only Contract Service

**Files:**
- Create: `v2-api/app/services/platform/config_persistence_contract.py`

- [ ] **Step 1: Build a config record preview**

Implement a function that maps an existing project definition into this shape:

```python
{
    "team_id": "local",
    "project_key": definition.id,
    "name": definition.name,
    "status": definition.status,
    "adapter": definition.adapter,
    "module_ids": list(definition.module_ids),
    "description": definition.description,
    "field_schema": normalized_work_item_schema,
    "workflow_definition": normalized_workflow,
    "created_at": definition.created_at,
    "updated_at": definition.updated_at,
    "created_by": "",
    "updated_by": normalized_workflow["updated_by"],
}
```

- [ ] **Step 2: Build a round-trip preview**

Reconstruct a `ProjectDefinition` from the record and compare:

- project key,
- name,
- status,
- adapter,
- module IDs,
- primary field key,
- aggregate field key,
- workflow node IDs.

- [ ] **Step 3: Include safety and migration gates**

The contract payload must include:

- `target_tables`,
- `config_record`,
- `roundtrip`,
- `migration_gate`,
- `safety`.

The safety list must contain `read_only_no_write`, `no_database_connection`, `no_postgres_schema_change`, and `json_source_only`.

### Task 3: Expose The API Route

**Files:**
- Modify: `v2-api/app/api/routes/projects.py`

- [ ] **Step 1: Import the service**

Import `build_project_config_persistence_contract`.

- [ ] **Step 2: Add the route**

Add:

```python
@router.get("/{project_id}/persistence/contract")
def get_project_config_persistence_contract(project_id: str, request: Request):
    ...
```

It returns `ok(request, payload)` and maps `ProjectNotFound` to 404 and `ProjectConfigurationError` to 500.

- [ ] **Step 3: Run the focused test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_config_persistence_contract.py -q
```

Expected: PASS.

### Task 4: Add A Standalone Guard

**Files:**
- Create: `scripts/verify_platform_project_config_persistence_contract.py`

- [ ] **Step 1: Add the guard**

The guard should create a temp local draft project store, create a sample "更换终端" project, call the API route, assert the record and safety fields, then clean up the temp store.

- [ ] **Step 2: Run the guard**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_platform_project_config_persistence_contract.py
```

Expected:

```text
[OK] platform project config persistence contract is consistent
```

### Task 5: Document And Verify

**Files:**
- Create: `docs/reports/pm-platform-config-persistence-contract-2026-07-02.md`
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

- [ ] **Step 1: Write the report**

Include:

- feature scope,
- API route,
- safety,
- verification commands,
- migration note,
- rollback note.

- [ ] **Step 2: Update team memory**

Record that persistence contract preview is complete and the next risky step remains user-approved Alembic migration.

- [ ] **Step 3: Run final verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_config_persistence_contract.py v2-api\tests\test_platform_postgres_design.py v2-api\tests\test_platform_persistence_status.py -q
.\.venv\Scripts\python.exe scripts\verify_platform_project_config_persistence_contract.py
.\.venv\Scripts\python.exe scripts\verify_platform_postgres_design.py
.\.venv\Scripts\python.exe scripts\verify_platform_persistence_status.py
```

Expected: all commands exit 0.

## Self-Review

- Spec coverage: This package advances persistence readiness without creating an Alembic migration or touching a database.
- Placeholder scan: No placeholders or unspecified commands remain.
- Type consistency: Route, service, test, guard, and report all use `project_config_persistence_contract` naming.
