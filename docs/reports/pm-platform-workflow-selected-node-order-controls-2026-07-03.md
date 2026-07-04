# PM Platform Workflow Selected Node Order Controls

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Summary

The workflow editor now lets operators adjust the selected node order from the right-side node configuration panel.

The panel shows the selected node's current position, previous node, next node, and up/down controls. This helps tablet users adjust a project-specific process without relying only on the small lane buttons.

## Changed Files

- `v2-web/src/components/project-workflow/WorkflowEditor.vue`
- `scripts/verify_vue_project_workflow_editor.js`
- `docs/superpowers/plans/2026-07-03-workflow-selected-node-order-controls.md`
- `docs/reports/pm-platform-workflow-selected-node-order-controls-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

## Verification

Commands:

- `node scripts\verify_vue_project_workflow_editor.js`
  - Result: `[OK] Vue project workflow editor entry and component are wired.`
- `pnpm --dir v2-web build`
  - Result: passed. Existing VueUse annotation and large chunk warnings remain.

Browser smoke:

- URL: `http://127.0.0.1:52137/platform-projects`
- Opened `更换终端` -> `流程配置`.
- Selected `字段配置`.
- Before interaction: right panel showed `第 2 / 7 步`, previous node `项目建立`, next node `现场施工采集`.
- Clicked right-panel `上移`.
- After interaction: right panel showed `第 1 / 7 步`; workflow lane began with `字段配置`, then `项目建立`, then `现场施工采集`.
- The workflow was not saved.
- Current `52137` console check found no relevant errors or warnings.

## Risk Notes

- This package changes only frontend draft editing controls.
- It does not change workflow persistence, workflow defaults, transition rules, permissions, database schema, OSS, PostgreSQL, deployment, tags, or production version numbers.

## Rollback Notes

- Revert the files listed above.
- Rebuild Vue static assets from reverted source if generated assets are included.
- No production rollback is needed because no production deployment, migration, tag, version bump, OSS write, PostgreSQL write, or production data edit occurred.
