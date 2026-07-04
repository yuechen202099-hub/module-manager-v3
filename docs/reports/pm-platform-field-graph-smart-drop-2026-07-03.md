# PM Platform Field Graph Smart Drop

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Summary

The field graph designer now has smart drop targets that apply hierarchy semantics while arranging fields:

- `拖到任务核心` sets a custom field as a task detail under the primary task object.
- `拖到主设备更换` sets a field as the main replacement device under the task object.
- `拖到附属设备确认` turns a field into a select/enum replacement confirmation with `更换`, `不更换`, and `待确认` options when needed.
- `拖到条件采集` attaches old/new accessory fields and evidence photos to the nearest replacement-confirmation rule.
- Evidence photos keep the `evidence_photo` relationship when dropped into conditional collection.

This keeps module replacement as accessory-device replacement under one task object, while terminal replacement first models the main terminal replacement and then accessory replacement confirmation.

## Changed Files

- `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- `scripts/verify_vue_field_graph_smart_drop.js`
- `docs/superpowers/plans/2026-07-03-field-graph-smart-drop.md`
- `docs/reports/pm-platform-field-graph-smart-drop-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

Frontend build also regenerated Vue static assets under `v2-api/app/static/vue/`.

## Verification

Commands:

- `node scripts\verify_vue_field_graph_smart_drop.js`
  - Red result before implementation: `[FAIL] FieldGraphDesigner.vue missing smart drop token: type FieldDropIntent`
  - Red result for photo boundary: `[FAIL] FieldGraphDesigner.vue missing smart drop token: if (isEvidenceField(field)) return 'evidence_photo'`
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
- Page identity: title `Module Manager V3.0.77`.
- The dialog rendered `字段关系图`, `拖到任务核心`, `拖到主设备更换`, `拖到附属设备确认`, `拖到条件采集`, `换模块：在任务对象下更换附属设备`, and `换终端：先确认附属设备是否更换`.
- Current-port console filter for `52137` returned no errors or warnings.
- A stale CSS preload error from an older `52131` browser session remains in historical logs and is not from the active `52137` page.

Interaction note:

- The browser automation opened the target dialog and verified the rendered smart-drop panel.
- A coordinate-level drag attempt did not trigger the browser's HTML5 drag/drop event, so this report does not claim browser-automated drag success. The smart-drop wiring is covered by the focused guard script and TypeScript build.

## Risk Notes

- Frontend build regenerated static Vue assets.
- This package changes frontend configuration behavior and visual guidance only.
- It does not execute migrations, change persistence, write PostgreSQL, write OSS, change production data, create tags, deploy, or bump the official production version.
- Manual QA should still try a real mouse drag before PR acceptance because browser coordinate automation could not reliably trigger HTML5 drag/drop.

## Rollback Notes

- Code rollback: revert the changed files listed above.
- Static asset rollback: rebuild from reverted source or restore the previous generated Vue assets.
- Production rollback: no production rollback is needed because no production release, migration, tag, version bump, OSS write, or PostgreSQL write was performed.
