# PM Platform Field Graph Tap Drop

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Summary

The field graph smart drop panel now supports a tablet-friendly interaction:

- Select a custom field card.
- Click or tap a smart drop target.
- The target applies the same hierarchy rules as drag/drop.

This provides a practical fallback when native HTML5 drag/drop is unreliable and makes field setup easier on a LAN tablet.

## Changed Files

- `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- `scripts/verify_vue_field_graph_smart_drop.js`
- `docs/superpowers/plans/2026-07-03-field-graph-tap-drop.md`
- `docs/reports/pm-platform-field-graph-tap-drop-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

Frontend build also regenerated Vue static assets under `v2-api/app/static/vue/`.

## Verification

Commands:

- `node scripts\verify_vue_field_graph_smart_drop.js`
  - Red result before implementation: `[FAIL] FieldGraphDesigner.vue missing smart drop token: selectedCustomFieldIndex`
  - Green result after implementation: `[OK] Vue field graph smart drop is wired.`
- `node scripts\verify_vue_field_graph_relationship_lines.js`
  - Result: `[OK] Vue field graph relationship lines are visible.`
- `node scripts\verify_vue_project_field_graph_designer.js`
  - Result: `[OK] Vue project field graph designer is wired.`
- `node scripts\verify_vue_device_hierarchy_config.js`
  - Result: `[OK] Vue device hierarchy configuration is represented.`
- `node scripts\verify_vue_field_graph_conditional_required_config.js`
  - Result: `[OK] Vue field graph conditional required config is wired.`
- `node scripts\verify_vue_work_item_schema_config.js`
  - Result: `[OK] Vue project creation configures work item schema fields.`
- `pnpm --dir v2-web build`
  - Result: passed after temporarily prepending the bundled Node runtime to PATH.
  - Existing warnings remain for VueUse pure annotations and large chunks.

Browser smoke:

- URL: `http://127.0.0.1:52137/platform-projects`
- Flow: open `更换终端` -> `字段配置`.
- Selected `终端地址`, then clicked `拖到主设备更换`.
- Observed result:
  - Before: `终端地址` was `任务详情 · 录入 · 文本 · 选填`.
  - After: `终端地址` became `主设备 · 更换后 · 扫码 · 文本 · 必填`.
  - Summary changed from `1 个 主设备更换` to `2 个 主设备更换`.
- Current-port console filter for `52137` returned no errors or warnings.
- The browser screenshot showed the selected field, smart-drop panel, and updated main-device relationship.

## Risk Notes

- This package changes frontend field configuration interaction only.
- It does not save data until the operator uses the existing save action in the field configuration dialog.
- It does not execute migrations, change persistence, write PostgreSQL, write OSS, change production data, create tags, deploy, or bump the official production version.

## Rollback Notes

- Code rollback: revert the changed files listed above.
- Static asset rollback: rebuild from reverted source or restore the previous generated Vue assets.
- Production rollback: no production rollback is needed because no production release, migration, tag, version bump, OSS write, or PostgreSQL write was performed.
