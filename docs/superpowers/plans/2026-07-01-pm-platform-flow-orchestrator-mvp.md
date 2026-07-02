# PM Platform Flow Orchestrator MVP Implementation Plan

This plan is for an agentic worker running in the module-manager-v3 repository. Follow it step by step. Do not skip verification. Do not touch production data.

## Goal

Implement the first usable version of a configurable project workflow editor for the operations engineering platform.

The user need is practical:

- Each project type has a similar but not identical process.
- Users should be able to decide which functions are used in a project.
- Users should be able to adjust process order visually.
- The workflow must support later binding to field schemas, import templates, construction collection, review, rework, exception handling, and delivery archive.

The MVP should create the foundation without pretending the whole automation engine is finished.

## Baseline And Branch

- Upstream repository: `https://github.com/yuechen202099-hub/module-manager-v3`
- Production baseline branch: `production/V3/3.0.71`
- Platform feature branch pattern: `pm-platform/flow-orchestrator`
- Current local development must not change official production version numbers, create tags, or publish a server.

## Safety Boundaries

- Do not modify production `.env`, `data`, `uploads`, OSS, or PostgreSQL data.
- Do not commit secrets, real customer data, uploaded images, database dumps, or build archives.
- Keep local demo data clearly separated from production data.
- If database schema is changed, add migration and rollback notes before handoff.
- For this MVP, prefer storing workflow configuration in the existing project platform configuration layer before introducing a database migration.

## Architecture Direction

Add a per-project workflow definition with this shape:

```json
{
  "version": 1,
  "nodes": [
    {
      "id": "project_setup",
      "type": "setup",
      "label": "项目建立",
      "enabled": true,
      "required": true,
      "order": 10,
      "moduleId": "project_setup",
      "config": {}
    }
  ],
  "edges": [
    {
      "id": "project_setup__field_schema",
      "source": "project_setup",
      "target": "field_schema",
      "label": "下一步"
    }
  ],
  "updatedAt": "2026-07-01T00:00:00+08:00",
  "updatedBy": "local-admin"
}
```

Initial node catalog:

- `project_setup`: 项目建立.
- `field_schema`: 字段配置.
- `template_import`: 模板导入.
- `work_order_plan`: 工单计划.
- `construction_collection`: 现场施工采集.
- `review`: 审阅.
- `rework`: 返工.
- `exception`: 异常处理.
- `delivery_archive`: 交付归档.
- `delivery_export`: 交付导出.

The MVP must support:

- Read project workflow.
- Save project workflow.
- Reset to default workflow.
- Enable or disable optional nodes.
- Reorder enabled nodes.
- Render a visual flow in the frontend.
- Keep existing project board behavior compatible when no workflow exists.

## Agent Work Packages

### Package A: Backend Workflow API

Owner: Backend Flow Engine Agent

Allowed files:

- `v2-api/app/services/platform/workflow.py`
- Existing project API route files that expose `/projects/{project_id}` behavior.
- Backend tests under `v2-api/tests/`.

Avoid editing:

- production deployment files
- version files
- unrelated import/export logic

Implementation steps:

1. Add a workflow service with default catalog helpers.
2. Implement `get_project_workflow(project_id)`.
3. Implement `save_project_workflow(project_id, workflow_payload, actor)`.
4. Implement `reset_project_workflow(project_id, actor)`.
5. Add API routes:
   - `GET /projects/{project_id}/workflow`
   - `PUT /projects/{project_id}/workflow`
   - `POST /projects/{project_id}/workflow/reset`
6. Preserve compatibility for existing project data. If a project has no workflow, return the default workflow.

Expected backend test coverage:

- Default workflow contains the required nodes.
- Optional nodes can be disabled and saved.
- Reordered nodes are returned in saved order.
- Reset returns the default workflow again.
- Unknown project returns the existing project-not-found behavior.

Suggested verification:

```powershell
python -m pytest v2-api/tests/test_api.py -k "workflow or project_modules" -q
```

### Package B: Frontend API And Types

Owner: Frontend Workflow Canvas Agent

Allowed files:

- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- workflow-specific frontend component files

Avoid editing:

- generated static assets by hand
- unrelated dashboard components

