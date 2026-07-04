# Construction Required Collection Gate Plan

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `4c05cc9`

## Objective

Make platform construction submission enforce the configured field hierarchy and conditional required rules.

Draft caching must remain flexible for field crews, but a submitted collection should not enter review when a required construction field, required photo, or conditionally required accessory field/photo is missing.

## Scope

- Validate submitted platform construction collection payloads before saving.
- Preserve cached incomplete drafts.
- Merge imported work-order values with submitted collection values before evaluating `required_when`.
- Check both construction fields and photo slots that are active in the construction panel.
- Cover main-device replacement plus conditional accessory replacement examples, such as terminal replacement with communication module confirmation.
- Do not change database schema, permissions, OSS, PostgreSQL data, production version, tags, or deployment.

## Verification Plan

- `python scripts\verify_platform_construction_required_collection.py`
- `python scripts\verify_platform_review_relation_roles.py`
- `python scripts\verify_pm_platform_team_operating_model.py`
- `git diff --check -- v2-api/app/services/platform/templates.py scripts/verify_platform_construction_required_collection.py docs/superpowers/plans/2026-07-03-construction-required-collection-gate.md docs/reports/pm-platform-construction-required-collection-gate-2026-07-03.md docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

## Migration Notes

No persistence migration. This package tightens backend validation for submitted platform construction collections only.

Projects that configure required or conditionally required construction-panel fields may now block incomplete submissions until field crews provide the configured data.

## Rollback

- Revert `v2-api/app/services/platform/templates.py`.
- Remove `scripts/verify_platform_construction_required_collection.py`.
- Revert this plan, the report, and the team memory update.
- No production rollback is needed because no production deployment, migration, tag, version bump, OSS write, PostgreSQL write, or production data edit occurred.
