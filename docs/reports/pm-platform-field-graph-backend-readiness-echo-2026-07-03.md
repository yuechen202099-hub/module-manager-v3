# PM Platform Field Graph Backend Readiness Echo Report

Date: 2026-07-03

## Baseline

- Branch: `pm-platform/production-3.0.77-sync`
- Production base: `production/V3/3.0.77`
- Scope: frontend field graph readiness echo and verification guard only.

## What Changed

- Added a backend readiness prop to `FieldGraphDesigner.vue` so saved project field configuration can display the backend `device_hierarchy` check.
- Rendered `后端上线检查回显` for `设备更换层级` inside the graphical field configuration panel.
- Mapped backend evidence keys into operator-facing issues:
  - `missing_parent_keys`
  - `missing_confirmation_keys`
  - `invalid_conditional_keys`
  - `unconditional_child_keys`
  - `confirmation_without_child_keys`
  - `missing_main_accessory_confirmation`
- Highlighted mind-map nodes with `backend-issue-node` when backend evidence points to a specific field key.
- Wired `ProjectsView.vue` to pass the saved project's `device_hierarchy` readiness check into the schema dialog field graph.
- Added `scripts/verify_vue_field_graph_backend_readiness_echo.js` as a regression guard.

## Requirement Mapping

- Module replacement remains represented as one task object with accessory device replacement below it.
- Terminal replacement remains represented as one task object with main device replacement first, then accessory replacement confirmation for communication modules, SIM cards, and follow-up evidence.
- Backend readiness is treated as the authority for saved configurations, while local graph cards still guide draft editing before save.

## Verification

Passed:

```powershell
node scripts\verify_vue_field_graph_backend_readiness_echo.js
node scripts\verify_vue_field_graph_hierarchy_save_gate.js
node scripts\verify_vue_device_hierarchy_config.js
python scripts\verify_platform_project_readiness.py
python scripts\verify_pm_platform_team_operating_model.py
pnpm --dir v2-web build
```

Browser smoke:

- Opened `http://127.0.0.1:52147/platform-projects`.
- Opened `字段配置：更换终端`.
- Verified one `.field-backend-readiness-panel` with text `后端上线检查回显`, `设备更换层级`, and `后端已通过`.
- The saved configuration had zero backend issue nodes, which matches the backend pass state for `device_hierarchy`.

Build warnings retained from the existing project:

- VueUse pure annotation warning from Rollup.
- Large chunk size warning.

## Data And Migration

- No database schema change.
- No production data change.
- No OSS, PostgreSQL, upload, or `.env` changes.
- No production version, tag, release, or deploy action.

## Risks

- The backend echo appears only for saved projects with loaded readiness data; newly created draft configuration still uses local graph readiness cards until saved.
- Failed backend evidence is guarded by source-level verification; current local sample project showed a pass state in browser smoke.

## Rollback

Revert these files:

- `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- `v2-web/src/views/ProjectsView.vue`
- `scripts/verify_vue_field_graph_backend_readiness_echo.js`
- `docs/superpowers/plans/2026-07-03-field-graph-backend-readiness-echo.md`
- `docs/reports/pm-platform-field-graph-backend-readiness-echo-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

Then rebuild frontend with:

```powershell
pnpm --dir v2-web build
```
