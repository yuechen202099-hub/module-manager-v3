# Device Replacement Confirmation Precision Plan

## Baseline

- Branch: `pm-platform/production-3.0.77-sync`
- Production baseline branch: `production/V3/3.0.77`
- Baseline commit: `4c05cc92a71e08a7eb5da6a25cef654271b4cfc5`

## Requirement

Device replacement hierarchy must distinguish ordinary select fields from accessory replacement confirmation fields.

- Module replacement: replace accessory devices under one task object.
- Terminal replacement: replace the main device, then confirm whether each accessory device is replaced.
- Plain select or enum fields must not trigger replacement hierarchy checks.

## Implementation Steps

1. Add a focused Vue verification script that fails when every select or enum field is treated as an accessory replacement confirmation.
2. Narrow `FieldGraphDesigner.vue` replacement confirmation detection to explicit `accessory_replace_confirm` roles or clear replacement-confirmation names/labels.
3. Apply the same narrowed rule to the project save gate in `ProjectsView.vue`.
4. Re-run existing device hierarchy verification scripts to ensure the module and terminal replacement modes still pass.

## Migration And Rollback

- Database migration: not required.
- Data migration: not required.
- Rollback: revert the two frontend detector changes and remove `scripts/verify_vue_device_replacement_confirmation_precision.js`.

## Safety

- No production `.env`, `data`, `uploads`, OSS, PostgreSQL data, tags, version numbers, or deployment paths are touched.
