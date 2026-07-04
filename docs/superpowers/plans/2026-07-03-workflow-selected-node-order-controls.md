# Workflow Selected Node Order Controls Plan

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Objective

Make workflow ordering easier to operate from the visual editor side panel.

When an operator selects a workflow node, the right-side configuration panel should show:

- current position,
- previous node,
- next node,
- up/down controls for the selected node.

## Scope

- Add selected-node order computed state to `WorkflowEditor.vue`.
- Add right-panel up/down controls that call existing reorder behavior.
- Keep the existing lane controls and drag/drop behavior.
- Do not change workflow API contracts, database schema, production version, tags, deployment, or production data.

## Verification Plan

- `node scripts\verify_vue_project_workflow_editor.js`
- `pnpm --dir v2-web build`
- Browser smoke: open `/platform-projects`, open `更换终端` workflow configuration, select `字段配置`, click right-panel `上移`, and confirm it becomes `第 1 / 7 步` with `项目建立` as the next node.

## Migration Notes

No migration. This is a frontend workflow-editor interaction improvement only.

## Rollback

- Revert `v2-web/src/components/project-workflow/WorkflowEditor.vue`.
- Revert workflow-editor guard additions in `scripts/verify_vue_project_workflow_editor.js`.
- Rebuild Vue static assets from reverted source if generated assets are included.
- No production rollback is needed because no deployment, tag, version bump, OSS write, PostgreSQL write, or production data edit occurred.
