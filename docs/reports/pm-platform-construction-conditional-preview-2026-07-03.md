# PM Platform Construction Conditional Preview

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Summary

Platform construction work-order sample cards now filter conditional fields per work order.

Example:

- `TT-TERM-REVIEW-001`: communication module is `更换`, so old/new communication module fields and the old-new module photo remain visible.
- `TT-TERM-REVIEW-002`: communication module is `不更换`, so old/new communication module fields and the old-new module photo are hidden, while SIM replacement fields remain visible.

This makes the construction entry match the configured device hierarchy: accessory follow-up fields appear only after the corresponding accessory confirmation says they are needed.

## Changed Files

- `v2-web/src/views/ConstructionView.vue`
- `scripts/verify_vue_construction_conditional_visibility.js`
- `scripts/seed-platform-terminal-demo.py`
- `scripts/verify_platform_terminal_review_sample.py`
- `docs/superpowers/plans/2026-07-03-construction-conditional-preview.md`
- `docs/reports/pm-platform-construction-conditional-preview-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

## Verification

Commands:

- `node scripts\verify_vue_construction_conditional_visibility.js`
  - Red result before implementation: `[FAIL] ConstructionView.vue missing conditional visibility token: function platformWorkOrderConditionValues`
  - Green result after implementation: `[OK] Vue construction conditional visibility is wired.`
- `node scripts\verify_vue_construction_hierarchy_collection.js`
  - Result: `[OK] Vue construction hierarchy collection is wired.`
- `node scripts\verify_vue_platform_construction_kpi_fields.js`
  - Result: `[OK] Vue construction page preserves platform KPI collection fields.`
- `python scripts\verify_seed_terminal_demo_hierarchy_roles.py`
  - Result: `[OK] terminal demo seed preserves hierarchy relation roles`
- `python scripts\verify_platform_terminal_review_sample.py`
  - First result exposed a real bug: template example values leaked into the no-communication sample.
  - Final result after clearing unspecified sample workbook cells: `[OK] terminal review sample preserves main-device review hierarchy`
- `pnpm --dir v2-web build`
  - Result: passed.
  - Existing warnings remain for VueUse pure annotations and large chunks.

Browser smoke:

- URL: `http://127.0.0.1:52137/construction?project_id=draft-project`
- Local no-communication sample was imported through the running local service.
- DOM verification found:
  - `sampleCount: 2`
  - `TT-TERM-REVIEW-002`
  - `通讯模块是否更换 不更换`
  - `SIM卡是否更换 更换`
  - old/new communication module fields hidden
  - old-new module photo hidden
  - old/new SIM fields visible
- Current `52137` console check found no relevant errors.

## Risk Notes

- GitHub remote baseline could not be refreshed during this package because GitHub network requests failed from the machine. Local recorded baseline remains `origin/production/V3/3.0.77` at `4c05cc9`.
- The local demo state now contains a second terminal external-completed sample for conditional-preview validation.
- Frontend build regenerated static Vue assets under `v2-api/app/static/vue`.

## Rollback Notes

- Code rollback: revert the changed files listed above.
- Local demo rollback: remove or roll back the import task for `TT-TERM-REVIEW-002` if a clean demo state is needed.
- Frontend asset rollback: rebuild from reverted source or restore previous generated assets.
- Production rollback: no production rollback needed because this package did not deploy, migrate, tag, bump version, write OSS, or write PostgreSQL.
