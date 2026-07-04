# PM Platform Device Replacement Hierarchy Mode Report

## Summary

The platform now makes device replacement hierarchy modes explicit in both the field graph and project readiness evidence.

It distinguishes:

- `accessory_under_task_object`: module replacement, where the task object stays unchanged and the replaced module or collector is attached under that task object.
- `main_device_with_accessory_confirmation`: terminal replacement, where the main device is replaced first and accessory devices must then be confirmed.

## Baseline

- Production baseline branch: `production/V3/3.0.77`
- Platform branch: `pm-platform/production-3.0.77-sync`
- Baseline commit: `6892205`

## Modified Files

- `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- `v2-api/app/services/platform/readiness.py`
- `scripts/verify_vue_device_replacement_hierarchy_mode.js`
- `scripts/verify_platform_device_replacement_hierarchy_mode.py`
- `docs/superpowers/plans/2026-07-03-device-replacement-hierarchy-mode.md`
- `docs/reports/pm-platform-device-replacement-hierarchy-mode-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Generated Vue static assets under `v2-api/app/static/vue/`

## Verification

- `node scripts\verify_vue_device_replacement_hierarchy_mode.js`
- `python scripts\verify_platform_device_replacement_hierarchy_mode.py`
- `node scripts\verify_vue_field_graph_smart_drop.js`
- `node scripts\verify_vue_project_board_field_hierarchy_map.js`
- `python scripts\verify_platform_device_relation_roles.py`
- `python scripts\verify_platform_project_readiness.py`
- `pnpm --dir v2-web build`
- Browser smoke on the local preview

## Risk

Low. This package is read-only from a data perspective. It adds visual classification and readiness evidence using existing schema fields: `relationRole`, `parentKey`, and `requiredWhen`.

It does not change PostgreSQL, OSS, production data, permissions, import execution, review decisions, archive writes, official version, tags, or deployment.

## Rollback

Remove the field graph hierarchy mode cards, the readiness evidence additions, the two guard scripts, and this report entry, then rebuild Vue static assets. No data rollback is required.
