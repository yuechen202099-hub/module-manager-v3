# PM Platform Field Graph Aggregate Guard

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` at `4c05cc92a71e08a7eb5da6a25cef654271b4cfc5`

## Summary

This package moves the single-active-aggregate rule into the graphical field designer.

- The field graph now shows a `聚合口径` readiness card.
- The card explains that station area, region, or manufacturer are alternative aggregation modes and only one can be active.
- Custom child fields no longer offer `aggregate` as a relation role.
- Draft project creation and draft schema save now run aggregate validation before sending the payload to the backend.

## Files Changed

- `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- `v2-web/src/views/ProjectsView.vue`
- `scripts/verify_vue_field_graph_aggregate_guard.js`
- `docs/superpowers/plans/2026-07-03-field-graph-aggregate-guard.md`
- `docs/reports/pm-platform-field-graph-aggregate-guard-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- frontend build output under `v2-api/app/static/vue`

## Verification

- Red first:
  - `node scripts/verify_vue_field_graph_aggregate_guard.js` failed before implementation because the designer did not compute aggregate guard issues.
- Green:
  - `node scripts/verify_vue_field_graph_aggregate_guard.js`
  - `node scripts/verify_vue_field_graph_hierarchy_save_gate.js`
  - `node scripts/verify_vue_field_graph_backend_readiness_echo.js`
  - `node scripts/verify_vue_project_field_graph_designer.js`
  - `node scripts/verify_vue_device_replacement_hierarchy_mode.js`
  - `pnpm --dir v2-web build`
  - Browser smoke at `/platform-projects`: opened `新建项目`, confirmed the field graph renders `聚合口径` and the one-active-aggregate explanation.

## Risk

Low. This is a frontend guard and guidance package. It does not change production data, backend persistence, database schema, permissions, OSS objects, official version numbers, tags, or deployment.

## Rollback

Rollback is code-only:

1. Remove the aggregate guard verifier.
2. Revert the FieldGraphDesigner aggregate readiness card and role-option filtering.
3. Revert the ProjectsView aggregate save validation.
4. Rebuild frontend static assets from the previous code state if generated assets were included.
