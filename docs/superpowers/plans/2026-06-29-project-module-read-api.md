# Project Module Read API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add read-only `/projects/{project_id}/...` module endpoints for progress, delivery, field, review, risks, and tasks.

**Architecture:** Keep `/projects` and `/projects/{project_id}` response shapes unchanged. Add thin route helpers in `v2-api/app/api/routes/projects.py` that validate the project id once, build the current replacement-project overview, and return a single focused section. This prepares the frontend to load platform modules independently without changing storage or production data.

**Tech Stack:** FastAPI, existing platform overview service, pytest.

---

## File Structure

- Modify `v2-api/tests/test_platform_overview.py`: add API regression tests for all focused module endpoints and unknown project 404 behavior.
- Modify `v2-api/app/api/routes/projects.py`: add read-only subroutes for `progress`, `delivery`, `field`, `review`, `risks`, and `tasks`.

## Task 1: Add Failing API Tests

**Files:**
- Modify: `v2-api/tests/test_platform_overview.py`

- [ ] **Step 1: Add module endpoint tests**

Append tests that call:

```python
client.get("/projects/replacement-project/progress")
client.get("/projects/replacement-project/delivery")
client.get("/projects/replacement-project/field")
client.get("/projects/replacement-project/review")
client.get("/projects/replacement-project/risks")
client.get("/projects/replacement-project/tasks")
```

Expected section keys:

```python
{
    "progress": ["stage", "system_progress", "management_progress", "management_locked"],
    "delivery": ["status", "total_items", "completed_items"],
    "field": ["photo_rows_linked", "unconstructed_groups", "exception_count"],
    "review": ["reviewed_groups", "review_rate", "pending_groups"],
    "risks": ["total", "field_exceptions", "delivery_blockers"],
    "tasks": ["total", "uploaded", "reviewing", "archived"],
}
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py -q
```

Expected: new endpoint tests fail with `404`.

## Task 2: Implement Read-Only Module Routes

**Files:**
- Modify: `v2-api/app/api/routes/projects.py`

- [ ] **Step 1: Add project validation helper**

Add `_replacement_overview_or_404(project_id: str)`.

- [ ] **Step 2: Add progress endpoint**

Return only stage, system progress, management progress, and lock state.

- [ ] **Step 3: Add delivery, field, review, risks, and tasks endpoints**

Return the matching nested section from the overview.

- [ ] **Step 4: Run tests and confirm pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py -q
```

Expected: all platform overview tests pass.

## Task 3: Verification and Commit

**Files:**
- Verify route and test changes.

- [ ] **Step 1: Run release gates**

Run:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_release_sop.py
.\.venv\Scripts\python.exe .\scripts\verify_vue_migration_gate.py --strict-native
```

Expected: both pass.

- [ ] **Step 2: Inspect Git status**

Run:

```powershell
git status -sb
git diff --stat
```

Expected: only the new plan, projects route, and platform overview tests changed.

- [ ] **Step 3: Commit**

Run:

```powershell
git add docs/superpowers/plans/2026-06-29-project-module-read-api.md v2-api/app/api/routes/projects.py v2-api/tests/test_platform_overview.py
git commit -m "feat: add project module read endpoints"
```

Expected: commit created on `feat/operations-platform-phase-one`.

## Self-Review

- Spec coverage: covers the requested next API split for the platform modules.
- Placeholder scan: no TBD or deferred implementation steps.
- Type consistency: endpoint names match the platform overview nested section keys.
