# Single Aggregate Readiness Plan

Date: 2026-07-03

## Context

The backend schema guard and graphical field designer now enforce one active aggregate field. Project readiness should expose the same rule so onboarding status, readiness summaries, and older validation scripts do not drift from the field model.

## Scope

- Add `single_aggregate_field` to backend project readiness checks.
- Add `fix_aggregate_field` as the operator action for aggregate misuse.
- Keep valid projects passing readiness.
- Keep invalid flat device hierarchy tests aligned with the newer backend save guard by testing the readiness helper directly.
- Add frontend label/action text for the new readiness check.

## Safety

This package is read-only from a production-data perspective. It does not connect to PostgreSQL, run migrations, edit production data, touch OSS, change official version numbers, create tags, or deploy servers.

## Rollback

Revert:

- `v2-api/app/services/platform/readiness.py` `single_aggregate_field` check and action.
- `v2-api/tests/test_platform_project_readiness.py` readiness coverage changes.
- `scripts/verify_platform_single_aggregate_readiness.py`.
- `scripts/verify_vue_single_aggregate_readiness.js`.
- frontend label/action additions in `v2-web/src/views/ProjectsView.vue`.

Rebuild frontend static assets from the previous state if generated assets were included.
