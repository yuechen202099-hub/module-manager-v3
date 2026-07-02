# Platform Contract Persistence Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the backend shared contract snapshot so future agents and PR checks can see the project configuration persistence route, record keys, target tables, migration gates, and safety flags.

**Architecture:** Keep `contracts.py` as a read-only names-and-shapes snapshot. Import constants from the project config persistence contract service rather than duplicating safety strings, then verify with focused pytest and the existing snapshot guard.

**Tech Stack:** Python service module, pytest, existing verification script.

---

## File Structure

- Modify: `v2-api/tests/test_platform_contracts.py`
  - Adds failing expectations for the new `persistence` contract section.
- Modify: `v2-api/app/services/platform/contracts.py`
  - Adds `PROJECT_CONFIG_PERSISTENCE_ROUTE`, `PROJECT_CONFIG_RECORD_KEYS`, `PROJECT_CONFIG_ROUNDTRIP_KEYS`, and a `persistence` section in `build_platform_contract_snapshot()`.
- Modify: `scripts/verify_platform_backend_contract_snapshot.py`
  - Adds guard checks for the persistence route, target tables, record keys, migration gates, and safety flags.
- Create: `docs/reports/pm-platform-contract-persistence-snapshot-2026-07-02.md`
  - Documents the scope, verification, migration note, and rollback note.
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
  - Records the completed package and next gated migration step.

### Task 1: Write The Failing Test

**Files:**
- Modify: `v2-api/tests/test_platform_contracts.py`

- [ ] **Step 1: Add persistence assertions**

Add assertions that `snapshot["persistence"]["project_config"]` includes:

```python
assert project_config["route"] == "/projects/{project_id}/persistence/contract"
assert project_config["source_backend"] == "local_json_project_draft_store"
assert project_config["target_backend"] == "postgres_after_approved_migration"
assert project_config["target_tables"] == ["platform_project_configs", "platform_project_config_events"]
assert {"field_schema", "workflow_definition", "project_key"}.issubset(project_config["config_record_keys"])
assert {"can_restore", "preserved_keys", "missing_preserved_keys"}.issubset(project_config["roundtrip_keys"])
assert "requires_user_approval_before_migration" in project_config["migration_gate"]
assert "no_database_connection" in project_config["safety"]
```

- [ ] **Step 2: Run focused pytest**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_contracts.py -q
```

Expected before implementation: FAIL with missing `persistence`.

### Task 2: Implement Snapshot Section

**Files:**
- Modify: `v2-api/app/services/platform/contracts.py`

- [ ] **Step 1: Add constants**

Add exact route/key constants for the project config persistence contract.

- [ ] **Step 2: Add the snapshot section**

Add:

```python
"persistence": {
    "project_config": {
        "route": PROJECT_CONFIG_PERSISTENCE_ROUTE,
        ...
    }
}
```

The section must remain read-only and must not call a database.

- [ ] **Step 3: Run focused pytest**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_contracts.py -q
```

Expected: PASS.

### Task 3: Update Guard And Docs

**Files:**
- Modify: `scripts/verify_platform_backend_contract_snapshot.py`
- Create: `docs/reports/pm-platform-contract-persistence-snapshot-2026-07-02.md`
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

- [ ] **Step 1: Add guard checks**

The guard must fail if the persistence route, target tables, record keys, roundtrip keys, migration gates, or safety flags drift.

- [ ] **Step 2: Write the report**

Document:

- feature scope,
- changed files,
- verification commands,
- migration note,
- rollback note,
- production safety.

- [ ] **Step 3: Update team memory**

Record this package as complete and keep Alembic migration as the next explicit-approval package.

### Task 4: Final Verification

**Files:**
- Verify all touched files.

- [ ] **Step 1: Run related tests and guards**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_contracts.py v2-api\tests\test_platform_project_config_persistence_contract.py -q
.\.venv\Scripts\python.exe scripts\verify_platform_backend_contract_snapshot.py
.\.venv\Scripts\python.exe scripts\verify_platform_project_config_persistence_contract.py
.\.venv\Scripts\python.exe scripts\verify_pm_platform_handoff_package.py
```

Expected: all commands exit 0.

- [ ] **Step 2: Check sensitive paths**

Run:

```powershell
& 'C:/Users/Yuech/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe' status --short -- .env data v2-api/data v2-api/app/static/uploads uploads
```

Expected: no output.

## Self-Review

- Spec coverage: The package keeps persistence names visible to backend decomposition without adding a migration or runtime write path.
- Placeholder scan: No placeholders remain.
- Type consistency: `persistence.project_config` naming matches the report, guard, test, and existing route.
