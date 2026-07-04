# PM Platform Device Hierarchy Contract Notes

## Baseline

- Branch: `pm-platform/production-3.0.77-sync`
- Production baseline branch: `production/V3/3.0.77`
- Baseline commit: `4c05cc92a71e08a7eb5da6a25cef654271b4cfc5`

## Summary

The platform now exposes the device replacement hierarchy contract in backend readiness evidence and the visual field graph:

- Module replacement: the task object stays unchanged, and accessory equipment is replaced under that task object.
- Terminal replacement: the main device is replaced first, then accessory equipment replacement is confirmed.
- Conditional collection: old parts, new parts, and photos are collected through `required_when` after an accessory is confirmed as replaced.

This makes the user's hierarchy rule visible even when the saved schema already passes backend readiness.

## Modified Files

- `v2-api/app/services/platform/readiness.py`
- `v2-api/tests/test_platform_project_readiness.py`
- `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- `scripts/verify_vue_device_hierarchy_contract_notes.js`
- `docs/superpowers/plans/2026-07-03-device-hierarchy-contract-notes.md`
- `docs/reports/pm-platform-device-hierarchy-contract-notes-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Generated Vue static assets under `v2-api/app/static/vue/`

## Verification

- `python -m pytest v2-api/tests/test_platform_project_readiness.py -q` -> `6 passed`.
- `python scripts/verify_platform_device_replacement_hierarchy_mode.py` -> passed.
- `python scripts/verify_platform_single_aggregate_device_hierarchy_guard.py` -> passed.
- `node scripts/verify_vue_device_hierarchy_contract_notes.js` -> passed.
- `node scripts/verify_vue_device_replacement_hierarchy_mode.js` -> passed.
- `node scripts/verify_vue_terminal_accessory_confirmation_gate.js` -> passed.
- `node scripts/verify_vue_field_graph_backend_readiness_echo.js` -> passed.
- `pnpm --dir v2-web build` -> passed with existing Rollup PURE-comment and chunk-size warnings.
- Browser smoke on `http://127.0.0.1:52131/platform-projects` -> passed; the terminal field configuration dialog shows `后端层级口径`, `任务对象下更换附属设备`, and `确认附属设备是否更换`.

## Risk

Low. The package is read-only from a data perspective. It adds readiness evidence and a visible field-graph explanation using existing schema concepts: `relation_role`, `parent_key`, and `required_when`.

No production `.env`, real `data`, `uploads`, OSS, PostgreSQL data, official version number, tag, release, or server deployment was touched.

## Rollback

Revert the backend readiness evidence addition, the project readiness test, the field graph display block, the new Vue guard script, this report, and regenerated Vue static assets. No database or object-storage rollback is required.
