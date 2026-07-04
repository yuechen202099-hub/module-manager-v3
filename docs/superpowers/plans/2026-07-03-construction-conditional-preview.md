# Construction Conditional Preview Plan

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Objective

Make platform construction work-order previews respect the configured accessory confirmation rules.

When a terminal replacement work order says an accessory device is not replaced, the preview should not show follow-up collection fields for that accessory. This keeps the site operator focused on the fields that actually apply to the current work order.

## Scope

Frontend:

- Keep the existing schema-level construction section preview unchanged.
- For each work-order sample card, merge the work order's imported values, collected values, KPI values, primary value, and aggregate value.
- Filter construction fields with `isFieldConditionActiveForValues`.
- Filter photo slots with `isPhotoSlotConditionActiveForValues`.
- Show per-order photo slot status only for slots active under that work order's confirmation values.

Local demo:

- Add a second terminal replacement external-completed sample:
  - `TT-TERM-REVIEW-002`
  - communication module: not replaced
  - SIM card: replaced
- Ensure blank fields in a generated sample workbook are explicitly cleared so template example values do not leak into local samples.

Verification:

- Strengthen `scripts/verify_vue_construction_conditional_visibility.js` first and observe it fail.
- Run construction hierarchy, KPI, terminal sample, and seed hierarchy guards.
- Build the frontend.
- Browser-smoke `/construction?project_id=draft-project` and verify both positive and negative accessory confirmation cases.

## Data Safety

- Local demo seeding uses development JSON state only.
- No production `.env`, production data, uploads, OSS object, PostgreSQL row, version number, tag, or deployment path is touched.
- The package does not change submission or review approval semantics.

## Rollback

- Revert `v2-web/src/views/ConstructionView.vue`.
- Revert `scripts/verify_vue_construction_conditional_visibility.js`.
- Revert terminal demo seed/test updates if the second sample is not desired.
- Rebuild Vue static assets from the reverted source.
- No production rollback is needed because no production deployment, migration, tag, version bump, OSS write, or PostgreSQL write was performed.
