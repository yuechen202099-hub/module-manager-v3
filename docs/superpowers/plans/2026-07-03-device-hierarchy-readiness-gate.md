# Device Hierarchy Readiness Gate Plan

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Objective

Make the backend onboarding check reject device-replacement projects whose fields are visually or structurally flat.

The field graph already helps operators configure replacement hierarchy. This package makes the saved project readiness check enforce the same rule before template import, construction collection, review, and archive.

## Scope

- Add a `device_hierarchy` readiness check.
- Pass non-device projects without forcing replacement-specific fields.
- When device replacement fields exist, verify:
  - device fields keep an explicit parent link to the task object,
  - terminal/main-device replacement has accessory replacement confirmations,
  - accessory confirmations have conditional child fields,
  - accessory child fields are not unconditional in main-device replacement projects,
  - fields that look like replacement confirmations are explicitly marked as `accessory_replace_confirm`.
- Add non-technical frontend labels for the new check and next action.
- Do not change database schema, permissions, import/export APIs, OSS, PostgreSQL, production version, tags, or deployment.

## Verification Plan

- `python -m pytest v2-api\tests\test_platform_project_readiness.py`
- `python scripts\verify_platform_project_readiness.py`
- `python scripts\verify_platform_device_relation_roles.py`
- `node scripts\verify_vue_project_readiness_panel.js`
- `pnpm --dir v2-web build`

## Migration Notes

No migration. The package adds read-only readiness validation logic and frontend display labels only.

## Rollback

- Revert `v2-api/app/services/platform/readiness.py`.
- Revert `v2-api/tests/test_platform_project_readiness.py`.
- Revert `scripts/verify_platform_project_readiness.py`.
- Revert `scripts/verify_vue_project_readiness_panel.js`.
- Revert `v2-web/src/views/ProjectsView.vue`.
- Rebuild Vue static assets from reverted source if generated assets are included.
- No production rollback is needed because no deployment, tag, version bump, OSS write, PostgreSQL write, or production data edit occurred.
