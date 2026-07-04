# PM Platform Single Aggregate Readiness

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` at `4c05cc92a71e08a7eb5da6a25cef654271b4cfc5`

## Summary

This package exposes the one-active-aggregate rule in project readiness.

- Backend readiness now includes `single_aggregate_field`.
- The check passes when the project has exactly one aggregate slot and no custom field is marked `aggregate`.
- The check reports `extra_aggregate_keys`, `primary_is_aggregate`, and `active_aggregate_count` in evidence.
- Frontend readiness panels map the check to `聚合口径唯一`.
- The operator action is `fix_aggregate_field`: keep one aggregate field and move the rest into task-core fields.

## Files Changed

- `v2-api/app/services/platform/readiness.py`
- `v2-api/tests/test_platform_project_readiness.py`
- `scripts/verify_platform_project_readiness.py`
- `scripts/verify_platform_single_aggregate_readiness.py`
- `scripts/verify_vue_single_aggregate_readiness.js`
- `v2-web/src/views/ProjectsView.vue`
- `docs/superpowers/plans/2026-07-03-single-aggregate-readiness.md`
- `docs/reports/pm-platform-single-aggregate-readiness-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- frontend build output under `v2-api/app/static/vue`

## Verification

- Red first:
  - `python scripts/verify_platform_single_aggregate_readiness.py` failed because `_single_aggregate_field_check` did not exist.
  - `pytest v2-api/tests/test_platform_project_readiness.py -k "single_aggregate or complete_project_is_ready" -q` failed on the missing import.
- Green:
  - `python scripts/verify_platform_single_aggregate_readiness.py`
  - `python scripts/verify_platform_project_readiness.py`
  - `pytest v2-api/tests/test_platform_project_readiness.py -q`
  - `pytest v2-api/tests/test_platform_overview.py -k "extra_aggregate_field or terminal_replacement_without_accessory_confirmation or work_item_schema" -q`
  - `python scripts/verify_platform_single_aggregate_device_hierarchy_guard.py`
  - `node scripts/verify_vue_single_aggregate_readiness.js`
  - `node scripts/verify_vue_project_readiness_panel.js`
  - `node scripts/verify_vue_project_readiness_summary_list.js`
  - `pnpm --dir v2-web build`

## Risk And Rollback

Risk is low. The change adds a readiness check and labels; it does not alter database schema or production data.

Rollback is code-only: remove the readiness check/action, tests, verification scripts, frontend labels, and rebuild static assets from the previous frontend state.
