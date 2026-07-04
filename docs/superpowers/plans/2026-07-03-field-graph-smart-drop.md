# Field Graph Smart Drop Plan

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Objective

Make the graphical field designer turn drag/drop into field semantics, not only parent reassignment.

The user rule is:

- Device replacement also has hierarchy.
- Module replacement means replacing accessory devices under one task object.
- Terminal replacement means replacing the main terminal device, then confirming whether accessory devices such as communication module and SIM card are replaced.
- Old accessory values, new accessory values, and related photos should be conditionally collected when the confirmation field equals replacement.

## Scope

- Add a focused frontend guard for smart drop wiring.
- Add explicit smart drop intents for task core, main-device replacement, accessory replacement confirmation, conditional accessory collection, and evidence photos.
- Keep photos as `evidence_photo` when they are dragged into conditional collection.
- Add a compact smart-drop panel in `FieldGraphDesigner.vue` with operator-facing rules:
  - `换模块：在任务对象下更换附属设备`
  - `换终端：先确认附属设备是否更换`
- Keep backend field schema, import templates, construction payloads, review behavior, persistence, versioning, tags, and deployment unchanged.

## Verification Plan

- `node scripts\verify_vue_field_graph_smart_drop.js`
- `node scripts\verify_vue_field_graph_relationship_lines.js`
- `node scripts\verify_vue_project_field_graph_designer.js`
- `node scripts\verify_vue_device_hierarchy_config.js`
- `node scripts\verify_vue_field_graph_conditional_required_config.js`
- `node scripts\verify_vue_work_item_schema_config.js`
- `pnpm --dir v2-web build`
- Browser smoke: `/platform-projects`, open `更换终端` field config, confirm the smart-drop panel and device rules render.

## Migration Notes

No database, permission, import/export, OSS, PostgreSQL, or production data migration is included. This package changes frontend configuration behavior only.

## Rollback

- Revert `v2-web/src/components/project-fields/FieldGraphDesigner.vue`.
- Revert `scripts/verify_vue_field_graph_smart_drop.js`.
- Rebuild Vue static assets from the reverted source if generated assets are included.
- No production rollback is needed because there is no deployment, tag, version bump, OSS write, PostgreSQL write, or production data edit.
