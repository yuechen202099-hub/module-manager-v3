# Delivery Archive Readiness Summary Plan

## Baseline

- Repository: `module-manager-v3`
- Platform branch: `pm-platform/production-3.0.77-sync`
- Production baseline branch: `production/V3/3.0.77`
- Baseline commit at work start: `6892205`

## Goal

Expose a read-only delivery archive readiness summary for configurable platform projects before any archive write path is introduced.

The summary must help operators answer:

- Which work orders are already approved and ready to package.
- Which work orders are still waiting for review.
- Which work orders were returned for rework.
- Which work orders have required field or photo evidence gaps.
- Which work orders have not started or are in exception status.

## Product Rules

- The check must respect the field hierarchy contract:
  - module replacement stays task object -> accessory device replacement;
  - terminal replacement stays task object -> main device replacement -> accessory replacement confirmation;
  - conditional accessory values and photos are required only when their `required_when` trigger is active.
- The summary is read-only. It must not create archive records, mutate review status, or write production data.
- The project board must show the archive readiness panel even when old platform task KPI totals are absent.

## Implementation Steps

1. Add a backend read-only readiness builder based on existing platform work orders, construction collections, review status, and required evidence validation.
2. Add `GET /projects/{project_id}/delivery/archive-readiness`.
3. Add frontend API types, mapper, and fetch function.
4. Show a project-board archive readiness panel with ready, pending review, evidence gap, returned rework, not-ready, and exception counts.
5. Keep the panel independent from legacy task KPI visibility.
6. Add guard scripts for backend readiness and frontend wiring.
7. Verify with focused scripts, production build, and local browser smoke.

## Data And Safety

- No database migration.
- No PostgreSQL or OSS write path.
- No production data edit.
- No `.env`, uploads, dumps, build archives, tag, deployment, or production version bump.

## Rollback

- Remove `build_platform_delivery_archive_readiness` and the `/delivery/archive-readiness` route.
- Remove frontend archive readiness types, mapper, fetch call, computed cards, and project-board panel.
- Remove `scripts/verify_platform_delivery_archive_readiness.py` and `scripts/verify_vue_delivery_archive_readiness.js`.
- Rebuild Vue static assets after reverting frontend files.
