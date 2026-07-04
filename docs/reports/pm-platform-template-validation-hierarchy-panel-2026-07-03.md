# PM Platform Template Validation Hierarchy Panel Report

Date: 2026-07-03

## Baseline

- Production baseline branch: `production/V3/3.0.77`
- Feature branch: `pm-platform/production-3.0.77-sync`
- App baseline: `V3.0.77`

## Scope

Expose backend `missing_conditional_field` warnings in the project template validation dialog as a dedicated operator-facing hierarchy evidence gap panel. This helps mid-project takeover imports explain missing conditional accessory evidence before users read the generic issue table.

## Changed Files

- `v2-web/src/views/ProjectsView.vue`
- `scripts/verify_vue_template_validation_hierarchy_panel.js`
- `docs/superpowers/plans/2026-07-03-template-validation-hierarchy-panel.md`
- `docs/reports/pm-platform-template-validation-hierarchy-panel-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- `v2-api/app/static/vue/` generated frontend build assets

## Behavior

- The validation dialog now computes `hierarchyValidationItems` from validation report items with code `missing_conditional_field`.
- When such items exist, the dialog shows `层级证据缺口` with `条件采集缺失`, row labels, field labels, messages, and current values.
- The original full validation issue table remains unchanged.

## Verification

- Red guard before implementation: `node scripts\verify_vue_template_validation_hierarchy_panel.js` failed with `[FAIL] projects view must compute hierarchy validation items`.
- `node scripts\verify_vue_template_validation_hierarchy_panel.js` passed.
- `python scripts\verify_platform_external_completed_hierarchy_validation.py` passed.
- `node scripts\verify_platform_external_completed_hierarchy_validation_guard.js` passed.
- `node scripts\verify_field_template_hierarchy_hints.js` passed.
- `pnpm --dir v2-web build` passed. Existing warnings remained: VueUse pure annotation comments and large chunks.
- Browser smoke: `http://127.0.0.1:52147/platform-projects` rendered project page, table count was nonzero, and current-port error logs were empty.
- `git diff --check` passed.
- Sensitive path check for `.env`, `data`, `uploads`, `v2-api/data`, and `v2-api/app/static/uploads` returned no changes.

## Migration Note

No database schema, permission, production data, OSS, or PostgreSQL migration is introduced. This is a frontend presentation layer change over an existing backend validation code.

## Rollback

Remove the `hierarchyValidationItems` computed value, `validationIssueRowLabel` helper, validation hierarchy panel markup/styles, the guard script, this report, and regenerate frontend assets from the previous source state.

## Risks

- The panel depends on the backend item code `missing_conditional_field`. If that code changes, the guard should be updated together with the backend contract.
- Full file-upload browser validation was not repeated in this package; behavior is covered by backend validation scripts and the new frontend source guard.
