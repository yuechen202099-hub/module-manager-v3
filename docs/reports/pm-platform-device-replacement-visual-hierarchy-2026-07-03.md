# PM Platform Device Replacement Visual Hierarchy Report

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Production baseline: `production/V3/3.0.77`, `V3.0.77`, commit `4c05cc9`

## Summary

The field graph now makes device replacement hierarchy explicit:

- Module replacement: meter is the task object; the replacement module is shown as an accessory new device.
- Terminal replacement: terminal is the task object; new terminal is shown as the main replacement device; communication module and SIM card are shown as accessory replacement confirmations.
- Conditional old/new accessory fields retain their confirmation-field dependency.
- Default module replacement draft fields now mark `module_asset_no` as required.
- Site-required previews now use required site collection fields plus required photos, instead of every optional site collection field.

## Changed Files

- `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- `v2-web/src/views/ProjectsView.vue`
- `scripts/verify_vue_device_hierarchy_config.js`
- `scripts/verify_vue_work_item_schema_config.js`
- `docs/superpowers/plans/2026-07-03-device-replacement-visual-hierarchy.md`
- `docs/reports/pm-platform-device-replacement-visual-hierarchy-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

Frontend build also regenerated static assets under `v2-api/app/static/vue`.

## Verification

Passed:

- `node scripts\verify_vue_device_hierarchy_config.js`
- `node scripts\verify_vue_work_item_schema_config.js`
- `node scripts\verify_vue_project_field_graph_designer.js`
- `node scripts\verify_vue_line_loss_project_preset.js`
- `pnpm build` with bundled Node added to `PATH`

Browser smoke on `http://127.0.0.1:52137/platform-projects`:

- Create-project dialog loads without a framework overlay.
- Default module replacement graph shows `模块（需更换）` as an accessory new-device and required field.
- Terminal replacement preset shows terminal task object, new terminal as main replacement device, two accessory confirmation nodes, and conditional accessory fields.
- Current-page console check found no relevant `52137` errors or warnings.

Known build warnings:

- Existing Rollup comments from `@vueuse/core`.
- Existing chunk-size warnings over 500 kB.

## Risk

Low to medium. This changes frontend field graph presentation and draft defaults, not backend persistence or production data.

The one behavior change is intentional: default module replacement drafts now treat the replacement module as required, aligning the graph with the site-required preview and module replacement preset.

## Rollback

Revert the changed frontend component/view files, the two guard scripts, this report/plan, and regenerated static Vue assets from this package.

No database rollback is required. No OSS, PostgreSQL, production `.env`, upload files, tags, or release versions were touched.
