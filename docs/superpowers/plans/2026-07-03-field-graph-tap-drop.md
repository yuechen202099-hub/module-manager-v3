# Field Graph Tap Drop Plan

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Objective

Make the field graph smart drop usable on tablets and in browsers where HTML5 drag/drop is unreliable.

The operator should be able to:

- Click a custom field card to select it.
- Click a smart drop target such as `拖到主设备更换`.
- Apply the same hierarchy semantics that drag/drop uses.

## Scope

- Reuse the smart-drop update logic for both drag and click/tap.
- Add selected-field state for smart drop targets.
- Add click and keyboard Enter/Space handlers to smart drop targets.
- Add visible guidance: `先选择字段，再点击落点应用` and `选中字段后点击应用`.
- Keep backend schema, API, database, import/export, review, construction, versioning, tags, and deployment unchanged.

## Verification Plan

- `node scripts\verify_vue_field_graph_smart_drop.js`
- `node scripts\verify_vue_field_graph_relationship_lines.js`
- `node scripts\verify_vue_project_field_graph_designer.js`
- `node scripts\verify_vue_device_hierarchy_config.js`
- `node scripts\verify_vue_field_graph_conditional_required_config.js`
- `node scripts\verify_vue_work_item_schema_config.js`
- `pnpm --dir v2-web build`
- Browser smoke: open `/platform-projects`, edit `更换终端`, select `终端地址`, click `拖到主设备更换`, and confirm it becomes `主设备 · 更换后`.

## Migration Notes

No database, permission, import/export, OSS, PostgreSQL, or production data migration is included. This is a frontend interaction improvement only.

## Rollback

- Revert `v2-web/src/components/project-fields/FieldGraphDesigner.vue`.
- Revert the extra expectations in `scripts/verify_vue_field_graph_smart_drop.js`.
- Rebuild Vue static assets from reverted source if generated assets are included.
- No production rollback is needed because there is no deployment, tag, version bump, OSS write, PostgreSQL write, or production data edit.
