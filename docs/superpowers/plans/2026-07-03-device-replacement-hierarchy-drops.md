# Device Replacement Hierarchy Drops Plan

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Objective

Make device replacement fields keep explicit hierarchy while operators configure projects visually.

Business rule:

- Module replacement is an accessory-device replacement under one task object.
- Terminal replacement is a main-device replacement under one task object, then accessory devices such as communication module and SIM card must be confirmed for replacement.

## Scope

- Add visible hierarchy guidance for module replacement and terminal replacement.
- Make device-node drops preserve hierarchy:
  - dropping onto a main replacement device creates an accessory replacement confirmation,
  - dropping onto an accessory confirmation creates conditional child fields,
  - photo fields become evidence-photo fields.
- Keep parent links on the task object rather than falling back to a flat field list.
- Do not change backend schema, import/export behavior, PostgreSQL, OSS, production version, tags, deployment, or production data.

## Verification Plan

- `node scripts\verify_vue_field_graph_smart_drop.js`
- `pnpm --dir v2-web build`
- Browser smoke: open `/platform-projects`, open `更换终端` field configuration, verify the field graph shows aggregate -> task core -> device/action/evidence layers and the smart-drop panel shows both hierarchy rules.

## Migration Notes

No migration. This is a frontend field-configuration behavior and guidance improvement only.

## Rollback

- Revert `v2-web/src/components/project-fields/FieldGraphDesigner.vue`.
- Revert smart-drop guard additions in `scripts/verify_vue_field_graph_smart_drop.js`.
- Rebuild Vue static assets from reverted source if generated assets are included.
- No production rollback is needed because no deployment, tag, version bump, OSS write, PostgreSQL write, or production data edit occurred.
