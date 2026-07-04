# PM Platform Review Hierarchy Gap Follow-up

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Production baseline: `production/V3/3.0.77`
Baseline commit: `4c05cc9`

## Summary

External-completed takeover imports now carry triggered device-hierarchy evidence gaps into the review workbench.

This keeps the hierarchy clear:

- module replacement stays modeled as accessory-device replacement under one task object;
- terminal replacement stays modeled as main-device replacement plus accessory replacement confirmation;
- when an accessory confirmation says replacement is needed, missing old/new accessory values or required photos remain visible as `导入层级缺口` during review.

## Changed Files

- `v2-api/app/services/platform/templates.py`
- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/views/ReviewView.vue`
- `scripts/verify_platform_review_hierarchy_gap_followup.py`
- `scripts/verify_vue_review_hierarchy_gap_followup.js`
- `docs/superpowers/plans/2026-07-03-review-hierarchy-gap-followup.md`
- `docs/reports/pm-platform-review-hierarchy-gap-followup-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Generated Vue static assets under `v2-api/app/static/vue/`

## Behavior

- Import work-order execution preserves `missing_conditional_field` warnings from preview rows as `review_hierarchy_gap_items` on locally created platform work orders.
- Review payloads expose sanitized `review_hierarchy_gap_items`.
- The frontend maps them to `reviewHierarchyGapItems`.
- `ReviewView.vue` adds them to the existing evidence gap gate as `导入层级缺口`, so approval remains blocked while imported hierarchy evidence is incomplete.

## Verification

- `python scripts\verify_platform_review_hierarchy_gap_followup.py` passed.
- `node scripts\verify_vue_review_hierarchy_gap_followup.js` passed.
- `python scripts\verify_platform_import_draft_hierarchy_gap_summary.py` passed.
- `python scripts\verify_platform_external_completed_hierarchy_validation.py` passed.
- `python scripts\verify_platform_review_required_evidence.py` passed.
- `node scripts\verify_vue_review_required_evidence_gate.js` passed.
- `node scripts\verify_vue_review_hierarchy_sections.js` passed.
- `node scripts\verify_vue_review_hierarchy_intent_labels.js` passed.
- `pnpm --dir v2-web build` passed after prepending the bundled Node runtime to PATH. Existing VueUse annotation and large chunk warnings remain.
- Browser smoke on `http://127.0.0.1:52147/app?page=review/group-001` passed: the review page rendered `审阅信息`, `资料完整性`, and `照片分类`; no local `52147` app errors were reported.

## Risk

Low to medium. The package changes import execution payload shape and review UI gating, but it does not change official version numbers, tags, deployment, PostgreSQL, OSS, production data, permissions, or migrations.

The new review gap items are derived only from existing `missing_conditional_field` warnings, so ordinary validation warnings do not become review blockers.

## Rollback

Revert the files listed above and rebuild Vue static assets from the reverted frontend source. No database, OSS, upload, production data, tag, or server rollback is required because this package was local feature-branch work only.
