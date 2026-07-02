# External Completed Import Review Handoff Plan

> **For agentic workers:** This plan records the current backend import package so future agents can continue without relying on chat history.

**Goal:** When a user imports a mid-project takeover workbook for work that was completed outside the platform, local platform work orders should be created as already collected and ready for review. Platform-owned KPI fields that the external workbook cannot provide should be filled at import execution time.

**Product rule:** `initial_work_orders` means work still needs field construction. `external_completed` means the work already happened outside the platform and should enter the platform at the review stage.

## Task 1: Backend Execution Semantics

**Files:**

- Modify: `v2-api/app/services/platform/templates.py`
- Modify: `v2-api/tests/test_api.py`

- [x] Add a regression test proving `external_completed` execution:
  - creates local platform work orders,
  - marks `collection_status` as `submitted`,
  - exposes `review_status` as `pending_review`,
  - copies field-collection values into `collection_field_values`,
  - fills platform KPI fields such as installer, completed time, upload time, work-order id, and photo count.

- [x] Update `execute_import_work_order_task()` so external-completed rows receive platform fill values at execution time.

- [x] Keep `initial_work_orders` behavior as the ordinary unconstructed work-order path.

## Task 2: Dashboard Compatibility

**Files:**

- Modify: `v2-api/tests/test_api.py`

- [x] Keep the dashboard count regression on `initial_work_orders`, because that test covers unconstructed, submitted, approved, and returned states.

- [x] Add full modules in dashboard tests only when the assertions expect those sections to exist. This preserves the product rule that each project can enable only the modules it needs.

## Verification

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_project_work_order_task_executes_idempotently_and_rolls_back_local_records v2-api\tests\test_api.py::test_external_completed_import_execution_marks_orders_ready_for_review_with_platform_fill v2-api\tests\test_api.py::test_project_overview_counts_local_platform_work_orders_after_execution v2-api\tests\test_api.py::test_project_review_work_orders_include_collected_platform_items -q
```

Observed result on 2026-07-01: `4 passed, 1 warning`.

## Migration And Rollback Notes

- No database migration is introduced in this package.
- Import execution still writes only to the local platform JSON stores used by the current platform prototype.
- Rollback path remains `POST /projects/{project_id}/work-order-tasks/{task_id}/rollback`, which deletes local platform work orders created by the task.
- The change does not touch production OSS, PostgreSQL, `.env`, `data`, or uploads.

