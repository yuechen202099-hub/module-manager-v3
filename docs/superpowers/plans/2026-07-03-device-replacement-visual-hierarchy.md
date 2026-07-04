# Device Replacement Visual Hierarchy Plan

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Production baseline: `production/V3/3.0.77`, `V3.0.77`, commit `4c05cc9`

## Goal

Make device replacement semantics visible in the project field graph:

- Module replacement: the meter remains the task object, and the new module is an accessory device under that task object.
- Terminal replacement: the terminal remains the task object, the new terminal is the main replacement device, and communication module/SIM card fields are accessory replacement confirmations.
- Conditional accessory fields, such as old/new communication module and old/new SIM card, remain tied to the matching "whether to replace" confirmation field.

## Scope

- Frontend-only visual and local validation update.
- No database migration.
- No PostgreSQL or OSS mutation.
- No production data edit.
- No version bump, tag, or deployment.

## Test First

Extend local guard scripts before implementation:

- `scripts/verify_vue_device_hierarchy_config.js` must require explicit visual classes and labels for main-device replacement, accessory confirmation, accessory new-device, old-device recovery, and conditional links.
- `scripts/verify_vue_work_item_schema_config.js` must require default module-replacement fields to be required and must make site-required previews use required field-collection labels, not every optional collection field.

Expected red checks:

- `verify_vue_device_hierarchy_config.js` initially fails because `deviceRelationClass` is missing.
- `verify_vue_work_item_schema_config.js` initially fails because required field-collection preview helpers are missing.

## Implementation

- Add device relation class helpers in `FieldGraphDesigner.vue`.
- Render relation-specific node classes and connector classes in the mind-map view.
- Rename the third visual layer to "device action/evidence" so main replacement devices and accessory devices can both live under the task object.
- Update default module replacement draft fields to be required.
- Add required field-collection label helpers so "site required" previews only show required site fields and required photos.

## Verification

- Run the updated guard scripts.
- Run frontend production build with bundled Node in `PATH`.
- Browser smoke:
  - Open `/platform-projects`.
  - Open the create-project dialog.
  - Verify default module replacement shows module as required accessory new-device.
  - Select terminal replacement preset.
  - Verify the graph shows terminal as task object, new terminal as main replacement device, and communication module/SIM card as accessory confirmation branches.

## Rollback

Revert:

- `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- `v2-web/src/views/ProjectsView.vue`
- `scripts/verify_vue_device_hierarchy_config.js`
- `scripts/verify_vue_work_item_schema_config.js`
- regenerated `v2-api/app/static/vue` build assets from this package

No production data rollback is required because this package does not write production data or change schema.