Implementation steps:

1. Add `ProjectWorkflow`, `ProjectWorkflowNode`, and `ProjectWorkflowEdge` types.
2. Add API functions:
   - `fetchProjectWorkflow(projectId)`
   - `saveProjectWorkflow(projectId, payload)`
   - `resetProjectWorkflow(projectId)`
3. Keep the API names explicit and platform-oriented.
4. Ensure missing workflow responses still render a default state.

Suggested verification:

```powershell
node scripts/verify-client-release.py --help
pnpm --dir v2-web build
```

### Package C: Frontend Workflow Editor UI

Owner: Frontend Workflow Canvas Agent

Allowed files:

- `v2-web/src/components/project-workflow/WorkflowEditor.vue`
- `v2-web/src/components/project-workflow/WorkflowNodeConfigPanel.vue`
- `v2-web/src/views/ProjectsView.vue` only for integration entry points

Avoid editing:

- existing field configuration UI unless required for the workflow entry point
- broad layout refactors

MVP UI behavior:

- Add a clear entry point named `流程配置`.
- Show a visual process lane with connected nodes.
- Let users drag or move nodes to change order.
- Let users enable or disable optional nodes.
- Keep required nodes locked.
- Show a side panel for the selected node.
- Save, reset, and close actions should be obvious and limited.

Design direction:

- This is an operations tool, not a marketing page.
- Use dense but calm layout.
- Avoid excessive action buttons; use one primary save action, one reset action, and compact node controls.
- Do not add in-app instructional paragraphs. Use labels, tooltips, and direct controls.

Suggested browser checks:

- Open `/platform-projects`.
- Open a project.
- Click `流程配置`.
- Reorder at least one optional node.
- Disable one optional node.
- Save.
- Refresh and confirm the saved order remains.

### Package D: Verification Guards

Owner: QA And Verification Agent

Allowed files:

- `scripts/verify_vue_project_workflow_editor.js`
- backend test files
- focused verification notes

Implementation steps:

1. Add a frontend guard that checks for:
   - workflow editor component exists
   - `流程配置`
   - node catalog tokens
   - save/reset API calls
   - drag or move controls
2. Add or extend backend tests for workflow endpoints.
3. Run existing platform guard scripts that are relevant to project configuration.

Expected verification set:

```powershell
node scripts/verify_vue_project_workflow_editor.js
node scripts/verify_vue_project_type_presets.js
node scripts/verify_vue_work_item_schema_config.js
python -m pytest v2-api/tests/test_api.py -k "workflow or project_modules or work_order_status" -q
pnpm --dir v2-web build
```

### Package E: Operations Handoff

Owner: Ops And Release Agent

Allowed files:

- docs handoff reports
- migration and rollback notes

Implementation steps:

1. Record baseline commit.
2. Record changed files.
3. Record functional behavior.
4. Record verification commands and results.
5. Record risks:
   - workflow config storage is MVP-level
   - no production automation is triggered yet
   - existing projects must continue to use defaults unless configured
6. Record rollback:
   - revert workflow API files
   - revert frontend workflow editor files
   - keep existing project behavior through default workflow fallback

## Integration Sequence

1. Backend service and tests.
2. Backend API routes.
3. Frontend API types and service methods.
4. Frontend workflow editor component.
5. Project list/detail entry point.
6. Verification guard script.
7. Frontend build.
8. Browser verification.
9. Handoff notes.

## First Implementation Checkpoint

Stop for review after these are true:

- `GET /projects/{project_id}/workflow` works locally.
- The frontend can open a workflow editor for one project.
- A user can reorder or disable nodes and save.
- Refresh preserves the saved workflow.
- Existing replacement-project board still opens.

At that checkpoint, Codex Integrator reviews the implementation before connecting workflow nodes to deeper automation rules.

## Future Work After MVP

After the MVP is accepted:

- Bind workflow nodes to field schema requirements.
- Let templates declare which workflow node they feed.
- Let construction collection submit against workflow node requirements.
- Let review and rework transitions update workflow progress.
- Add workflow-driven dashboard cards.
- Add per-project role permissions for who can change workflow.
- Add workflow history and audit records.

