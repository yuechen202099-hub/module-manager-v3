# Main Old Device Hierarchy Plan

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `4c05cc9`

## Objective

Keep device replacement hierarchy clear when a project replaces either an accessory device or a main device.

Module replacement remains an accessory-device change under one task object. Terminal replacement has a main-device before/after pair, then separate accessory replacement confirmations for communication module, SIM card, and similar children.

## Scope

- Refine the field graph designer so unconditional `old_device` fields are shown as main-device-before fields when the same schema has a `replacement_device`.
- Keep conditional `old_device` fields under accessory follow-up collection when they depend on an accessory replacement confirmation.
- Add focused guard coverage to prevent future flattening of old terminal/device fields.
- Do not change database schema, production version, tags, deployment, OSS, PostgreSQL data, or production `.env`.

## Verification Plan

- `node scripts\verify_vue_device_hierarchy_config.js`
- `python scripts\verify_platform_device_relation_roles.py`
- `python scripts\verify_seed_terminal_demo_hierarchy_roles.py`
- `node scripts\verify_vue_project_board_field_hierarchy_map.js`
- `node scripts\verify_vue_field_graph_relationship_lines.js`
- `pnpm --dir v2-web build`

## Rollback

- Revert `v2-web/src/components/project-fields/FieldGraphDesigner.vue`.
- Revert `scripts/verify_vue_device_hierarchy_config.js`.
- Rebuild Vue static assets from reverted source if generated assets are included.
- No database rollback is required.
