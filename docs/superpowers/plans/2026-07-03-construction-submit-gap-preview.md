# Construction Submit Gap Preview Plan

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `4c05cc9`

## Objective

Move the platform construction submission gate closer to the field crew.

The backend now rejects missing active required collection data. This package makes the construction page show the same submission gap before the crew presses submit, grouping missing fields, missing photos, and missing required KPI inputs in one visible warning.

## Scope

- Add a frontend submit-gap guard for platform construction collection.
- Group missing required construction fields, photos, and KPI inputs.
- Keep draft saving available even when submit is blocked.
- Disable platform final submit from both inline and drawer construction forms while gaps remain.
- Add a focused Vue guard script and run existing construction guards.
- Do not change database schema, permissions, backend API behavior, OSS, PostgreSQL data, production version, tags, or deployment.

## Verification Plan

- `node scripts\verify_vue_construction_submit_gap_preview.js`
- `node scripts\verify_vue_construction_checklist_consumption.js`
- `node scripts\verify_vue_platform_construction_kpi_fields.js`
- `node scripts\verify_vue_construction_conditional_visibility.js`
- `pnpm --dir v2-web build`
- Browser smoke on a temporary local port with seeded demo data.

## Migration Notes

No migration. This is a frontend validation and operator-feedback package.

## Rollback

- Revert `v2-web/src/views/ConstructionView.vue`.
- Remove `scripts/verify_vue_construction_submit_gap_preview.js`.
- Rebuild Vue static assets from reverted source if generated assets are included.
- Revert this plan, the report, and the team memory update.
- No production rollback is needed because no production deployment, migration, tag, version bump, OSS write, PostgreSQL write, or production data edit occurred.
