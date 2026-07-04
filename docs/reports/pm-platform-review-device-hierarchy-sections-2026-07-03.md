# PM Platform Review Device Hierarchy Sections

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Summary

The platform review workbench now presents configured work-order data by device hierarchy instead of a flat field list.

Visible review sections now include:

- `设备/附属设备采集`
- `附属设备确认`
- `条件补采`
- `照片证据`

The same data contract also supports future `主设备更换` review sections for terminal-replacement projects.

## Changed Files

- `v2-api/app/services/platform/templates.py`
- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/views/ReviewView.vue`
- `v2-web/src/views/TaskHallView.vue`
- `scripts/verify_vue_review_hierarchy_sections.js`
- `docs/superpowers/plans/2026-07-03-review-device-hierarchy-sections.md`
- `docs/reports/pm-platform-review-device-hierarchy-sections-2026-07-03.md`

## Verification

Commands:

- `node scripts\verify_vue_review_hierarchy_sections.js`
  - Result: `[OK] Vue review hierarchy sections are wired.`
- `node scripts\verify_vue_review_platform_filters.js`
  - Result: `[OK] Vue review page exposes platform review filters.`
- `node scripts\verify_vue_construction_hierarchy_collection.js`
  - Result: `[OK] Vue construction hierarchy collection is wired.`
- `node scripts\verify_vue_device_hierarchy_config.js`
  - Result: `[OK] Vue device hierarchy configuration is represented.`
- `python scripts\verify_platform_review_relation_roles.py`
  - Result: `[OK] platform review relation roles are preserved`
- `pnpm --dir v2-web build`
  - Result: passed. Existing warnings remain for VueUse pure annotations and large chunks.

Browser smoke:

- URL: `http://127.0.0.1:52137/task-hall?project_id=replacement-project`
- Local service restarted with `APP_ENV=local`, `DEMO_AUTH_ENABLED=true`, `STATE_BACKEND=json`, `STORAGE_BACKEND=local`.
- A local `external_completed` sample work order was created through the import-batch and work-order-task APIs.
- DOM verification found:
  - `platformCardCount: 1`
  - `platformDetail: 1`
  - `hierarchySections: 4`
  - `deviceReplacement: 1`
  - `accessoryConfirmation: 1`
  - `conditionalAccessory: 1`
  - `photoEvidence: 1`
  - `conditionHints: 2`
  - `roleTags: 8`
- Current `52137` console check found no relevant errors or warnings.

## Risk Notes

- This package changes review presentation and API passthrough only; it does not change review approval semantics.
- Local validation data remains in the development JSON state unless rolled back.
- If the local server is restarted without `STATE_BACKEND=json`, project overview endpoints may wait on the default PostgreSQL backend in machines without the test database.

## Rollback Notes

- Code rollback: revert the files listed above.
- Local sample rollback:
  `POST /projects/replacement-project/work-order-tasks/task-2f174af4472044848ad0c3872b0ab938/rollback`
- Production rollback: no production rollback needed because no production deployment, migration, tag, version bump, OSS write, or PostgreSQL write occurred.
