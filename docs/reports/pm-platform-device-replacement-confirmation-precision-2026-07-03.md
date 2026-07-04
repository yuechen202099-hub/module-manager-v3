# Device Replacement Confirmation Precision Report

## Summary

Refined the equipment hierarchy rule so that device replacement confirmation is detected only when a field is explicitly marked as `accessory_replace_confirm` or clearly named/labeled as a replacement confirmation.

This protects projects that have normal select/enum fields from accidentally entering the equipment replacement readiness gate.

## Changed Files

- `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- `v2-web/src/views/ProjectsView.vue`
- `scripts/verify_vue_device_replacement_confirmation_precision.js`
- `docs/superpowers/plans/2026-07-03-device-replacement-confirmation-precision.md`
- `docs/reports/pm-platform-device-replacement-confirmation-precision-2026-07-03.md`

## Verification

- `node scripts/verify_vue_device_replacement_confirmation_precision.js`
- `node scripts/verify_vue_device_replacement_hierarchy_mode.js`
- `node scripts/verify_vue_terminal_accessory_confirmation_gate.js`
- `python scripts/verify_platform_device_replacement_hierarchy_mode.py`
- `python scripts/verify_platform_device_relation_roles.py`

## Migration And Rollback

- Migration: none.
- Rollback: revert the detector changes and remove the precision verification script.

## Production Safety

- No production data, production uploads, OSS objects, PostgreSQL data, version numbers, tags, or deployment actions were changed.
