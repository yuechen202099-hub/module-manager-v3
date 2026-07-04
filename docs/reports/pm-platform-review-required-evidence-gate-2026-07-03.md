# PM Platform Review Required Evidence Gate

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `4c05cc9`

## Summary

Platform review approval now checks required construction evidence before saving an approved status.

The review page also shows a grouped `审阅证据缺口` for the selected platform work order and disables the `通过` action while required fields or required photos are missing. Reviewers can still return or mark exception so incomplete work can flow back to construction.

## Changed Files

- `v2-api/app/services/platform/templates.py`
- `v2-web/src/views/ReviewView.vue`
- `scripts/verify_platform_review_required_evidence.py`
- `scripts/verify_vue_review_required_evidence_gate.js`
- `docs/superpowers/plans/2026-07-03-review-required-evidence-gate.md`
- `docs/reports/pm-platform-review-required-evidence-gate-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Generated Vue static assets under `v2-api/app/static/vue/` after `pnpm --dir v2-web build`

## Verification

Commands:

- `python scripts\verify_platform_review_required_evidence.py`
  - Red check before implementation: failed because incomplete cached evidence could still be approved.
  - Green check after implementation: `[OK] platform review required evidence is enforced`.
- `python scripts\verify_platform_review_relation_roles.py`
  - Result: `[OK] platform review relation roles are preserved`.
- `node scripts\verify_vue_review_required_evidence_gate.js`
  - Red check before implementation: failed because `reviewEvidenceGapGroups` was missing.
  - Green check after implementation: `[OK] Vue review required evidence gate is wired.`
- `node scripts\verify_vue_review_hierarchy_sections.js`
  - Result: `[OK] Vue review hierarchy sections are wired.`
- `node scripts\verify_vue_platform_review_actions.js`
  - Result: `[OK] Vue task hall exposes platform review actions.`
- `node scripts\verify_vue_review_schema_completeness.js`
  - Result: `[OK] Vue review view checks project schema completeness.`
- `node scripts\verify_vue_review_platform_filters.js`
  - Result: `[OK] Vue review page exposes platform review filters.`
- `pnpm --dir v2-web build`
  - Result: passed after adding bundled Node to `PATH`.
  - Existing VueUse pure-annotation warnings and large chunk warnings remain.

Browser smoke:

- Temporary current-code server was started on `http://127.0.0.1:52144`.
- Static shell rendered `Module Manager V3.0.77` without framework error overlay.
- Target review page verification could not be completed in the browser because the local auth redirect stayed on `/login?redirect=/vue/review?project_id=review-gap-smoke`.
- The temporary server was stopped.
- The visible review-gap behavior is covered by the Vue guard and production build in this package; backend approval behavior is covered by the API guard.

## Risk Notes

- This is a core review rule tightening: evidence-incomplete platform work orders can no longer be approved directly.
- Return and exception actions remain available for incomplete work.
- The backend guard reuses construction required-field/photo rules, including conditional `required_when` accessory evidence.

## Rollback Notes

- Revert `v2-api/app/services/platform/templates.py`.
- Revert `v2-web/src/views/ReviewView.vue`.
- Remove the two new verification scripts.
- Rebuild Vue static assets from reverted source if generated assets are included.
- Revert the documentation entries listed above.
- No production rollback is needed because no production deployment, migration, tag, version bump, OSS write, PostgreSQL write, or production data edit occurred.
