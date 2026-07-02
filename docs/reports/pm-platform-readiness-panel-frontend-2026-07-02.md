# PM Platform Readiness Panel Frontend Report

Date: 2026-07-02

## Scope

- Add a frontend consumer for `GET /projects/{project_id}/readiness`.
- Show a server-backed `上线检查` panel inside the existing `/platform-projects` field configuration dialog.
- Keep row operations compact: no new table action button was added.
- Keep the package read-only from the frontend perspective: no database migration, no PostgreSQL write path, no production data edit, no version tag, and no deployment.

## Changed Files

- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/views/ProjectsView.vue`
- `scripts/verify_vue_project_readiness_panel.js`
- `docs/superpowers/plans/2026-07-02-project-readiness-panel-frontend.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

## Behavior

- Field configuration now automatically loads backend readiness for the selected project.
- The dialog shows:
  - readiness status: `可接入` or `需补齐`,
  - pass/fail summary,
  - individual checks grouped by field configuration, site evidence, KPI, and workflow,
  - operator-language next actions.
- Saving field configuration refreshes the cached readiness result for the project.

## Verification

- RED guard:
  - `node scripts\verify_vue_project_readiness_panel.js`
  - Result before implementation: failed with `types.ts missing readiness token: ProjectReadinessCheckStatus`.
- Guard checks after implementation:
  - `node scripts\verify_vue_project_readiness_panel.js`
  - Result: `[OK] Project readiness panel is wired to the frontend.`
  - `node scripts\verify_vue_project_field_graph_template_actions.js`
  - Result: `[OK] Field graph template actions are wired.`
  - `node scripts\verify_vue_project_workflow_module_toggles.js`
  - Result: `[OK] Vue workflow editor exposes module-level enable/disable controls.`
- Backend readiness guard:
  - `.\.venv\Scripts\python.exe scripts\verify_platform_project_readiness.py`
  - Result: `[OK] platform project readiness is consistent`
  - Note: Starlette emitted the existing `TestClient` deprecation warning.
- Frontend build:
  - `pnpm --dir v2-web build` with bundled Node/Pnpm on PATH
  - Result: build exited 0, `1894 modules transformed`.
  - Note: existing Rollup annotation and chunk-size warnings remain.
- Browser smoke:
  - Local server: `http://127.0.0.1:52131/platform-projects`
  - Opened existing `字段配置`.
  - Verified `.readiness-server-panel` text includes `上线检查`, `需补齐`, `通过 6/10 项`, and next action hints.
- Sensitive path check:
  - `.env`, `data`, `v2-api/data`, `v2-api/app/static/uploads`, and `uploads` had no pending Git changes.
  - PR/patch handoff guard also checks changed paths for live OSS/PostgreSQL, SQL, dump, and key-like artifacts.

## Migration And Rollback

- Migration: none.
- Rollback: revert the readiness frontend types, service mapping, `ProjectsView.vue` panel, guard script, generated Vue static assets, and documentation updates.
