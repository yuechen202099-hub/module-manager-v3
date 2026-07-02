# Platform Project Readiness Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only project readiness API that tells operators whether a configured project is ready to be taken over, imported, constructed, reviewed, and archived.

**Architecture:** Implement a small backend service that inspects the existing project definition, normalized field schema, workflow, module selection, and platform KPI fields. Expose it as `GET /projects/{project_id}/readiness`; do not write files, connect to a database, or change production data.

**Tech Stack:** FastAPI, existing platform catalog services, pytest, Python verification script.

---

## File Structure

- Create: `v2-api/app/services/platform/readiness.py`
  - Builds readiness checks grouped by field schema, construction evidence, KPI, workflow, import/review, and persistence safety.
- Modify: `v2-api/app/api/routes/projects.py`
  - Adds `GET /projects/{project_id}/readiness`.
- Create: `v2-api/tests/test_platform_project_readiness.py`
  - API-level test for a complete "更换终端" configuration and an incomplete minimal project.
- Create: `scripts/verify_platform_project_readiness.py`
  - Standalone guard that creates temp projects and verifies ready/not-ready checks.
- Create: `docs/reports/pm-platform-project-readiness-2026-07-02.md`
  - Records feature scope, verification, migration note, rollback note, and safety.
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
  - Records this package as the next platform readiness step.

### Task 1: Write Failing Tests

**Files:**
- Create: `v2-api/tests/test_platform_project_readiness.py`

- [ ] **Step 1: Add complete project readiness test**

Create a "更换终端" project with:

- primary field `terminal`,
- aggregate field `station_area`,
- site collection fields `old_terminal`, `communication_module`, `new_sim_card`,
- photo fields `before_photo`, `module_photo`, `after_photo`,
- modules `progress`, `field`, `review`, `tasks`, `delivery`,
- workflow nodes `project_setup`, `field_schema`, `template_import`, `construction_collection`, `review`, `delivery_archive`.

Call:

```text
GET /projects/{project_id}/readiness
```

Expected after implementation:

```python
assert payload["ready"] is True
assert payload["summary"]["failed"] == 0
assert payload["summary"]["passed"] >= 8
```

- [ ] **Step 2: Add incomplete project readiness test**

Create a minimal project with only `progress`, default fields, and default workflow. Expected after implementation:

```python
assert payload["ready"] is False
assert "custom_site_fields" in failed_check_ids
assert "photo_evidence" in failed_check_ids
assert "review_workflow" in failed_check_ids
```

- [ ] **Step 3: Run tests before implementation**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_readiness.py -q
```

Expected before implementation: FAIL because the route is missing.

### Task 2: Implement Service And Route

**Files:**
- Create: `v2-api/app/services/platform/readiness.py`
- Modify: `v2-api/app/api/routes/projects.py`

- [ ] **Step 1: Implement readiness service**

Expose:

```python
def build_project_readiness(project_id: str) -> dict[str, Any]:
    ...
```

The payload must include:

- `readiness_version`,
- `project_id`,
- `ready`,
- `summary`,
- `checks`,
- `next_actions`,
- `safety`.

Each check has:

- `id`,
- `group`,
- `label`,
- `status`,
- `severity`,
- `evidence`,
- `action`.

- [ ] **Step 2: Implement route**

Add:

```python
@router.get("/{project_id}/readiness")
def get_project_readiness(project_id: str, request: Request):
    ...
```

Map missing projects to 404 and invalid configuration to 500.

- [ ] **Step 3: Run tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_readiness.py -q
```

Expected: PASS.

### Task 3: Add Guard And Documentation

**Files:**
- Create: `scripts/verify_platform_project_readiness.py`
- Create: `docs/reports/pm-platform-project-readiness-2026-07-02.md`
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

- [ ] **Step 1: Add guard**

The guard creates complete and incomplete temp projects, calls the API, and verifies ready/not-ready signals.

- [ ] **Step 2: Write report**

Document:

- route,
- what it checks,
- verification commands,
- migration note,
- rollback note,
- safety.

- [ ] **Step 3: Update team memory**

Record this as the next operational readiness package.

### Task 4: Final Verification

**Files:**
- Verify all touched files.

- [ ] **Step 1: Run focused tests and guards**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_readiness.py v2-api\tests\test_platform_project_config_persistence_contract.py v2-api\tests\test_platform_contracts.py -q
.\.venv\Scripts\python.exe scripts\verify_platform_project_readiness.py
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

- Spec coverage: This package advances the platform from configurable fields/workflows toward real project onboarding decisions.
- Placeholder scan: No placeholders remain.
- Type consistency: `readiness` naming is used consistently for route, service, tests, guard, and report.
