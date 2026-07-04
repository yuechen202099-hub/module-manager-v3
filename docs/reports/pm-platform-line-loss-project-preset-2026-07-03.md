# PM Platform Line Loss Project Preset Report

Date: 2026-07-03

## Baseline

- Production branch: `production/V3/3.0.77`
- Development branch: `pm-platform/production-3.0.77-sync`
- Baseline commit: `4c05cc9` from `origin/production/V3/3.0.77`

## Changed Files

- `v2-web/src/views/ProjectsView.vue`
- `scripts/verify_vue_line_loss_project_preset.js`
- `scripts/verify_platform_line_loss_template_contract.py`
- `docs/superpowers/plans/2026-07-03-line-loss-project-preset.md`
- `docs/reports/pm-platform-line-loss-project-preset-2026-07-03.md`

## Function Summary

- Added a `line-loss-investigation` project preset for station-area line-loss investigation.
- Uses one active aggregate field, `power_supply_unit`.
- Uses `station_area_no` as the task object.
- Keeps `master_meter_no` and `user_no` as task details under the station area.
- Keeps issue type and meter photos as field-collection evidence under the station area.
- Preserves the template split: initial work-order import uses import fields; external-completed import can include field-collection evidence completed outside the platform.

## Verification

- `node scripts\verify_vue_line_loss_project_preset.js`
- `python scripts\verify_platform_line_loss_template_contract.py`

## Risk

- Low. This package adds a frontend preset and guard scripts. It does not execute database migration, write PostgreSQL, write OSS, deploy, create a tag, or change the official production version.

## Rollback

- Remove the `line-loss-investigation` preset from `v2-web/src/views/ProjectsView.vue`.
- Remove the two line-loss guard scripts.
- No database rollback is required for this package.
