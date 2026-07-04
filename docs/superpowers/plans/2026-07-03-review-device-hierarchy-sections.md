# Review Device Hierarchy Sections Plan

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Objective

Carry the configured device hierarchy into the platform review workbench so reviewers can inspect externally completed work orders by business relationship instead of a flat field list.

The review surface must distinguish:

- device/accessory collection under the task object,
- accessory replacement confirmation,
- conditional accessory follow-up fields controlled by `required_when`,
- photo evidence slots,
- future main-device replacement fields for terminal replacement.

## Scope

Backend:

- Preserve `required_when` in platform review field and photo-slot payloads.

Frontend:

- Map backend `required_when` into API types.
- Group platform review detail fields in both review entry points:
  - `ReviewView.vue`
  - `TaskHallView.vue`
- Show role tags and conditional review hints.

Verification:

- Extend the review hierarchy guard so it checks the real `/task-hall` workbench, not only the nested review view.
- Run focused Vue guards, backend relation-role guard, and frontend build.
- Browser-smoke `/task-hall?project_id=replacement-project` with one local external-completed sample work order.

## Data Safety

- Development-only local sample data was created through the platform import workflow.
- No `.env`, production data, uploads, OSS object, PostgreSQL data, version number, tag, or deployment path is touched.
- Local service must run with `STATE_BACKEND=json`; otherwise project overview routes may wait on the default PostgreSQL backend.

## Rollback

Code rollback:

- Revert changes in review hierarchy mapping and guard files.

Local sample data rollback:

- Roll back the generated local task:
  `POST /projects/replacement-project/work-order-tasks/task-2f174af4472044848ad0c3872b0ab938/rollback`

Production rollback:

- Not applicable in this package because no production write, migration, tag, version bump, or deployment was performed.
