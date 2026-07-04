# PM Platform Device Hierarchy Readiness Gate

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Summary

The platform readiness check now validates device replacement hierarchy before a project is treated as ready.

The new `device_hierarchy` check passes correctly structured replacement projects and blocks flat terminal-replacement schemas where accessory confirmations or conditional child fields are missing.

## Changed Files

- `v2-api/app/services/platform/readiness.py`
- `v2-api/tests/test_platform_project_readiness.py`
- `scripts/verify_platform_project_readiness.py`
- `scripts/verify_vue_project_readiness_panel.js`
- `v2-web/src/views/ProjectsView.vue`
- `docs/superpowers/plans/2026-07-03-device-hierarchy-readiness-gate.md`
- `docs/reports/pm-platform-device-hierarchy-readiness-gate-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

## Verification

Commands:

- `python -m pytest v2-api\tests\test_platform_project_readiness.py`
  - Red check before implementation: failed because `device_hierarchy` was missing.
  - Green check after implementation: `4 passed`.
- `python scripts\verify_platform_project_readiness.py`
  - Result: `[OK] platform project readiness is consistent`.
- `python scripts\verify_platform_device_relation_roles.py`
  - Result: `[OK] platform device relation roles are preserved`.
- `node scripts\verify_vue_project_readiness_panel.js`
  - Result: `[OK] Project readiness panel is wired to the frontend.`
- `pnpm --dir v2-web build`
  - Result: passed. Existing VueUse annotation and large chunk warnings remain.

## Risk Notes

- This is a read-only readiness gate. It does not write production data and does not change persistence schema.
- Existing non-device projects pass the check when they have no device replacement relation roles.
- Device-replacement projects that were previously flat may now be shown as not ready until users add relation roles and conditional child fields.

## Rollback Notes

- Revert the files listed above.
- Rebuild Vue static assets from reverted source if generated assets are included.
- No production rollback is needed because no production deployment, migration, tag, version bump, OSS write, PostgreSQL write, or production data edit occurred.
