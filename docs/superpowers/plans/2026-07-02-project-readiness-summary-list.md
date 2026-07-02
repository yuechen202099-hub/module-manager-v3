# Project Readiness Summary List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/platform-projects` show a scan-friendly onboarding/readiness status for every project without opening each field configuration dialog.

**Architecture:** Add a read-only backend summary endpoint that reuses the existing single-project readiness service and returns lightweight per-project rows. The frontend maps that endpoint into existing project-list state and renders a compact `上线状态` column plus an aggregate banner. No database migration, production write path, tag, deployment, or version bump is included.

**Tech Stack:** FastAPI route/service, existing platform catalog/readiness services, Vue 3 + TypeScript + Element Plus, Node guard script, focused pytest.

---

## File Structure

- Modify: `v2-api/app/services/platform/readiness.py`
  - Add `build_project_readiness_summary()` using `list_project_definitions()` and `build_project_readiness(project_id)`.
  - Return only summary fields for list rendering, not full check details.
- Modify: `v2-api/app/api/routes/projects.py`
  - Add `GET /projects/readiness/summary`.
- Modify: `v2-api/tests/test_platform_project_readiness.py`
  - Add a failing test proving the batch summary returns ready/not-ready project rows.
- Modify: `v2-web/src/api/types.ts`
  - Add `ProjectReadinessSummaryItem` and `ProjectReadinessSummaryList`.
- Modify: `v2-web/src/api/services.ts`
  - Add backend types, mapper, and `fetchProjectReadinessSummary()`.
- Modify: `v2-web/src/views/ProjectsView.vue`
  - Load the summary with the project list.
  - Render a `上线状态` column and a compact aggregate line.
- Create: `scripts/verify_vue_project_readiness_summary_list.js`
  - Guard visible tokens, API wiring, and that the feature stays out of the row operation button cluster.
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
  - Record the package and next-state memory.
- Modify: PR/patch handoff docs and guard if needed.

### Task 1: Backend Red Test

**Files:**
- Modify: `v2-api/tests/test_platform_project_readiness.py`

- [x] **Step 1: Add failing test**

Add a test named `test_project_readiness_summary_lists_ready_and_blocked_projects`. It creates one complete terminal project and one incomplete project, then calls:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_readiness.py::test_project_readiness_summary_lists_ready_and_blocked_projects -q
```

Expected RED before implementation:

```text
404 Not Found
```

Observed RED:

```text
assert 404 == 200
```

### Task 2: Backend Summary Endpoint

**Files:**
- Modify: `v2-api/app/services/platform/readiness.py`
- Modify: `v2-api/app/api/routes/projects.py`

- [x] **Step 1: Implement `build_project_readiness_summary()`**

The payload shape must be:

```python
{
    "readiness_version": 1,
    "total": <project_count>,
    "ready": <ready_count>,
    "not_ready": <not_ready_count>,
    "items": [
        {
            "project_id": "...",
            "project_name": "...",
            "project_status": "...",
            "ready": True,
            "summary": {"total": 10, "passed": 10, "failed": 0, "blockers": 0},
            "next_actions": ["ready_for_template_import"],
        }
    ],
    "safety": ["read_only_no_write", "no_database_connection", "no_postgres_schema_change", "no_production_data_edit"],
}
```

- [x] **Step 2: Add the route**

Add `GET /projects/readiness/summary`, returning the summary through `ok(request, summary)`.

- [x] **Step 3: Verify backend green**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_readiness.py -q
```

Expected: all tests in that file pass.

Observed: `3 passed, 1 warning`.

### Task 3: Frontend API And List UI

**Files:**
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/views/ProjectsView.vue`

- [x] **Step 1: Add TypeScript contracts and mapper**

Expose `ProjectReadinessSummaryItem`, `ProjectReadinessSummaryList`, and `fetchProjectReadinessSummary()`.

- [x] **Step 2: Render the list status**

Add a compact `上线状态` table column. For each row, show `可接入` or `需补齐`, plus `通过 x/y 项` or a loading/empty fallback.

- [x] **Step 3: Keep operations column uncluttered**

Do not add a new row-level operation button; detailed checks remain inside `字段配置`.

### Task 4: Guard, Docs, And Handoff

**Files:**
- Create: `scripts/verify_vue_project_readiness_summary_list.js`
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Modify: `docs/reports/pm-platform-pr-patch-handoff-2026-07-02.md`
- Modify: `docs/reports/pm-platform-pr-body-2026-07-02.md`
- Modify: `scripts/verify_pm_platform_handoff_package.py`

- [x] **Step 1: Add frontend guard**

The guard must require tokens for `fetchProjectReadinessSummary`, `ProjectReadinessSummaryList`, `readiness-summary-band`, `上线状态`, `可接入`, and `需补齐`.

- [x] **Step 2: Run frontend guard RED before implementation if possible**

Run:

```powershell
node scripts\verify_vue_project_readiness_summary_list.js
```

Expected: FAIL before frontend wiring, then OK after wiring.

Observed RED: missing `ProjectReadinessSummaryItem`.

Observed GREEN: `[OK] Project readiness summary list is wired to the frontend.`

- [x] **Step 3: Update docs and handoff**

Record verification, risk, migration, and rollback notes. This package has no migration and rollback is branch/patch-level.

### Task 5: Final Verification

**Files:**
- Verify: backend test, frontend guards, build, handoff guard, production baseline, sensitive paths

- [x] **Step 1: Run focused backend test**

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_readiness.py -q
```

- [x] **Step 2: Run focused frontend guards**

```powershell
node scripts\verify_vue_project_readiness_summary_list.js
node scripts\verify_vue_project_readiness_panel.js
```

- [x] **Step 3: Run handoff and safety guards**

```powershell
.\.venv\Scripts\python.exe scripts\verify_pm_platform_handoff_package.py
.\.venv\Scripts\python.exe scripts\verify_production_baseline.py
git diff --check
git status --short -- .env data v2-api/data v2-api/app/static/uploads uploads
```

Observed:

```text
[OK] PM platform PR/patch handoff package is consistent
[OK] production ref: origin/production/V3/3.0.71 @ 862659e0e659
[OK] baseline tag: v3.0.71 @ 825f88092701
[OK] current ref contains production baseline: HEAD @ 8035f3247b5f
```

`git diff --check` and the sensitive path status command produced no output.

- [x] **Step 4: Run frontend build if Vue source changed**

```powershell
pnpm --dir v2-web build
```

Observed: build exited 0 with existing Rollup PURE annotation and large chunk warnings.

## Self-Review

- Spec coverage: The plan advances multi-project platform visibility while staying read-only and data-safe.
- Placeholder scan: No placeholders or ambiguous commands remain.
- Type consistency: Backend snake_case fields map to frontend camelCase fields, matching existing service conventions.
