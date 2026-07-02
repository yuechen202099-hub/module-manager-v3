# Project Board Platform KPI Band Plan

> For future agents: this package promotes the platform KPI split from the project list into the project cockpit.

**Goal:** Let an operator open `/project-board?project_id=<project>` and immediately see the platform work-order stages for the active project.

**Product rule:** The cockpit should speak in operational stages: initial work orders, external completed takeover, pending review, returned rework, approved archive, and not-ready work.

## Task 1: Frontend Guard

**Files:**

- Add: `scripts/verify_vue_project_board_platform_kpis.js`

- [x] Add a guard requiring `ProjectBoardView.vue` to load platform projects.
- [x] Require the active project to be selected from `route.query.project_id`.
- [x] Require the cockpit to render all six platform KPI labels.
- [x] Verify the guard fails before implementation and passes after implementation.

## Task 2: Project Board Cockpit UI

**Files:**

- Modify: `v2-web/src/views/ProjectBoardView.vue`

- [x] Load platform projects together with the existing project board summary data.
- [x] Pick the active platform project from `project_id`, falling back to `replacement-project`.
- [x] Render six operation-stage KPI cards in the cockpit.
- [x] Keep the display read-only and data-safe.
- [x] Keep existing replacement-project board behavior compatible.

## Verification

Run:

```powershell
node scripts\verify_vue_project_board_platform_kpis.js
node scripts\verify_vue_project_platform_kpis.js
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_project_overview_splits_platform_work_order_kpis_by_import_and_review_stage -q
pnpm --dir v2-web build
.\.venv\Scripts\python.exe scripts\verify_production_baseline.py
```

Observed result on 2026-07-01:

- Frontend project-board KPI guard: passed.
- Frontend project-list KPI guard: passed.
- Backend focused KPI test: `1 passed, 1 warning`.
- Frontend build: passed with existing Rollup pure-comment and chunk-size warnings.
- Production baseline check: passed for `origin/production/V3/3.0.71 @ 862659e0e659`; current `HEAD @ 8035f3247b5f` contains the production baseline.
- Sensitive path check for `.env`, `data`, `v2-api/data`, `v2-api/app/static/uploads`, and `uploads`: clean.
- Browser smoke: `/project-board?project_id=replacement-project` loaded, all target KPI labels were visible, and console error logs were empty.

## Migration And Rollback Notes

- No database migration is introduced.
- No production version number is changed.
- No production data, OSS object, upload file, or database row is modified.
- Rollback can remove the KPI band from `ProjectBoardView.vue` and delete `scripts/verify_vue_project_board_platform_kpis.js`.
- Existing backend KPI fields remain compatible with the project list and API response.
