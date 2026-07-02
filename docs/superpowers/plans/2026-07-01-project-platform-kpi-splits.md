# Project Platform KPI Splits Plan

> **For agentic workers:** This plan records the project-level KPI split package for the PM platform build-out.

**Goal:** Let project operators see different operational states separately: initial work orders, external completed takeover, pending review, returned rework, approved archive, and not-ready work.

**Product rule:** A project cockpit must explain progress in operational language, not only generic uploaded/reviewing/archive totals.

## Task 1: Backend KPI Contract

**Files:**

- Modify: `v2-api/tests/test_api.py`
- Modify: `v2-api/app/services/platform/templates.py`
- Modify: `v2-api/app/services/platform/catalog.py`

- [x] Add a failing test that imports both initial work orders and external-completed takeover rows.
- [x] Move one initial work order into returned rework and one external-completed work order into approved archive.
- [x] Require project overview `tasks` to expose:
  - `initial_work_orders`,
  - `external_completed`,
  - `pending_review`,
  - `returned_rework`,
  - `approved_archive`,
  - `not_ready`.
- [x] Store `source_template_type` on newly executed local platform work orders.
- [x] Summarize work orders by import source and review stage.

## Task 2: Frontend KPI Exposure

**Files:**

- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/views/ProjectsView.vue`
- Add: `scripts/verify_vue_project_platform_kpis.js`

- [x] Map backend snake_case KPI fields to frontend camelCase fields.
- [x] Show platform KPI splits in the project list task center column.
- [x] Add a frontend guard so the KPI mapping and display are not accidentally removed.

## Verification

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_project_overview_splits_platform_work_order_kpis_by_import_and_review_stage v2-api\tests\test_api.py::test_project_overview_counts_local_platform_work_orders_after_execution v2-api\tests\test_api.py::test_external_completed_import_execution_marks_orders_ready_for_review_with_platform_fill -q
node scripts\verify_vue_project_platform_kpis.js
node scripts\verify_vue_project_import_wizard_actions.js
pnpm --dir v2-web build
```

Observed result on 2026-07-01:

- Backend focused tests: `3 passed, 1 warning`.
- Frontend KPI guard: passed.
- Import wizard guard: passed.
- Frontend build: passed with existing Rollup/chunk-size warnings.

## Migration And Rollback Notes

- No database migration is introduced.
- New local platform work orders receive `source_template_type`.
- Existing local platform work orders without `source_template_type` are counted as initial work orders for compatibility.
- Rollback can remove the new KPI fields and UI display; existing local work-order records remain readable.

