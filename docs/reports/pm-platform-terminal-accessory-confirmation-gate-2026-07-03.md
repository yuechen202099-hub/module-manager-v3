# PM Platform Terminal Accessory Confirmation Gate

## Baseline

- Branch: `pm-platform/production-3.0.77-sync`
- Production baseline branch: `production/V3/3.0.77`
- Baseline commit: `4c05cc92a71e08a7eb5da6a25cef654271b4cfc5`

## Summary

The graphical field designer now makes the user's equipment hierarchy rule explicit:

- Module replacement: the task object remains unchanged and accessory equipment is replaced under that task object.
- Terminal replacement: the main device is replaced, and accessory equipment such as communication module or SIM card must first be confirmed as replaced or not replaced.

The UI now shows a selected-field hierarchy hint for main-device-before, main-device-after, accessory confirmation, conditional collection, and task-object accessory fields. It also blocks terminal replacement schemas that flatten new accessory devices directly under the task object before backend submission.

## Modified Files

- `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- `v2-web/src/views/ProjectsView.vue`
- `scripts/verify_vue_terminal_accessory_confirmation_gate.js`
- `docs/superpowers/plans/2026-07-03-terminal-accessory-confirmation-gate.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

The frontend build also regenerated static Vue assets under `v2-api/app/static/vue`.

## Verification

- `node scripts/verify_vue_terminal_accessory_confirmation_gate.js` -> passed.
- `node scripts/verify_vue_device_hierarchy_config.js` -> passed.
- `node scripts/verify_vue_device_replacement_hierarchy_mode.js` -> passed.
- `node scripts/verify_vue_field_graph_hierarchy_save_gate.js` -> passed.
- `node scripts/verify_vue_replacement_hierarchy_template_apply.js` -> passed.
- `python scripts/verify_platform_device_replacement_hierarchy_mode.py` -> passed.
- `python scripts/verify_platform_single_aggregate_device_hierarchy_guard.py` -> passed.
- `pnpm --dir v2-web build` -> passed with existing Rollup PURE-comment and chunk-size warnings.
- Browser smoke on `http://127.0.0.1:52131/platform-projects?...` -> passed; terminal field configuration dialog exposes the hierarchy hint.

## Safety

- No production `.env`, `data`, `uploads`, OSS, PostgreSQL data, official version number, tag, or deployment was touched.
- No migration was created or executed.
- Rollback is a frontend-only revert of the two Vue source files, the verification script, and generated static Vue assets from this package.
