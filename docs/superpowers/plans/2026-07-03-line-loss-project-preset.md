# Line Loss Project Preset Plan

Date: 2026-07-03

## Objective

Add a practical project preset for station-area line-loss investigation so the platform can create a third project type beyond module replacement and terminal replacement.

## Scope

- Frontend project creation preset only.
- Backend generic template contract verification for the same schema.
- No PostgreSQL migration, no production data edit, no OSS write, no deployment, no official version bump.

## Field Contract

- Primary task object: `station_area_no` / station area.
- Active aggregate field: `power_supply_unit` / power supply unit.
- Task details under the station area: `master_meter_no` and `user_no`.
- Field collection under the station area: `line_loss_issue_type`, `master_meter_photo`, `user_meter_sample_photo`, and `site_check_note`.
- Initial work-order template includes import fields only.
- External-completed template includes import fields plus field-collection evidence that may have been completed outside the platform.

## Verification

- `node scripts\verify_vue_line_loss_project_preset.js`
- `python scripts\verify_platform_line_loss_template_contract.py`

## Migration Note

This package changes configurable project schema presets and template expectations only. It does not introduce a database schema change or persistence migration.

## Rollback Note

Rollback by removing the `line-loss-investigation` project type preset and the two guard scripts. Existing user-created project drafts remain JSON-backed and are not rewritten by this package.
