# Construction Rework Filter Plan

> **For agentic workers:** This plan records the rework queue package for the PM platform build-out.

**Goal:** Make returned platform work orders easy for field operators to find after review sends them back for rework.

**Product rule:** Review return is not only a status. It must become an actionable field-construction queue item with the return reason visible.

## Task 1: Guard The Rework Queue

**Files:**

- Modify: `scripts/verify_vue_platform_construction_rework.js`

- [x] Extend the guard so construction view must expose:
  - `platformReworkOnly`,
  - `platformConstructionReworkOrders`,
  - `platformConstructionDisplayOrders`,
  - `platform-rework-filter`.
- [x] Run the guard before implementation and observe failure.

## Task 2: Field Construction UI

**Files:**

- Modify: `v2-web/src/views/ConstructionView.vue`

- [x] Keep the existing returned-work-order reason display.
- [x] Add a returned-rework-only filter on the platform work-order entry card.
- [x] Prioritize returned work orders in the display list.
- [x] Increase the platform preview list from three records to five filtered records so returned items are less likely to be hidden.

## Verification

Run:

```powershell
node scripts\verify_vue_platform_construction_rework.js
node scripts\verify_vue_review_platform_filters.js
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_project_review_work_order_action_persists_local_status v2-api\tests\test_api.py::test_external_completed_import_execution_marks_orders_ready_for_review_with_platform_fill -q
pnpm --dir v2-web build
```

Observed result on 2026-07-01:

- Rework guard: passed after implementation.
- Review filters guard: passed.
- Backend focused tests: `2 passed, 1 warning`.
- Frontend build: passed with existing Rollup/chunk-size warnings.

## Migration And Rollback Notes

- No database migration is introduced.
- No backend endpoint change is introduced.
- The change is UI-only plus a guard script.
- Rollback can remove the `ConstructionView.vue` filter additions and restore the guard script to the previous checks.

