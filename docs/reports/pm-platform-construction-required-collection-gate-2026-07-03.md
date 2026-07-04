# PM Platform Construction Required Collection Gate

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `4c05cc9`

## Summary

Submitted platform construction collections now enforce active required fields and photos.

This keeps the field hierarchy practical: module replacement remains an accessory replacement under one task object, while terminal replacement can require a main replacement device and then conditionally require accessory data only when the crew confirms that an accessory is replaced.

Cached drafts are still allowed to be incomplete so field crews can save partial work.

## Changed Files

- `v2-api/app/services/platform/templates.py`
- `scripts/verify_platform_construction_required_collection.py`
- `docs/superpowers/plans/2026-07-03-construction-required-collection-gate.md`
- `docs/reports/pm-platform-construction-required-collection-gate-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

## Verification

Commands:

- `python scripts\verify_platform_construction_required_collection.py`
  - Result: `[OK] platform construction required collection is enforced`.

- `python scripts\verify_platform_review_relation_roles.py`
  - Result: `[OK] platform review relation roles are preserved`.
- `python scripts\verify_pm_platform_team_operating_model.py`
  - Result: `[OK] PM platform team operating model is locked`.
- `git diff --check -- v2-api/app/services/platform/templates.py scripts/verify_platform_construction_required_collection.py docs/superpowers/plans/2026-07-03-construction-required-collection-gate.md docs/reports/pm-platform-construction-required-collection-gate-2026-07-03.md docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
  - Result: passed with no output.
- Sensitive-path status check for `.env`, `data`, `uploads`, `v2-api/data`, and `v2-api/app/static/uploads`.
  - Result: passed with no output.

## Behavior Covered

- `status=cached` with missing required accessory data is accepted.
- `status=submitted` with communication module confirmation set to replacement is rejected when the new communication module number or old-new module photo is missing.
- `status=submitted` succeeds when the main replacement device, conditional accessory value, and required photos are present.

## Risk Notes

- This is a core business-rule tightening for platform construction submission.
- Projects with required construction-panel fields will now block incomplete submitted payloads.
- The validation only applies to fields and photo slots active in the construction panel, so hidden configuration fields are not accidentally forced during field collection.

## Rollback Notes

- Revert `v2-api/app/services/platform/templates.py`.
- Remove `scripts/verify_platform_construction_required_collection.py`.
- Revert the documentation entries listed above.
- No production rollback is needed because no production deployment, migration, tag, version bump, OSS write, PostgreSQL write, or production data edit occurred.
