# PM Platform Import Draft Hierarchy Gap Summary Report

Date: 2026-07-03

## Baseline

- Production baseline branch: `production/V3/3.0.77`
- Feature branch: `pm-platform/production-3.0.77-sync`
- App baseline: `V3.0.77`

## Scope

Keep conditional accessory evidence gaps visible after template validation when the operator generates an import draft preview for a mid-project takeover workbook.

## Changed Files

- `v2-api/app/services/platform/templates.py`
- `v2-web/src/views/ProjectsView.vue`
- `scripts/verify_platform_import_draft_hierarchy_gap_summary.py`
- `scripts/verify_vue_import_draft_hierarchy_gap_summary.js`
- `docs/superpowers/plans/2026-07-03-import-draft-hierarchy-gap-summary.md`
- `docs/reports/pm-platform-import-draft-hierarchy-gap-summary-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- `v2-api/app/static/vue/` generated frontend build assets

## Behavior

- `create_project_template_import_draft` now copies validation items with code `missing_conditional_field` into `result.hierarchy_gap_items`.
- Import draft `result.summary` now includes `hierarchy_gap_count`.
- The import draft preview card in `/platform-projects` now shows `层级缺口` count and a compact `import-draft-hierarchy-gaps` list after the operator generates an import preview.
- Existing validation report, import batch creation, and work-order task flow remain unchanged.

## Verification

- Red backend guard before implementation: `python scripts\verify_platform_import_draft_hierarchy_gap_summary.py` failed with `[FAIL] draft summary must count conditional hierarchy gaps`.
- Red frontend guard before implementation: `node scripts\verify_vue_import_draft_hierarchy_gap_summary.js` failed with `[FAIL] import draft summary must expose hierarchy gap count`.
- `python scripts\verify_platform_import_draft_hierarchy_gap_summary.py` passed.
- `node scripts\verify_vue_import_draft_hierarchy_gap_summary.js` passed.
- `python scripts\verify_platform_external_completed_hierarchy_validation.py` passed.
- `node scripts\verify_vue_template_validation_hierarchy_panel.js` passed.
- `pnpm --dir v2-web build` passed. Existing warnings remained: VueUse pure annotation comments and large chunks.
- Browser smoke: `http://127.0.0.1:52147/platform-projects` rendered with project rows and no current-port error logs.

## Migration Note

No database schema, permission, production data, OSS, or PostgreSQL migration is introduced. This change extends an existing dry-run import draft response with derived summary data.

## Rollback

Remove `hierarchy_gap_count` and `hierarchy_gap_items` from import draft result construction, remove frontend import draft hierarchy gap rendering and parsing, delete the two new verification scripts and this report, then rebuild frontend static assets.

## Risks

- Consumers that treat import draft `result.summary` as a fixed shape should continue to work because this only adds fields.
- The summary depends on backend validation item code `missing_conditional_field`; if that code changes, backend and frontend guards must be updated together.
