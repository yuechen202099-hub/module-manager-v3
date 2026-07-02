# Project Import Wizard Guidance Plan

> For future agents: this package makes template import choices and post-import next actions easier for non-technical operators to understand.

**Goal:** Operators should know which template to use and what to do after each import stage without reading backend terminology.

**Product rule:** The template is for bringing a running or externally completed project into the platform. It is not a separate construction collection template.

## Task 1: Frontend Guard

**Files:**

- Add: `scripts/verify_vue_project_import_wizard_guidance.js`

- [x] Require the project page to explain `initial_work_orders` and `external_completed`.
- [x] Require the import dialog to show guided stages: template validation, preview, batch confirmation, work-order planning, and platform access.
- [x] Require a next-action hint that points users to construction collection or review workbench.
- [x] Verify the guard fails before implementation and passes after implementation.

## Task 2: Project Import Guidance UI

**Files:**

- Modify: `v2-web/src/views/ProjectsView.vue`

- [x] Add two compact template usage cards above the project list.
- [x] Keep template actions consolidated under the existing row dropdown.
- [x] Add import wizard step cards inside the validation dialog.
- [x] Add a dynamic next-action hint that follows the current import state.

## Verification

Run:

```powershell
node scripts\verify_vue_project_import_wizard_guidance.js
node scripts\verify_vue_project_import_wizard_actions.js
node scripts\verify_vue_project_list_fast_overview.js
node scripts\verify_vue_project_workflow_status.js
pnpm --dir v2-web build
```

Observed result on 2026-07-01:

- Import wizard guidance guard: passed.
- Import wizard action guard: passed.
- Project list fast overview guard: passed.
- Project workflow status guard: passed.
- Frontend build: passed with existing Rollup pure-comment and chunk-size warnings.
- Production baseline check: passed.
- Sensitive path check for `.env`, `data`, `v2-api/data`, `v2-api/app/static/uploads`, and `uploads`: passed with no reported changes.
- Local server restart on port `52131`: passed.
- Browser smoke:
  - `/platform-projects` shows `初始接入模板`, `系统外已完成模板`, `运行到一半的项目接入平台`, and `系统外已经完成，只需要接入审阅和归档`.
  - The same page shows route hints `导入字段 -> 施工采集 -> 审阅归档` and `已有结果 -> 审阅工作台 -> 交付归档`.
  - Browser console check: no error or warning logs observed during the smoke check.

## Migration And Rollback Notes

- No database migration is introduced.
- No backend contract change is introduced.
- Rollback can remove `scripts/verify_vue_project_import_wizard_guidance.js` and the import guidance additions in `ProjectsView.vue`.
- No production data, OSS object, upload file, or database row is modified.
