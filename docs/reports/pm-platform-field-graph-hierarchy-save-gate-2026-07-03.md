# PM Platform Field Graph Hierarchy Save Gate

Date: 2026-07-03

## Scope

This package moves device hierarchy validation closer to the operator while editing fields. The graphical field designer now shows whether the current unsaved field graph can be saved, and `/platform-projects` blocks create/save when a configured device-replacement hierarchy is incomplete.

## Changed Files

- `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- `v2-web/src/views/ProjectsView.vue`
- `scripts/verify_vue_field_graph_hierarchy_save_gate.js`
- `docs/superpowers/plans/2026-07-03-field-graph-hierarchy-save-gate.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- `docs/reports/pm-platform-field-graph-hierarchy-save-gate-2026-07-03.md`

Frontend build regenerated files under `v2-api/app/static/vue/`.

## Behavior

- Field graph now shows `层级完整性`, `换模块完整性`, and `换终端完整性` cards.
- The cards show `可保存` or `需补齐` based on current unsaved field roles.
- Module replacement mode requires direct accessory replacement plus old-device or recovery/evidence data under the task object.
- Terminal replacement mode requires main-device replacement, old device, accessory confirmation, and conditional collection.
- Create project draft and save field configuration both call the hierarchy gate before sending the API request.

## Verification

Red check:

- `node scripts\verify_vue_field_graph_hierarchy_save_gate.js`
  - `[FAIL] designer must define hierarchy readiness issue type`

Passing checks:

- `node scripts\verify_vue_field_graph_hierarchy_save_gate.js`
  - `[OK] Vue field graph hierarchy save gate is wired.`
- `node scripts\verify_vue_device_hierarchy_config.js`
  - `[OK] Vue device hierarchy configuration is represented.`
- `node scripts\verify_vue_field_graph_smart_drop.js`
  - `[OK] Vue field graph smart drop is wired.`
- `python scripts\verify_platform_project_readiness.py`
  - `[OK] platform project readiness is consistent`
- `python scripts\verify_pm_platform_team_operating_model.py`
  - `[OK] PM platform team operating model is locked`
- `pnpm --dir v2-web build`
  - Passed. Existing warnings remained for VueUse Rollup pure annotations and large chunks.
- Browser smoke at `http://127.0.0.1:52147/platform-projects`
  - Opened field configuration and saw 3 hierarchy cards: `层级完整性`, `换模块完整性`, `换终端完整性`; current sample project showed `可保存`.
- `git diff --check`
  - Passed with no output.
- `git status --short -- .env data uploads v2-api/data v2-api/app/static/uploads`
  - Passed with no output.

## Migration Notes

No database migration is required. This is a frontend validation and presentation change that runs before existing project create/save API calls.

## Rollback

Revert the changes to `FieldGraphDesigner.vue`, `ProjectsView.vue`, and `scripts/verify_vue_field_graph_hierarchy_save_gate.js`, then rerun `pnpm --dir v2-web build` to regenerate static Vue assets.

## Risk

Risk is medium. The new gate can block saving device-replacement configurations that were previously allowed when they are visibly incomplete. It does not affect projects with no device-replacement fields and does not write production data.
