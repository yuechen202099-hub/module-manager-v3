# PM Platform Field Graph Relationship Lines

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Summary

The project field graph now makes hierarchy lines explicit:

- `平行核心字段`: terminal number, address, region, manufacturer, and other non-aggregate task-core fields sit in the same task-core layer.
- `隶属任务对象`: main device, old device, accessory confirmation, new accessory, and evidence fields belong under the task object.
- `条件触发`: old/new accessory values and conditional photos are shown as triggered by replacement-confirmation fields.

The graph also shows a relationship summary for core peers, main-device replacement, accessory confirmation, and conditional collection counts.

## Changed Files

- `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- `scripts/verify_vue_field_graph_relationship_lines.js`
- `docs/superpowers/plans/2026-07-03-field-graph-relationship-lines.md`
- `docs/reports/pm-platform-field-graph-relationship-lines-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

## Verification

Commands:

- `node scripts\verify_vue_field_graph_relationship_lines.js`
  - Red result before implementation: `[FAIL] FieldGraphDesigner.vue missing relationship-line token: labelX: number`
  - Green result after implementation: `[OK] Vue field graph relationship lines are visible.`
- `node scripts\verify_vue_project_field_graph_designer.js`
  - Result: `[OK] Vue project field graph designer is wired.`
- `node scripts\verify_vue_device_hierarchy_config.js`
  - Result: `[OK] Vue device hierarchy configuration is represented.`
- `node scripts\verify_vue_field_graph_conditional_required_config.js`
  - Result: `[OK] Vue field graph conditional required config is wired.`
- `node scripts\verify_vue_work_item_schema_config.js`
  - Result: `[OK] Vue project creation configures work item schema fields.`
- `pnpm --dir v2-web build`
  - Result: passed.
  - Existing warnings remain for VueUse pure annotations and large chunks.

Browser smoke:

- URL: `http://127.0.0.1:52137/platform-projects`
- Opened `更换终端` -> `字段配置`.
- Fresh reload after build showed:
  - `connectorLabelCount: 21`
  - `legendCount: 3`
  - `summaryCount: 4`
  - visible text for `平行核心字段`, `隶属任务对象`, `条件触发`, and `条件采集`.
- Console error list still contains one stale preload error from an older `52131` session, not the active `52137` verification.

## Risk Notes

- Frontend build regenerated static Vue assets under `v2-api/app/static/vue`.
- The package changes visualization only. It does not change saved field schema semantics, import templates, construction payloads, or review rules.
- The local branch still contains broader WIP and generated assets from earlier platform packages.

## Rollback Notes

- Code rollback: revert the changed files listed above.
- Frontend asset rollback: rebuild from reverted source or restore previous generated assets.
- Production rollback: no production rollback is needed because this package did not deploy, migrate, tag, bump version, write OSS, or write PostgreSQL.
