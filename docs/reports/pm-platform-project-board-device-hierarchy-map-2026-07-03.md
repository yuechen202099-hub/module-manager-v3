# PM Platform Project Board Device Hierarchy Map

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Summary

`/project-board` now shows the configured project fields as a six-layer hierarchy:

- `聚合字段`
- `任务核心`
- `主设备更换`
- `附属设备确认`
- `条件补采`
- `照片证据`

This makes the difference explicit:

- module replacement is an accessory-device replacement under one task object,
- terminal replacement is a main-device replacement plus accessory replacement confirmations.

Each visible field node now also shows its parent relationship and any conditional follow-up rule.

## Changed Files

- `v2-web/src/views/ProjectBoardView.vue`
- `scripts/verify_vue_project_board_field_hierarchy_map.js`
- `docs/superpowers/plans/2026-07-03-project-board-device-hierarchy-map.md`
- `docs/reports/pm-platform-project-board-device-hierarchy-map-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

## Verification

Commands:

- `node scripts\verify_vue_project_board_field_hierarchy_map.js`
  - Red result before implementation: `[FAIL] project board must distinguish main device replacement fields`
  - Green result after implementation: `[OK] Vue project board field hierarchy map is wired.`
- `node scripts\verify_vue_device_hierarchy_config.js`
  - Result: `[OK] Vue device hierarchy configuration is represented.`
- `node scripts\verify_vue_construction_hierarchy_collection.js`
  - Result: `[OK] Vue construction hierarchy collection is wired.`
- `node scripts\verify_vue_review_hierarchy_sections.js`
  - Result: `[OK] Vue review hierarchy sections are wired.`
- `pnpm --dir v2-web build`
  - Result: passed after adding the bundled Node runtime to the command path.
  - Existing warnings remain for VueUse pure annotations and large chunks.

Browser smoke:

- URL: `http://127.0.0.1:52137/project-board?project_id=draft-project`
- DOM verification found:
  - `columnCount: 6`
  - `titles: 聚合字段, 任务核心, 主设备更换, 附属设备确认, 条件补采, 照片证据`
  - `mainDeviceNodes: 旧终端/旧设备（拆回）, 新终端号（安装后扫码）`
  - `accessoryNodes: 通讯模块是否更换, SIM卡是否更换`
  - `conditionalNodes: 旧通讯模块号（更换时扫码）, 新通讯模块号（更换时扫码）, 旧SIM卡号（更换时录入）, 新SIM卡号（更换时录入）`
  - `totalParentRows: 14`
  - `totalConditionRows: 5`
- Current `52137` console check found no relevant errors.

## Risk Notes

- This is a presentation and classification change on the project cockpit; it does not change import, construction submission, review approval, or archive behavior.
- `old_device` is context-sensitive: when the schema has a main `replacement_device`, old devices without `required_when` are shown as main-device recovery; otherwise they stay in the accessory layer.
- Generated Vue static assets changed because the frontend build writes to `v2-api/app/static/vue`.

## Rollback Notes

- Code rollback: revert the changed files listed above.
- Frontend asset rollback: rebuild from the reverted source or restore the prior generated assets.
- Production rollback: no production rollback is needed because no migration, tag, version bump, OSS write, PostgreSQL write, or deployment was performed.
