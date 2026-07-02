# Project Readiness Action Todos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn project-list readiness from a passive `可接入/需补齐` status into an actionable onboarding todo summary that shows what operators should fix next.

**Architecture:** Extend the existing read-only `GET /projects/readiness/summary` response with aggregated `action_counts` derived from not-ready projects' `next_actions`. The frontend renders those counts in the existing `上线检查` band and keeps detailed diagnostics in the existing field-configuration readiness panel. No migration, production write, version bump, tag, or deployment is included.

**Tech Stack:** FastAPI service tests, existing readiness service, Vue 3 + TypeScript + Element Plus, Node guard script, existing handoff guards.

---

## File Structure

- Modify: `v2-api/app/services/platform/readiness.py`
  - Add action-count aggregation for not-ready projects.
- Modify: `v2-api/tests/test_platform_project_readiness.py`
  - Test that the summary returns `action_counts` for missing field schema and workflow actions.
- Modify: `scripts/verify_platform_project_readiness.py`
  - Guard that the route keeps action counts and stays lightweight.
- Modify: `v2-web/src/api/types.ts`
  - Add `ProjectReadinessActionCount`.
- Modify: `v2-web/src/api/services.ts`
  - Map `action_counts` to `actionCounts`.
- Modify: `v2-web/src/views/ProjectsView.vue`
  - Show a compact `接入待办` list in the `上线检查` band.
- Modify: `scripts/verify_vue_project_readiness_summary_list.js`
  - Guard the visible `接入待办` tokens and API mapping.
- Update: docs/reports and team memory.

### Task 1: Backend Red Test

- [x] Add assertions to `test_project_readiness_summary_lists_ready_and_blocked_projects`:

```python
action_counts = {item["action"]: item["count"] for item in payload["action_counts"]}
assert action_counts["complete_field_schema"] >= 1
assert action_counts["enable_review_workflow"] >= 1
assert "ready_for_template_import" not in action_counts
```

- [x] Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_readiness.py::test_project_readiness_summary_lists_ready_and_blocked_projects -q
```

Expected RED: missing `action_counts`.

Observed RED:

```text
KeyError: 'action_counts'
```

### Task 2: Backend Implementation

- [x] Add an `_action_counts(items)` helper that counts `next_actions` only for `ready == False` items.
- [x] Add `action_counts` to `build_project_readiness_summary()`.
- [x] Extend `scripts/verify_platform_project_readiness.py`.
- [x] Run the readiness test file and guard.

### Task 3: Frontend Implementation

- [x] Add frontend types and mapping.
- [x] Add `topReadinessActionCounts` and `readinessActionCountText` computed/helper logic.
- [x] Render a compact `接入待办` line in `.readiness-summary-band`.
- [x] Extend the Vue guard and run it.

### Task 4: Handoff And Verification

- [x] Update the readiness summary report, PR body/report, and team memory.
- [ ] Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_readiness.py -q
.\.venv\Scripts\python.exe scripts\verify_platform_project_readiness.py
node scripts\verify_vue_project_readiness_summary_list.js
pnpm --dir v2-web build
.\.venv\Scripts\python.exe scripts\verify_pm_platform_handoff_package.py
.\.venv\Scripts\python.exe scripts\verify_production_baseline.py
git diff --check
git status --short -- .env data v2-api/data v2-api/app/static/uploads uploads
```

Observed so far:

- Backend readiness tests: `3 passed, 1 warning`.
- Backend readiness guard: `[OK] platform project readiness is consistent`.
- Vue readiness summary guard: `[OK] Project readiness summary list is wired to the frontend.`
- Frontend build: exited 0 with existing Rollup PURE annotation and large chunk warnings.
- Browser smoke: `接入待办` showed action counts such as `启用模板接入流程 151 个`.

## Self-Review

- Scope remains focused on read-only onboarding guidance.
- No placeholders or destructive operations.
- Backend snake_case `action_counts` maps to frontend camelCase `actionCounts`.
