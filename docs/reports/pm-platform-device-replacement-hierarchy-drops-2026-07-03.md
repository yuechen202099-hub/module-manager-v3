# PM Platform Device Replacement Hierarchy Drops

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Summary

The field graph now treats device replacement as a hierarchy, not a flat field list.

The visible rules are:

- `换模块：任务对象 -> 附属设备更换`
- `换终端：任务对象 -> 主设备更换 -> 附属设备确认`

Device-node drops now preserve the intended relationship:

- dropping onto a main replacement device creates an accessory replacement confirmation,
- dropping onto an accessory confirmation creates conditional child fields,
- photo fields become evidence-photo fields.

## Changed Files

- `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- `scripts/verify_vue_field_graph_smart_drop.js`
- `docs/superpowers/plans/2026-07-03-device-replacement-hierarchy-drops.md`
- `docs/reports/pm-platform-device-replacement-hierarchy-drops-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

## Verification

Commands:

- `node scripts\verify_vue_field_graph_smart_drop.js`
  - Red check before implementation: failed with `FieldGraphDesigner.vue missing smart drop token: function fieldDropIntentForDeviceNode`.
  - Green check after implementation: `[OK] Vue field graph smart drop is wired.`
- `pnpm --dir v2-web build`
  - Result: passed. Existing VueUse annotation and large chunk warnings remain.

Browser smoke:

- URL: `http://127.0.0.1:52137/platform-projects`
- Opened `更换终端` -> `字段配置`.
- DOM and screenshot verification found the field graph with aggregate -> task core -> device/action/evidence layers.
- The graph showed the terminal task object, old terminal/device recovery, new terminal scan, communication module confirmation, SIM card confirmation, conditional old/new accessory fields, and evidence photos.
- Smart-drop panel showed both hierarchy rules and all four drop zones: task core, main device replacement, accessory device confirmation, and conditional collection.
- The field configuration was not saved.
- Current `52137` console check found no relevant errors or warnings.

## Risk Notes

- This package changes frontend field-configuration behavior and guidance only.
- It does not execute database migrations, write PostgreSQL, write OSS, modify production data, change import/export APIs, tag, deploy, or occupy an official production version number.

## Rollback Notes

- Revert the files listed above.
- Rebuild Vue static assets from reverted source if generated assets are included.
- No production rollback is needed because no production deployment, migration, tag, version bump, OSS write, PostgreSQL write, or production data edit occurred.
