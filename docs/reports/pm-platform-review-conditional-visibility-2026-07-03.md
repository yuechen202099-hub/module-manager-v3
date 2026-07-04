# PM Platform Review Conditional Visibility

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Summary

Platform review now filters conditional accessory fields and photo slots per selected work order before grouping them into hierarchy sections.

This keeps the review view aligned with the product rule:

- Module replacement: replace an accessory device under one task object.
- Terminal replacement: replace the main terminal/device first, then ask whether accessory devices also changed.
- Accessory old/new fields and conditional evidence photos appear only when the work order's confirmation field says the accessory was replaced.

## Changed Files

- `v2-web/src/views/ReviewView.vue`
- `v2-web/src/views/TaskHallView.vue`
- `scripts/verify_vue_review_hierarchy_sections.js`
- `docs/superpowers/plans/2026-07-03-review-conditional-visibility.md`
- `docs/reports/pm-platform-review-conditional-visibility-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

## Verification

Commands:

- `node scripts\verify_vue_review_hierarchy_sections.js`
  - Red result before implementation: `[FAIL] review view must read per-work-order values before conditional filtering`
  - Green result after implementation: `[OK] Vue review hierarchy sections are wired.`
- `node scripts\verify_vue_construction_conditional_visibility.js`
  - Result: `[OK] Vue construction conditional visibility is wired.`
- `node scripts\verify_vue_construction_hierarchy_collection.js`
  - Result: `[OK] Vue construction hierarchy collection is wired.`
- `python scripts\verify_platform_terminal_review_sample.py`
  - Result: `[OK] terminal review sample preserves main-device review hierarchy`
- `pnpm --dir v2-web build`
  - Result: passed.
  - Existing warnings remain for VueUse pure annotations and large chunks.

Browser smoke:

- URL: `http://127.0.0.1:52137/task-hall?project_id=draft-project`
- `TT-TERM-REVIEW-001`: communication module is replaced, so old/new communication module fields and the old-new module photo remain visible.
- `TT-TERM-REVIEW-002`: communication module is not replaced, so old/new communication module fields and the old-new module photo are hidden; SIM old/new fields remain visible.
- The current browser log contained one stale preload error from an older `52131` session, not from the active `52137` verification page.

## Risk Notes

- Frontend build regenerated static Vue assets under `v2-api/app/static/vue`.
- GitHub remote baseline was not refreshed during this continuation because earlier network checks to GitHub failed from this machine. Local recorded baseline remains `origin/production/V3/3.0.77` at `4c05cc9`.
- The change is visibility-only for review panels; it does not remove data from the work order payload.

## Rollback Notes

- Code rollback: revert the changed files listed above.
- Frontend asset rollback: rebuild from reverted source or restore previous generated assets.
- Local demo rollback: no new demo import was created in this package.
- Production rollback: no production rollback is needed because this package did not deploy, migrate, tag, bump version, write OSS, or write PostgreSQL.
