# PM Platform Main Old Device Hierarchy Report

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `4c05cc9`

## Summary

The field graph now distinguishes a main-device old value from an accessory old value.

When a schema contains a main `replacement_device`, an unconditional `old_device` is displayed as the main device before replacement. Conditional `old_device` fields still remain under accessory follow-up collection, so terminal replacement and module replacement keep different hierarchy semantics.

## Changed Files

- `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- `scripts/verify_vue_device_hierarchy_config.js`
- `docs/superpowers/plans/2026-07-03-main-old-device-hierarchy.md`
- `docs/reports/pm-platform-main-old-device-hierarchy-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

## Verification

- Red check before implementation:
  - `node scripts\verify_vue_device_hierarchy_config.js`
  - Result: failed because `isMainOldDeviceField` was missing.
- Green checks after implementation:
  - `node scripts\verify_vue_device_hierarchy_config.js`
  - `python scripts\verify_platform_device_relation_roles.py`
  - `python scripts\verify_seed_terminal_demo_hierarchy_roles.py`
  - `node scripts\verify_vue_project_board_field_hierarchy_map.js`
  - `node scripts\verify_vue_field_graph_relationship_lines.js`
  - `pnpm --dir v2-web build`
    - Result: passed. Existing VueUse annotation and large chunk warnings remain.
- Browser smoke:
  - Started a temporary local current-code server on `127.0.0.1:52145` with temp demo data.
  - Opened `/platform-projects`, logged in with the local demo admin account, opened `更换终端` field configuration.
  - Verified old terminal/device is displayed as `主设备 · 更换前`, while old communication module and old SIM remain accessory conditional follow-up fields.

## Risk

- Low. This is a frontend hierarchy classification and guard update. It does not change persisted schema values or production data.
- The visible effect is that old terminal/device fields in terminal-replacement projects are no longer described as accessory old devices in the graph.

## Rollback

- Revert the changed files listed above.
- Rebuild Vue static assets from reverted source if generated assets are included.
- No production database, OSS, tag, version, or deployment rollback is required.
