# PM Platform Device Hierarchy Refinement Report

Date: 2026-07-03

## Baseline

- Production branch: `production/V3/3.0.77`
- Development branch: `pm-platform/production-3.0.77-sync`
- Baseline commit: `4c05cc9` from `origin/production/V3/3.0.77`

## Changed Files

- `v2-api/app/services/platform/catalog.py`
- `v2-web/src/views/ProjectsView.vue`
- `scripts/verify_platform_device_relation_roles.py`
- `scripts/verify_vue_device_hierarchy_config.js`
- `docs/reports/pm-platform-device-hierarchy-refinement-2026-07-03.md`

## Function Summary

- Refined the replacement hierarchy semantics:
  - Module replacement: the meter remains the task object; the new module is an attached accessory device under `meter_no`.
  - Terminal replacement: the terminal remains the task object; the new terminal is the main replacement device under `terminal_no`.
  - Terminal accessory devices, such as communication module and SIM card, remain confirmation-driven replacement branches.
- Updated backend default module replacement schema and frontend default/preset project schema to keep the new module role as `accessory_new_device`.
- Tightened the frontend guard so it checks the `module_asset_no` field block itself instead of matching a later sibling field.

## Verification

- `node scripts\verify_vue_device_hierarchy_config.js`
- `python scripts\verify_platform_device_relation_roles.py`

## Risk

- Low to medium. This changes field relation semantics for configurable project schemas, not legacy task data. Review, construction, and project-board screens already understand both `replacement_device` and `accessory_new_device` as device fields.

## Rollback

- Change `module_asset_no` relation role back to `replacement_device` in the backend default schema and frontend defaults/preset.
- Revert the two guard-script expectation changes.
- No database rollback is required for this package.
