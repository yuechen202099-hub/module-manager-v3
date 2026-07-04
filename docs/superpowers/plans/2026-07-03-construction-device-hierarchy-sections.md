# Construction Device Hierarchy Sections Plan

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Production baseline: `production/V3/3.0.77`, `V3.0.77`, commit `4c05cc9`

## Goal

Carry the project field hierarchy from configuration into the construction entry:

- Main replacement devices should be visible as a separate construction section.
- Accessory replacement confirmations should be visible before conditional old/new accessory fields.
- Conditional accessory fields should only appear after the matching confirmation is active, and should show the trigger rule.
- When there is no active construction task, the platform construction entry should still preview grouped field sections.

## Scope

- Frontend-only construction page change.
- No API contract change.
- No persistence change or database migration.
- No production data, OSS, upload, tag, version, or deployment action.

## Test First

Extend `scripts/verify_vue_construction_hierarchy_collection.js` to require:

- `main-device-replacement`, `accessory-confirmation`, and `conditional-accessory-fields` sections.
- Shared `constructionFieldSectionsBase`.
- Conditional accessory detection by `requiredWhen`.
- Explicit labels for main replacement device and accessory confirmation roles.
- Construction row condition hints.
- Grouped platform construction schema preview.

Expected red checks:

- The first run fails because the main-device section is missing.
- The second red run fails because the platform construction entry does not yet preview grouped sections.

## Implementation

- Reuse one section definition for desktop collection, drawer collection, and platform-entry preview.
- Route fields by relation role:
  - `replacement_device` -> main device replacement.
  - `accessory_replace_confirm` -> accessory confirmation.
  - `old_device` / `accessory_new_device` -> device/accessory collection.
  - fields with `requiredWhen.fieldKey` -> conditional accessory fields.
- Add condition hint text below conditional fields.
- Show grouped field preview in the platform construction entry so the hierarchy is visible even with no active work order.

## Verification

- `node scripts\verify_vue_construction_hierarchy_collection.js`
- `node scripts\verify_vue_construction_conditional_visibility.js`
- `node scripts\verify_vue_device_hierarchy_config.js`
- `node scripts\verify_vue_work_item_schema_config.js`
- `node scripts\verify_vue_platform_construction_kpi_fields.js`
- `pnpm build` with bundled Node in `PATH`
- Browser smoke on `/construction?project_id=replacement-project`

## Rollback

Revert:

- `v2-web/src/views/ConstructionView.vue`
- `scripts/verify_vue_construction_hierarchy_collection.js`
- this plan/report
- regenerated `v2-api/app/static/vue` assets from this package

No production data rollback is required.
