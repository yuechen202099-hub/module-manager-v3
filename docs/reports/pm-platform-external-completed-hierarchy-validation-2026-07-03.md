# PM Platform External Completed Hierarchy Validation Report

Date: 2026-07-03

## Baseline

- Branch: `pm-platform/production-3.0.77-sync`
- Production base: `production/V3/3.0.77`
- Scope: backend template validation and verification scripts only.

## What Changed

- Added conditional hierarchy validation for `external_completed` templates.
- When a row has a confirmation field matching `required_when.equals`, blank conditional child fields now generate warning items with code `missing_conditional_field`.
- The validation remains non-blocking: missing conditional evidence produces `warning`, not `failed`, so system-external completed projects can still be connected and reviewed.
- Added Python behavior verification and a source guard:
  - `scripts/verify_platform_external_completed_hierarchy_validation.py`
  - `scripts/verify_platform_external_completed_hierarchy_validation_guard.js`

## Requirement Mapping

- If the uploaded completed template says a communication module was replaced, the report now warns when old module, new module, or photo evidence is missing.
- If the uploaded row says the accessory was not replaced, conditional child fields remain optional and no conditional warning is emitted.
- Later review-stage hard evidence checks remain unchanged.

## Verification

Passed:

```powershell
python scripts\verify_platform_external_completed_hierarchy_validation.py
node scripts\verify_platform_external_completed_hierarchy_validation_guard.js
python scripts\verify_platform_line_loss_template_contract.py
python scripts\verify_platform_review_required_evidence.py
python scripts\verify_platform_review_relation_roles.py
pnpm --dir v2-web build
git diff --check
git status --short -- .env data uploads v2-api/data v2-api/app/static/uploads
```

Build warnings retained from the existing project:

- VueUse pure annotation warning from Rollup.
- Large chunk size warning.

## Data And Migration

- No database schema change.
- No production data change.
- No OSS, PostgreSQL, upload, or `.env` changes.
- No production version, tag, release, or deploy action.

## Risks

- This package adds warnings only; it does not block imperfect external-completed uploads.
- Current row-level validation checks fields present in the template headers or known by schema. It does not parse attached photo files, only template cell values/URLs.

## Rollback

Revert these files:

- `v2-api/app/services/platform/templates.py`
- `scripts/verify_platform_external_completed_hierarchy_validation.py`
- `scripts/verify_platform_external_completed_hierarchy_validation_guard.js`
- `docs/superpowers/plans/2026-07-03-external-completed-hierarchy-validation.md`
- `docs/reports/pm-platform-external-completed-hierarchy-validation-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

Then rerun:

```powershell
python scripts\verify_platform_line_loss_template_contract.py
pnpm --dir v2-web build
```
