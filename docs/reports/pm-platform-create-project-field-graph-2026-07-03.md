# PM Platform Create Project Field Graph Report

Date: 2026-07-03

## Baseline

- Production branch: `production/V3/3.0.77`
- Development branch: `pm-platform/production-3.0.77-sync`
- Baseline commit: `4c05cc9` from `origin/production/V3/3.0.77`

## Changed Files

- `v2-web/src/views/ProjectsView.vue`
- `scripts/verify_vue_project_field_graph_designer.js`
- `docs/superpowers/plans/2026-07-03-create-project-field-graph.md`
- `docs/reports/pm-platform-create-project-field-graph-2026-07-03.md`

## Function Summary

- The new-project draft dialog now reuses `FieldGraphDesigner`.
- Operators can see the aggregate layer, task core layer, device/accessory/evidence layer, and template binding preview before creating a project.
- Drag/drop parent changes and selected-field edits update the draft project form directly.
- Template actions in the create dialog are guarded with a message to create the draft first.

## Verification

- `node scripts\verify_vue_project_field_graph_designer.js` passed.
- `node scripts\verify_vue_work_item_schema_config.js` passed.
- `node scripts\verify_vue_device_hierarchy_config.js` passed.
- `node scripts\verify_vue_line_loss_project_preset.js` passed.
- `pnpm build` passed.
- Browser smoke passed on `http://127.0.0.1:52137/platform-projects`: opening `新建项目` shows the field relationship graph in the create dialog with aggregate, task core, and accessory/evidence layers.

## Risk

- Low. This is a frontend experience change and does not change production data, PostgreSQL, OSS, official version numbers, tags, or deployment.

## Rollback

- Remove the create-dialog `FieldGraphDesigner` usage and create-specific handlers.
- Revert the create-dialog assertions in `scripts/verify_vue_project_field_graph_designer.js`.
- No database rollback is required.
