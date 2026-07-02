# PM Platform Backend Contract Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a machine-checkable backend contract snapshot for the PM platform before widening persistence or splitting more backend agents.

**Architecture:** Add a small backend contract module that centralizes the current platform template, field-schema, construction, KPI, and review contract names without changing existing APIs. Guard it with a focused pytest and a lightweight verification script so future packages can detect contract drift before PR or patch handoff.

**Tech Stack:** FastAPI service modules, Python 3.12, pytest, existing platform catalog/template contracts.

---

## Context

- Production baseline: `production/V3/3.0.71`.
- Feature branch: `pm-platform/project-drafts`.
- Lead role: Codex Integrator with Backend Field Schema Agent, Backend Import And Template Agent, Backend Construction And Review Agent, QA And Verification Agent, and Ops And Release Agent boundaries.
- User need: multiple project types should share a configurable platform backbone without each module inventing different field, import, construction, and review semantics.
- Data safety: no database migration, no production data edit, no version bump, no tag, no deployment.

## Files

- Create: `v2-api/app/services/platform/contracts.py`
- Create: `v2-api/tests/test_platform_contracts.py`
- Create: `scripts/verify_platform_backend_contract_snapshot.py`
- Create: `docs/reports/pm-platform-backend-contract-review-2026-07-02.md`
- Update: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Update: `docs/superpowers/plans/2026-07-02-pm-platform-backend-contract-review.md`

## Tasks

### Task 1: Write the failing backend contract test

- [x] **Step 1: Create `v2-api/tests/test_platform_contracts.py`**

Test requirements:

```text
build_platform_contract_snapshot() returns a plain dict.
The snapshot names both template types: initial_work_orders and external_completed.
The field schema contract includes import, field_collection, review, and system sources.
The construction contract names field_schema keys, work_order payload keys, collection payload keys, and required KPI keys.
The review contract names pending_review, approved, returned, exception, and not_ready status counts plus approved/returned/exception actions.
The snapshot agrees with templates.SUPPORTED_TEMPLATE_TYPES.
```

- [x] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api/tests/test_platform_contracts.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'app.services.platform.contracts'
```

### Task 2: Add the contract snapshot module

- [x] **Step 1: Create `v2-api/app/services/platform/contracts.py`**

Expected implementation shape:

```python
def build_platform_contract_snapshot() -> dict[str, Any]:
    return {
        "contract_version": 1,
        "template_types": ["initial_work_orders", "external_completed"],
        "field_schema": {...},
        "construction": {...},
        "review": {...},
        "handoff": {...},
    }
```

- [x] **Step 2: Keep it read-only**

Expected behavior:

```text
The module only exports constants and snapshot builders.
It does not read or write .env, data, uploads, OSS, PostgreSQL, or generated frontend assets.
```

### Task 3: Add a lightweight verification script

- [x] **Step 1: Create `scripts/verify_platform_backend_contract_snapshot.py`**

Expected behavior:

```text
The script imports build_platform_contract_snapshot() through the bundled Python path and verifies required contract keys.
It prints [OK] platform backend contract snapshot is consistent when the snapshot is valid.
It exits non-zero with a clear message when a required field, status, or template type is missing.
```

- [x] **Step 2: Run GREEN checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api/tests/test_platform_contracts.py -q
.\.venv\Scripts\python.exe .\scripts\verify_platform_backend_contract_snapshot.py
```

Expected: both commands exit 0.

### Task 4: Document the contract review handoff

- [x] **Step 1: Update `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`**

Expected update:

```text
Last completed package becomes backend contract snapshot.
Current active package becomes PR/patch handoff preparation or the next persistence package.
The document names the snapshot module as the shared source for agent boundaries.
```

- [x] **Step 2: Add verification evidence to this plan**

Expected evidence:

```text
RED output, pytest GREEN output, verifier output, production baseline check, and sensitive path check.
```

## Verification Evidence

- RED test before implementation:

```text
ModuleNotFoundError: No module named 'app.services.platform.contracts'
```

- GREEN pytest:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api/tests/test_platform_contracts.py -q
```

Observed:

```text
1 passed in 0.73s
```

- GREEN verifier:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_platform_backend_contract_snapshot.py
```

Observed:

```text
[OK] platform backend contract snapshot is consistent
```

- Handoff report: `docs/reports/pm-platform-backend-contract-review-2026-07-02.md`.
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
- No API route behavior change.
- No import/export behavior change.
- No production data, OSS, PostgreSQL, upload, or version change.

## Rollback Notes

- Remove `v2-api/app/services/platform/contracts.py`.
- Remove `v2-api/tests/test_platform_contracts.py`.
- Remove `scripts/verify_platform_backend_contract_snapshot.py`.
- Revert the team development document entry if the package is rolled back.
