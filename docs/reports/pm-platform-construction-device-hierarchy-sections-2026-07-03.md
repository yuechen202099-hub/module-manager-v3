# PM Platform Construction Device Hierarchy Sections Report

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Production baseline: `production/V3/3.0.77`, `V3.0.77`, commit `4c05cc9`

## Summary

Construction now receives the device hierarchy from project field configuration:

- Construction fields are grouped into task core, main device replacement, device/accessory collection, accessory confirmation, conditional accessory collection, and supporting fields.
- Conditional accessory fields show their trigger rule, for example `collector_replace_confirm = 更换 时显示并必采`.
- The platform construction entry previews the same grouped sections even when no active construction task is selected.

## Changed Files

- `v2-web/src/views/ConstructionView.vue`
- `scripts/verify_vue_construction_hierarchy_collection.js`
- `docs/superpowers/plans/2026-07-03-construction-device-hierarchy-sections.md`
- `docs/reports/pm-platform-construction-device-hierarchy-sections-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

Frontend build regenerated static assets under `v2-api/app/static/vue`.

## Verification

Passed:

- `node scripts\verify_vue_construction_hierarchy_collection.js`
- `node scripts\verify_vue_construction_conditional_visibility.js`
- `node scripts\verify_vue_device_hierarchy_config.js`
- `node scripts\verify_vue_work_item_schema_config.js`
- `node scripts\verify_vue_platform_construction_kpi_fields.js`
- `pnpm build` with bundled Node added to `PATH`

Browser smoke on `http://127.0.0.1:52137/construction?project_id=replacement-project`:

- Page title: `Module Manager V3.0.77`.
- Page rendered construction content and no framework overlay.
- Current-page console check found no relevant `52137` errors or warnings.
- Platform construction entry showed grouped module-replacement sections:
  - `设备/附属设备采集`
  - `附属设备确认`
  - `条件补采`

The active local project is module replacement, so a `主设备更换` section is not expected on this route. The terminal main-device branch is guarded by the construction hierarchy script and the field graph/device hierarchy scripts.

Known build warnings:

- Existing Rollup comments from `@vueuse/core`.
- Existing chunk-size warnings over 500 kB.

## Risk

Low. This changes construction presentation and grouping only. It does not change submitted field keys, API payload shape, database schema, or production data.

## Rollback

Revert the changed construction view, guard script, this report/plan, and regenerated Vue static assets from this package.

No database rollback is required. No OSS, PostgreSQL, production `.env`, upload files, tags, or release versions were touched.
