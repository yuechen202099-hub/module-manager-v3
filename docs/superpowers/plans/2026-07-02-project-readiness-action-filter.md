# Project Readiness Action Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let operators click a `接入待办` action count on `/platform-projects` and immediately filter the project list to projects that need that action.

**Architecture:** Reuse the existing read-only `GET /projects/readiness/summary` payload. The frontend keeps a local selected readiness action, derives `filteredProjects` from the existing project list plus per-project `nextActions`, and renders a clearable filter state. No backend write path, migration, version bump, tag, or deployment is included.

**Tech Stack:** Vue 3 + TypeScript + Element Plus, existing readiness summary API, Node guard script, browser smoke.

---

## File Structure

- Modify: `scripts/verify_vue_project_readiness_summary_list.js`
  - Require the filter state, click wiring, filtered table data, and clear action.
- Modify: `v2-web/src/views/ProjectsView.vue`
  - Add `selectedReadinessAction`, `filteredProjects`, filter text, apply/clear handlers, and visible filter state.
- Create: `docs/reports/pm-platform-readiness-action-filter-2026-07-02.md`
  - Record scope, verification, risk, migration, and rollback notes.
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
  - Record the latest package for future context recovery.
- Modify: `docs/reports/pm-platform-pr-patch-handoff-2026-07-02.md`, `docs/reports/pm-platform-pr-body-2026-07-02.md`, and `scripts/verify_pm_platform_handoff_package.py`
  - Keep the PR/patch handoff package current.

### Task 1: Frontend Guard Red

- [x] Extend `scripts/verify_vue_project_readiness_summary_list.js` to require:

```text
selectedReadinessAction
filteredProjects
applyReadinessActionFilter
clearReadinessActionFilter
readinessActionFilterText
:data="filteredProjects"
@click="applyReadinessActionFilter(item.action)"
筛选中
清除筛选
```

- [x] Run:

```powershell
node scripts\verify_vue_project_readiness_summary_list.js
```

Expected RED observed: `ProjectsView.vue missing readiness summary token: selectedReadinessAction`.

### Task 2: Implement Filter

- [x] Add `selectedReadinessAction = ref('')`.
- [x] Add `filteredProjects` computed. If no action is selected, return `workspace.projects`; otherwise return only projects whose readiness summary item contains the selected action in `nextActions`.
- [x] Render the table with `filteredProjects`.
- [x] Make `接入待办` tags clickable.
- [x] Add a visible `筛选中` state and `清除筛选` button.
- [x] Run the frontend guard until green.

### Task 3: Verify And Handoff

- [x] Run:

```powershell
node scripts\verify_vue_project_readiness_summary_list.js
pnpm --dir v2-web build
```

- [x] Browser smoke:
  - Open `/platform-projects`.
  - Confirm `接入待办` tags are visible.
  - Click one action tag.
  - Confirm the table row count shrinks or equals the selected action count.
  - Confirm `筛选中` and `清除筛选` are visible.

- [x] Run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_pm_platform_handoff_package.py
.\.venv\Scripts\python.exe scripts\verify_production_baseline.py
git diff --check
git status --short -- .env data v2-api/data v2-api/app/static/uploads uploads
```

## Self-Review

- Scope is frontend-only and read-only.
- No placeholders remain.
- Filter is derived from current readiness summary data and does not duplicate backend logic.

## Evidence

- `node scripts\verify_vue_project_readiness_summary_list.js`: `[OK] Project readiness summary list is wired to the frontend.`
- `pnpm --dir v2-web build`: exit 0, `1894 modules transformed`, built in `10.24s`.
- Browser smoke on `/platform-projects`: 4 `接入待办` tags visible; clicking `启用现场、审阅、工单和交付模块 154 个` showed `筛选中`, filtered the table from 193 rows to 154 rows, and `清除筛选` restored 193 rows.
- Handoff report: `docs/reports/pm-platform-readiness-action-filter-2026-07-02.md`.
