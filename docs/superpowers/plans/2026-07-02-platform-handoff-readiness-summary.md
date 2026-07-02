# Platform Handoff Readiness Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only handoff readiness summary so operators and reviewers can see baseline, review-package readiness, migration block status, and production safety without running a migration or release.

**Architecture:** Build a small backend aggregation service that composes the existing project readiness summary, persistence status, and migration readiness gate. Expose it through the projects router, consume it on `/platform-projects`, and guard the visible UI contract with focused tests and scripts.

**Tech Stack:** FastAPI, pytest, Vue 3, TypeScript, Element Plus, local guard scripts.

---

### Task 1: Backend Read-Only Contract

**Files:**
- Create: `v2-api/tests/test_platform_handoff_readiness.py`
- Create: `v2-api/app/services/platform/handoff_readiness.py`
- Modify: `v2-api/app/api/routes/projects.py`
- Create: `scripts/verify_platform_handoff_readiness.py`

- [x] **Step 1: Write the failing backend test**

Add a test that calls `GET /projects/handoff/readiness` and expects:

```python
assert payload["handoff_version"] == 1
assert payload["ready_for_review_package"] is True
assert payload["ready_for_production_migration"] is False
assert payload["production_baseline"]["branch"] == "production/V3/3.0.71"
assert payload["feature_branch"] == "pm-platform/project-drafts"
assert payload["migration"]["ready_for_migration"] is False
assert "no_tag" in payload["production_safety"]
assert "prepare_pr_or_patch_handoff" in payload["next_actions"]
```

- [x] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_handoff_readiness.py -q
```

Expected: FAIL with 404 because the route does not exist yet.

- [x] **Step 3: Implement the aggregation service and route**

Create `build_platform_handoff_readiness()` that returns only local read-only metadata and aggregates existing services. Add `GET /projects/handoff/readiness` in `projects.py`.

- [x] **Step 4: Add a guard script**

Create `scripts/verify_platform_handoff_readiness.py` to call the service directly and assert the same stable English safety tokens.

- [x] **Step 5: Run GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_handoff_readiness.py v2-api\tests\test_platform_migration_readiness.py v2-api\tests\test_platform_persistence_status.py v2-api\tests\test_platform_project_readiness.py -q
.\.venv\Scripts\python.exe scripts\verify_platform_handoff_readiness.py
```

Expected: all pass.

### Task 2: Frontend Review Signal

**Files:**
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/views/ProjectsView.vue`
- Create: `scripts/verify_vue_platform_handoff_readiness.js`

- [x] **Step 1: Add frontend guard first**

The guard requires `PlatformHandoffReadiness`, `fetchPlatformHandoffReadiness`, `/projects/handoff/readiness`, `handoff-readiness-band`, `交付就绪`, `可评审包`, and `生产迁移未放行`.

- [x] **Step 2: Run RED**

Run:

```powershell
node scripts\verify_vue_platform_handoff_readiness.js
```

Expected: FAIL before the frontend contract exists.

- [x] **Step 3: Add frontend types, mapper, API helper, and UI band**

Load the handoff summary on `/platform-projects` and render a compact top band with review-package readiness, target branch, migration block, and next action.

- [x] **Step 4: Run GREEN and build**

Run:

```powershell
node scripts\verify_vue_platform_handoff_readiness.js
pnpm --dir v2-web build
```

Expected: guard passes and build succeeds with only existing warnings.

### Task 3: Documentation, Team Memory, And Handoff Guard

**Files:**
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Create: `docs/reports/pm-platform-handoff-readiness-summary-2026-07-02.md`
- Modify: `docs/reports/pm-platform-pr-body-2026-07-02.md`
- Modify: `docs/reports/pm-platform-pr-patch-handoff-2026-07-02.md`
- Modify: `scripts/verify_pm_platform_handoff_package.py`

- [x] **Step 1: Record team setting and current package**

Update team memory so the next session sees this package as the current execution rhythm and next queue item.

- [x] **Step 2: Record delivery evidence**

Add a report with changed files, function summary, tests, risk, migration note, and rollback note.

- [x] **Step 3: Guard the handoff package**

Extend `verify_pm_platform_handoff_package.py` with stable English tokens for the new plan, report, backend route, frontend fetch helper, and guard scripts.

- [x] **Step 4: Final verification**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_pm_platform_handoff_package.py
.\.venv\Scripts\python.exe scripts\verify_pm_platform_team_operating_model.py
.\.venv\Scripts\python.exe scripts\verify_production_baseline.py
git diff --check
git status --short -- .env data v2-api/data v2-api/app/static/uploads uploads
```

Expected: all guards pass; sensitive paths remain clean.

## Execution Evidence

- Backend RED: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_handoff_readiness.py -q` failed with `404 Not Found`.
- Backend GREEN: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_handoff_readiness.py v2-api\tests\test_platform_migration_readiness.py v2-api\tests\test_platform_persistence_status.py v2-api\tests\test_platform_project_readiness.py -q` -> `6 passed, 1 warning`.
- Backend guard: `.\.venv\Scripts\python.exe scripts\verify_platform_handoff_readiness.py` -> `[OK] platform handoff readiness summary is consistent`.
- Frontend RED: `node scripts\verify_vue_platform_handoff_readiness.js` failed with missing `PlatformHandoffReadiness`.
- Frontend GREEN: `node scripts\verify_vue_platform_handoff_readiness.js` -> `[OK] Vue platform handoff readiness is wired.`
- Frontend build: `pnpm --dir v2-web build` -> exit 0, `1894 modules transformed`, built in `9.65s`.
- Browser smoke: `/platform-projects` shows `交付就绪`, `可评审包`, `production/V3/3.0.71`, `生产迁移未放行`, and places `.handoff-readiness-band` before `.readiness-summary-band`.
- Final handoff guard: `.\.venv\Scripts\python.exe scripts\verify_pm_platform_handoff_package.py` -> `[OK] PM platform PR/patch handoff package is consistent`.
- Team guard: `.\.venv\Scripts\python.exe scripts\verify_pm_platform_team_operating_model.py` -> `[OK] PM platform team operating model is locked`.
- Production baseline: `.\.venv\Scripts\python.exe scripts\verify_production_baseline.py` -> production ref `origin/production/V3/3.0.71 @ 862659e0e659`, tag `v3.0.71 @ 825f88092701`, current ref contains production baseline.
- `git diff --check` passed.
- Sensitive path check for `.env`, `data`, `v2-api/data`, `v2-api/app/static/uploads`, and `uploads` returned clean.
