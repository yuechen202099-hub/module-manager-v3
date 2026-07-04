# Review Required Evidence Gate Plan

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `4c05cc9`

## Objective

Make platform review refuse approval when required construction evidence is still missing.

The construction page already shows submission gaps, and the backend rejects incomplete submitted collection payloads. This package closes the review loop so cached or externally connected incomplete work orders cannot be approved without required fields and photos.

## Scope

- Add a backend review approval guard for required construction fields and photo slots.
- Preserve return and exception review actions even when evidence is incomplete.
- Add a visible review-side evidence gap summary for selected platform work orders.
- Disable platform approval while required review evidence gaps remain.
- Add focused backend and Vue guard scripts.
- Do not change database schema, permissions, import/export contracts, OSS, PostgreSQL data, production version, tags, or deployment.

## Verification Plan

- `python scripts\verify_platform_review_required_evidence.py`
- `python scripts\verify_platform_review_relation_roles.py`
- `node scripts\verify_vue_review_required_evidence_gate.js`
- `node scripts\verify_vue_review_hierarchy_sections.js`
- `node scripts\verify_vue_platform_review_actions.js`
- `node scripts\verify_vue_review_schema_completeness.js`
- `node scripts\verify_vue_review_platform_filters.js`
- `pnpm --dir v2-web build`

## Migration Notes

No persistence migration. This package tightens review approval behavior and adds frontend review feedback only.

## Rollback

- Revert `v2-api/app/services/platform/templates.py`.
- Revert `v2-web/src/views/ReviewView.vue`.
- Remove `scripts/verify_platform_review_required_evidence.py`.
- Remove `scripts/verify_vue_review_required_evidence_gate.js`.
- Rebuild Vue static assets from reverted source if generated assets are included.
- Revert this plan, the report, and the team memory update.
- No production rollback is needed because no production deployment, migration, tag, version bump, OSS write, PostgreSQL write, or production data edit occurred.
